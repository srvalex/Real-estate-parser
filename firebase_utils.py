import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import hashlib
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

def _url_to_doc_id(url: str) -> str:
    """Derive a stable, Firestore-safe document ID from a URL using an MD5 hash."""
    return hashlib.md5(url.encode()).hexdigest()


def save_to_firestore(data_list, collection_name='listings'):
    """
    Saves a list of dictionaries to Firestore.
    Uses an MD5 hash of the listing URL as the document ID so that
    re-inserting the same URL is always an upsert, never a duplicate.
    """
    db = init_firebase()
    if db is None or not data_list:
        return

    batch = db.batch()
    doc_count = 0

    for item in data_list:
        url = item.get('url') or item.get('link')
        doc_id = _url_to_doc_id(url) if url else None

        if doc_id:
            doc_ref = db.collection(collection_name).document(doc_id)
        else:
            doc_ref = db.collection(collection_name).document()

        batch.set(doc_ref, item, merge=True)
        doc_count += 1

        if doc_count % 500 == 0:
            batch.commit()
            batch = db.batch()
            print(f"  [firebase] Uploaded {doc_count} documents...")

    batch.commit()
    print(f"✅ Successfully saved {doc_count} records to Firestore collection '{collection_name}'.")

def query_listings_by_district(district_names: list, collection_name='listings') -> list:
    """Fetch all listings from Firestore whose district field matches any of the given neighborhoods.
    Batches into chunks of 30 to stay within Firestore's 'in' query limit.
    """
    db = init_firebase()
    if db is None or not district_names:
        return []

    results = []
    for i in range(0, len(district_names), 30):
        chunk = district_names[i:i + 30]
        docs = (
            db.collection(collection_name)
            .where(filter=FieldFilter('district', 'in', chunk))
            .where(filter=FieldFilter('is_available', '==', 1))
            .stream()
        )
        results.extend(doc.to_dict() for doc in docs)
    return results


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
