"""
check_chromadb.py
─────────────────
Run this as a cell in your Colab notebook to audit the ChromaDB contents.
Set CHROMA_PATH to wherever your persistent ChromaDB lives in Google Drive.
"""

import chromadb

CHROMA_PATH = "/content/drive/MyDrive/chroma_db"   # ← adjust to your actual path

client = chromadb.PersistentClient(path=CHROMA_PATH)

collections = client.list_collections()
if not collections:
    print("No collections found in ChromaDB.")
else:
    for col in collections:
        collection = client.get_collection(col.name)
        count = collection.count()

        print(f"\n{'─'*50}")
        print(f"Collection : {col.name}")
        print(f"Embeddings : {count:,}")

        if count > 0:
            # Peek at a small sample to verify URLs are stored correctly
            sample = collection.peek(limit=5)
            urls = sample.get("ids", [])
            metadatas = sample.get("metadatas", [])

            print(f"Sample IDs / URLs:")
            for i, uid in enumerate(urls):
                meta = metadatas[i] if metadatas else {}
                url = meta.get("url", uid)
                print(f"  [{i+1}] {url}")
        print(f"{'─'*50}")
