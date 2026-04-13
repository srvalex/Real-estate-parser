"""
backfill_image_embeddings.py
────────────────────────────
Embed all existing listing photos into the ChromaDB `listing_image_embeddings`
collection using the Colab CLIP server.

Fully resumable — already-embedded photos are skipped on every run.

Usage:
    python backfill_image_embeddings.py --server https://xxx.ngrok.io
    python backfill_image_embeddings.py --server https://xxx.ngrok.io --platform storia
    python backfill_image_embeddings.py --server https://xxx.ngrok.io --limit 200
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time

import requests

ROOT           = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CHROMA_DB_PATH = os.path.join(ROOT, "ChromaDB")
COLLECTION_NAME = "listing_image_embeddings"
DB_PATH        = os.path.join(ROOT, "Streamlit Interface", "real_estate.db")
BATCH_SIZE     = 10


def _url_to_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def load_collection():
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def get_existing_ids(collection) -> set:
    """Fetch all IDs already in the collection without loading embeddings."""
    result = collection.get(include=[])
    return set(result["ids"])


def get_listings_with_images(conn, platform_id=None, limit=None):
    query = """
        SELECT url, platform_id, image_urls
        FROM listings
        WHERE image_urls IS NOT NULL
          AND image_urls != ''
          AND image_urls != '[]'
    """
    params = []
    if platform_id:
        query += " AND platform_id = ?"
        params.append(platform_id)
    if limit:
        query += f" LIMIT {int(limit)}"
    return conn.execute(query, params).fetchall()


def embed_batch(server_url: str, photo_urls: list) -> list:
    resp = requests.post(
        f"{server_url}/embed",
        json={"urls": photo_urls},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def main():
    parser = argparse.ArgumentParser(description="Backfill image embeddings into ChromaDB")
    parser.add_argument("--server", required=True,
                        help="Colab CLIP server URL (ngrok), e.g. https://xxx.ngrok.io")
    parser.add_argument("--platform", choices=["olx", "storia"], default=None,
                        help="Only embed photos from this platform")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max listings to process (for testing)")
    args = parser.parse_args()

    server_url = args.server.rstrip("/")

    # ── Health check ──────────────────────────────────────────────────────────
    try:
        resp = requests.get(f"{server_url}/health", timeout=10)
        resp.raise_for_status()
        info = resp.json()
        print(f"CLIP server OK — device: {info.get('device', '?')}")
    except Exception as e:
        print(f"Server unreachable at {server_url}: {e}")
        sys.exit(1)

    # ── Load ChromaDB + existing IDs ──────────────────────────────────────────
    print("Loading ChromaDB collection...")
    collection   = load_collection()
    existing_ids = get_existing_ids(collection)
    print(f"Already embedded: {len(existing_ids)} photos\n")

    # ── Read listings from SQLite ─────────────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    rows = get_listings_with_images(conn, args.platform, args.limit)
    conn.close()
    print(f"Listings with images: {len(rows)}")

    # ── Build embedding queue (skip already done, deduplicate URLs) ───────────
    to_embed: list[tuple[str, str, int]] = []
    seen_urls: set[str] = set()

    for listing_url, _platform_id, image_urls_raw in rows:
        try:
            images = json.loads(image_urls_raw)
        except Exception:
            continue
        if not isinstance(images, list):
            continue

        for pos, img in enumerate(images):
            photo_url = (img.get("medium") or img.get("small")
                         or img.get("large") or img.get("thumbnail") or "")
            if not photo_url or photo_url in seen_urls:
                continue
            doc_id = _url_to_id(photo_url)
            if doc_id in existing_ids:
                continue
            seen_urls.add(photo_url)
            to_embed.append((listing_url, photo_url, pos))

    total = len(to_embed)
    print(f"Photos to embed: {total}")
    if total == 0:
        print("Nothing to do — all photos are already embedded.")
        return

    num_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"Batches: {num_batches} × {BATCH_SIZE}\n")

    # ── Embed in batches ──────────────────────────────────────────────────────
    embedded = 0
    errors   = 0
    t_start  = time.time()

    for batch_num, i in enumerate(range(0, total, BATCH_SIZE), 1):
        batch      = to_embed[i:i + BATCH_SIZE]
        photo_urls = [p for _, p, _ in batch]
        meta_map   = {p: (lu, pos) for lu, p, pos in batch}

        try:
            results = embed_batch(server_url, photo_urls)
        except Exception as e:
            errors += len(batch)
            print(f"  Batch {batch_num}/{num_batches}: ERROR — {e}")
            continue

        ids, embeddings, metadatas, documents = [], [], [], []
        for r in results:
            if "error" in r or "embedding" not in r:
                errors += 1
                continue
            photo_url               = r["url"]
            listing_url, pos        = meta_map.get(photo_url, ("", 0))
            doc_id                  = _url_to_id(photo_url)

            ids.append(doc_id)
            embeddings.append(r["embedding"])
            metadatas.append({
                "listing_url": listing_url,
                "image_url":   photo_url,
                "room_labels": ", ".join(r.get("labels", ["other"])),
                "position":    pos,
            })
            documents.append(photo_url)

        if ids:
            collection.upsert(
                ids=ids, embeddings=embeddings,
                metadatas=metadatas, documents=documents,
            )
            embedded += len(ids)

        # ── Progress ──────────────────────────────────────────────────────────
        done      = min(i + BATCH_SIZE, total)
        elapsed   = time.time() - t_start
        rate      = done / elapsed if elapsed > 0 else 0
        remaining = (total - done) / rate / 60 if rate > 0 else 0
        print(f"  [{done:>5}/{total}] embedded: {embedded} | errors: {errors} "
              f"| ~{remaining:.0f} min left")

    elapsed_total = time.time() - t_start
    print(f"\nDone in {elapsed_total/60:.1f} min")
    print(f"Embedded: {embedded} | Errors: {errors}")
    print(f"Collection size: {collection.count()} photos")


if __name__ == "__main__":
    main()
