import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

# Replace with the path to your Firebase service account key JSON file
SERVICE_ACCOUNT_KEY_PATH = os.path.join(os.path.dirname(__file__), 'real-estate-parser-f44a0-firebase-adminsdk-fbsvc-56cddcced1.json')

_db = None

def init_firebase():
    """Initializes Firebase Admin SDK if not already initialized."""
    global _db
    if _db is not None:
        return _db
    
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
            firebase_admin.initialize_app(cred)
        _db = firestore.client()
        print("✅ Firebase Admin SDK initialized successfully.")
        return _db
    except Exception as e:
        print(f"❌ Error initializing Firebase Admin SDK: {e}")
        return None

def save_to_firestore(data_list, collection_name='listings'):
    """
    Saves a list of dictionaries to Firestore.
    Uses 'link' as the document ID for deduplication.
    """
    db = init_firebase()
    if db is None or not data_list:
        return

    batch = db.batch()
    doc_count = 0

    for item in data_list:
        # We use the 'url' or 'link' as a unique ID to avoid duplicates in Firestore
        # Since 'link' is often a full URL, we might need to sanitize it or just use it.
        # Firestore IDs can be problematic with certain characters, but simple URLs are usually fine.
        # However, extractor.py uses 'url' as the primary key-like field.
        doc_id = item.get('id') or item.get('link')
        if not doc_id:
            doc_ref = db.collection(collection_name).document()
        else:
            # Firestore document IDs cannot contain /
            # Let's use 'id' if possible, otherwise let Firebase generate one or sanitize link.
            # actually, if we use the 'id' field from OLX/Storia, it's safer.
            doc_ref = db.collection(collection_name).document(str(doc_id))

        batch.set(doc_ref, item, merge=True)
        doc_count += 1

        if doc_count % 500 == 0:
            batch.commit()
            batch = db.batch()
            print(f"  [firebase] Uploaded {doc_count} documents...")

    batch.commit()
    print(f"✅ Successfully saved {doc_count} records to Firestore collection '{collection_name}'.")

def get_all_firestore_urls(collection_name='listings'):
    """Returns a set of all URLs currently stored in Firestore."""
    db = init_firebase()
    if db is None:
        return set()
    
    docs = db.collection(collection_name).stream()
    return {doc.to_dict().get('url') for doc in docs if doc.to_dict().get('url')}

if __name__ == "__main__":
    # Quick test
    db = init_firebase()
    if db:
        print("Connected to Firestore.")
    else:
        print("Failed to connect.")
