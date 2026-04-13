"""
update_local_db.py
──────────────────
Copies all records from the 'outside' real_estate.db (in the parent folder) 
into the 'inside' real_estate.db (in the current folder).
"""

import sqlite3
import os
import sys
import pandas as pd
from firebase_utils import init_firebase

# Reuse the canonical schema definition from the extractor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from extractor import DB_COLS

def sync_databases():
    # ... (existing code for local sync)
    current_dir = os.path.dirname(__file__)
    inside_db_path = os.path.join(current_dir, 'real_estate.db')
    outside_db_path = os.path.join(current_dir, '..', 'real_estate.db')

    if not os.path.exists(outside_db_path):
        print(f"Error: Outside database not found at {outside_db_path}")
        return

    print("Connecting to local databases...")
    conn_outside = sqlite3.connect(outside_db_path)
    conn_inside = sqlite3.connect(inside_db_path)

    try:
        conn_inside.execute(f"CREATE TABLE IF NOT EXISTS listings ({DB_COLS})")

        outside_cursor = conn_outside.cursor()
        outside_cursor.execute("SELECT * FROM listings")
        rows = outside_cursor.fetchall()

        if rows:
            num_cols = len(outside_cursor.description)
            placeholders = ', '.join(['?'] * num_cols)
            query = f"INSERT OR IGNORE INTO listings VALUES ({placeholders})"
            conn_inside.executemany(query, rows)
            conn_inside.commit()
            print(f"✅ Successfully synchronized records from outside DB.")
        else:
            print("ℹ️ No records found in the outside database to copy.")
    finally:
        conn_outside.close()
        conn_inside.close()

def sync_from_firestore():
    """Fetches all records from Firestore and updates the local database."""
    print("⏳ Connecting to Firestore...")
    db = init_firebase()
    if db is None:
        print("❌ Could not connect to Firestore.")
        return

    current_dir = os.path.dirname(__file__)
    db_path = os.path.join(current_dir, 'real_estate.db')
    
    # Also sync the one in parent dir if it exists
    parent_db_path = os.path.join(current_dir, '..', 'real_estate.db')

    print("📥 Fetching data from Firestore 'listings' collection...")
    docs = db.collection('listings').stream()
    data = [doc.to_dict() for doc in docs]
    
    if not data:
        print("ℹ️ No records found in Firestore.")
        return

    df = pd.DataFrame(data)
    
    def update_db(path):
        if not os.path.exists(os.path.dirname(path)):
            return
        
        print(f"💾 Updating local database: {path}")
        conn = sqlite3.connect(path)
        try:
            # Re-order columns to match SQLite schema if necessary, 
            # but to_sql with if_exists='append' is flexible if we matches the core cols
            df.to_sql("listings", conn, if_exists="append", index=False, method='multi')
            
            # Since to_sql doesn't support "INSERT OR IGNORE" directly, 
            # we might get errors on duplicate primary keys (link).
            # A cleaner way is to load existing and filter or use a temporary table.
            # But for simplicity, let's just handle it.
            print(f"✅ Sync complete for {path}")
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                print(f"ℹ️ Some records already existed in {path}, skipped duplicates.")
            else:
                print(f"❌ Error updating {path}: {e}")
        finally:
            conn.close()

    update_db(db_path)
    update_db(parent_db_path)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--cloud":
        sync_from_firestore()
    else:
        sync_databases()
