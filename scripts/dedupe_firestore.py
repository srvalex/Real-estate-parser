"""
dedupe_firestore.py
────────────────────
Removes duplicate listings from Firestore (same `url` field).
Keeps the record with the latest `scraped_at`; deletes the rest.
Run locally — uses the service account key already in the project folder.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import firebase_admin
from firebase_admin import credentials, firestore
from collections import defaultdict
from firebase_utils import init_firebase

db = init_firebase()

print("📥 Fetching all listings from Firestore...")
docs = list(db.collection("listings").stream())
print(f"   Total documents: {len(docs):,}")

# Group document references by url
groups = defaultdict(list)
no_url = []

for doc in docs:
    data = doc.to_dict()
    url = data.get("url") or data.get("link")
    if url:
        groups[url].append((doc.reference, data))
    else:
        no_url.append(doc.reference)

duplicates = {url: refs for url, refs in groups.items() if len(refs) > 1}
print(f"   Unique URLs     : {len(groups):,}")
print(f"   URLs with dupes : {len(duplicates):,}")
print(f"   Docs without URL: {len(no_url):,}")

if not duplicates:
    print("\n✅ No duplicates found.")
else:
    to_delete = []

    for url, refs_and_data in duplicates.items():
        # Sort by scraped_at descending — keep the newest, delete the rest
        def sort_key(item):
            return item[1].get("scraped_at") or ""

        refs_and_data.sort(key=sort_key, reverse=True)
        # Keep index 0 (newest), queue the rest for deletion
        for ref, _ in refs_and_data[1:]:
            to_delete.append(ref)

    print(f"\n🗑️  Deleting {len(to_delete):,} duplicate documents...")

    # Firestore batch delete (max 500 per batch)
    BATCH_SIZE = 500
    for i in range(0, len(to_delete), BATCH_SIZE):
        batch = db.batch()
        for ref in to_delete[i : i + BATCH_SIZE]:
            batch.delete(ref)
        batch.commit()
        print(f"   Deleted {min(i + BATCH_SIZE, len(to_delete)):,} / {len(to_delete):,}")

    print(f"\n✅ Done. Removed {len(to_delete):,} duplicates.")
    print(f"   Remaining documents: {len(docs) - len(to_delete):,}")
