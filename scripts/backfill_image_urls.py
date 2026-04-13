"""
backfill_image_urls.py
──────────────────────
One-time script to populate image_urls for existing listings that don't have them.
Also sets is_available = 1 (listing still live) or 0 (taken down / error).

Usage:
    python backfill_image_urls.py              # backfill all
    python backfill_image_urls.py --limit 50   # backfill first 50
    python backfill_image_urls.py --platform olx   # backfill OLX only
"""

import json
import os
import sqlite3
import sys
import time
import argparse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from scrapers import SCRAPERS
from scrapers.storia import StoriaScraper
from scrapers.imobiliare import ImobiliareRoScraper
from firebase_utils import save_to_firestore, _url_to_doc_id, init_firebase

DB_PATH = os.path.join(ROOT, "Streamlit Interface", "real_estate.db")


"""
Availability states stored in is_available column:
  1   = confirmed available (listing is live, images fetched)
  0   = confirmed expired   (Storia returned ExpiredAdContentLayout — skip on reruns)
 -1   = blocked / transient (request failed or was blocked — retry next run)
 NULL = never processed
"""

def ensure_columns(conn):
    """Add image_urls and is_available columns if they don't exist."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    if "image_urls" not in existing:
        conn.execute("ALTER TABLE listings ADD COLUMN image_urls TEXT")
        print("📋 Added image_urls column.")
    if "is_available" not in existing:
        conn.execute("ALTER TABLE listings ADD COLUMN is_available INTEGER")
        print("📋 Added is_available column.")
    conn.commit()


def get_listings_to_backfill(conn, platform_id=None, limit=None, retry_expired=False):
    """
    Return listings that still need processing.

    Default: skip is_available=0 (confirmed expired). Process NULL, 1, and -1.
    retry_expired=True: also re-verify is_available=0 listings (migration tool).
    """
    if retry_expired:
        query = "SELECT url, platform_id FROM listings WHERE (image_urls IS NULL OR image_urls = '' OR image_urls = '[]')"
    else:
        # Exclude confirmed-expired (0). Include: NULL, available (1), blocked (-1).
        query = (
            "SELECT url, platform_id FROM listings "
            "WHERE (image_urls IS NULL OR image_urls = '' OR image_urls = '[]') "
            "AND (is_available IS NULL OR is_available <> 0)"
        )
    params = []
    if platform_id:
        query += " AND platform_id = ?"
        params.append(platform_id)
    if limit:
        query += f" LIMIT {int(limit)}"
    return conn.execute(query, params).fetchall()


def update_row(conn, url, image_urls_json, is_available):
    """Update a single listing in SQLite. Pass image_urls_json=None to leave it as NULL."""
    conn.execute(
        "UPDATE listings SET image_urls = ?, is_available = ? WHERE url = ?",
        (image_urls_json, is_available, url),
    )
    conn.commit()


def update_firestore_row(url, image_urls_list, is_available):
    """
    Update a single listing in Firestore.
    image_urls_list=None → don't touch image_urls field (blocked state).
    """
    try:
        db = init_firebase()
        if db is None:
            return
        doc_id = _url_to_doc_id(url)
        update = {"is_available": is_available}
        if image_urls_list is not None:   # None = blocked, don't overwrite
            update["image_urls"] = image_urls_list
        db.collection("listings").document(doc_id).update(update)
    except Exception:
        pass  # Firestore errors are non-blocking


def backfill_olx(conn, urls, delay=1.2):
    """
    Backfill OLX listings one at a time using the 3-state model:
      success → is_available=1
      expired → is_available=0  (ad-inactive-msg detected — skip on reruns)
      blocked → is_available=-1 (network/parse error — retry next run)
    Returns (success, expired, blocked).
    """
    scraper = SCRAPERS["olx"]
    success, expired, blocked = 0, 0, 0
    slug = lambda u: u.split("/d/")[-1][:55] if "/d/" in u else u[-55:]

    for i, url in enumerate(urls, 1):
        result = scraper.scrape_listing_with_status(url)
        status = result["status"]

        if status == "success":
            images = result["data"].get("image_urls", [])
            images_json = json.dumps(images, ensure_ascii=False)
            update_row(conn, url, images_json, 1)
            update_firestore_row(url, images, 1)
            success += 1
            print(f"  [{i}/{len(urls)}] ✅ ok ({len(images)} imgs) — {slug(url)}")

        elif status == "expired":
            update_row(conn, url, "[]", 0)
            update_firestore_row(url, [], 0)
            expired += 1
            print(f"  [{i}/{len(urls)}] ❌ expired — {slug(url)}")

        else:  # blocked
            update_row(conn, url, None, -1)
            update_firestore_row(url, None, -1)
            blocked += 1
            print(f"  [{i}/{len(urls)}] 🔒 blocked — {slug(url)}")

        time.sleep(delay)

    return success, expired, blocked


def backfill_storia(conn, urls, batch_size=10, delay=2.0):
    """
    Backfill Storia listings in batches via subprocess.
    Returns (success, expired, blocked) counts.
    """
    scraper = SCRAPERS["storia"]
    success, expired, blocked = 0, 0, 0
    total_batches = (len(urls) + batch_size - 1) // batch_size

    for i in range(0, len(urls), batch_size):
        chunk = urls[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        processed_urls = set()

        try:
            raw_results = scraper._fetch_batch_raw(chunk)

            for raw in raw_results:
                raw_url = raw.get("url", "")
                processed_urls.add(raw_url)
                status = raw.get("status", "blocked")
                data   = raw.get("data") if isinstance(raw, dict) else {}

                if status == "expired":
                    # Storia confirmed this listing is gone via ExpiredAdContentLayout.
                    update_row(conn, raw_url, "[]", 0)
                    update_firestore_row(raw_url, [], 0)
                    expired += 1
                    print(f"    ❌ expired  — {raw_url.split('/oferta/')[-1][:55]}")

                elif status == "success" and data and isinstance(data, dict):
                    raw_images = data.get("images", [])
                    images = [
                        {k: v for k, v in img.items() if k in ("thumbnail", "small", "medium", "large")}
                        for img in raw_images if isinstance(img, dict)
                    ]
                    images_json = json.dumps(images, ensure_ascii=False)
                    update_row(conn, raw_url, images_json, 1)
                    update_firestore_row(raw_url, images, 1)
                    success += 1
                    print(f"    ✅ ok ({len(images)} imgs) — {raw_url.split('/oferta/')[-1][:55]}")

                else:
                    # status == "blocked" or unexpected — transient, retry next run.
                    update_row(conn, raw_url, None, -1)
                    update_firestore_row(raw_url, None, -1)
                    blocked += 1
                    print(f"    🔒 blocked  — {raw_url.split('/oferta/')[-1][:55]}")

            # URLs not returned at all → batch-level failure (Playwright crash, etc.)
            for url in chunk:
                if url not in processed_urls:
                    update_row(conn, url, None, -1)
                    update_firestore_row(url, None, -1)
                    blocked += 1

        except Exception as e:
            # Entire batch failed — mark all as blocked for retry.
            print(f"  Batch {batch_num}/{total_batches}: ❌ {e}")
            for url in chunk:
                if url not in processed_urls:
                    update_row(conn, url, None, -1)
                    update_firestore_row(url, None, -1)
                    blocked += 1

        print(f"  Batch {batch_num}/{total_batches} — ✅ {success} ok | ❌ {expired} expired | 🔒 {blocked} blocked (cumulative)")
        time.sleep(delay)

    return success, expired, blocked


def backfill_imobiliare(conn, urls, batch_size=10, delay=2.0):
    """
    Backfill Imobiliare.ro listings in batches via subprocess.
    Returns (success, expired, blocked) counts.
    """
    scraper = SCRAPERS["imobiliare"]
    success, expired, blocked = 0, 0, 0
    total_batches = (len(urls) + batch_size - 1) // batch_size

    for i in range(0, len(urls), batch_size):
        chunk = urls[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        processed_urls = set()

        try:
            raw_results = scraper._fetch_batch_raw(chunk)

            for raw in raw_results:
                raw_url = raw.get("url", "")
                processed_urls.add(raw_url)
                status = raw.get("status", "blocked")

                if status == "expired":
                    update_row(conn, raw_url, "[]", 0)
                    update_firestore_row(raw_url, [], 0)
                    expired += 1
                    print(f"    ❌ expired  — {raw_url.split('/oferta/')[-1][:55]}")

                elif status == "success":
                    parsed = scraper._parse_raw(raw)
                    images = parsed.get("image_urls", []) if parsed else []
                    images_json = json.dumps(images, ensure_ascii=False)
                    update_row(conn, raw_url, images_json, 1)
                    update_firestore_row(raw_url, images, 1)
                    success += 1
                    print(f"    ✅ ok ({len(images)} imgs) — {raw_url.split('/oferta/')[-1][:55]}")

                else:
                    update_row(conn, raw_url, None, -1)
                    update_firestore_row(raw_url, None, -1)
                    blocked += 1
                    print(f"    🔒 blocked  — {raw_url.split('/oferta/')[-1][:55]}")

            for url in chunk:
                if url not in processed_urls:
                    update_row(conn, url, None, -1)
                    update_firestore_row(url, None, -1)
                    blocked += 1

        except Exception as e:
            print(f"  Batch {batch_num}/{total_batches}: ❌ {e}")
            for url in chunk:
                if url not in processed_urls:
                    update_row(conn, url, None, -1)
                    update_firestore_row(url, None, -1)
                    blocked += 1

        print(f"  Batch {batch_num}/{total_batches} — ✅ {success} ok | ❌ {expired} expired | 🔒 {blocked} blocked (cumulative)")
        time.sleep(delay)

    return success, expired, blocked


def main():
    parser = argparse.ArgumentParser(description="Backfill image_urls for existing listings")
    parser.add_argument("--limit",    type=int, default=None, help="Max listings to process")
    parser.add_argument("--platform", choices=["olx", "storia", "imobiliare"], default=None)
    parser.add_argument("--retry-expired", action="store_true",
                        help="Also re-verify listings already marked is_available=0 (confirmed expired). "
                             "Useful as a one-time migration after upgrading to 3-state availability.")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    ensure_columns(conn)

    rows = get_listings_to_backfill(conn, args.platform, args.limit, args.retry_expired)
    print(f"\n🔍 Found {len(rows)} listings to process\n")

    if not rows:
        print("Nothing to do!")
        conn.close()
        return

    by_platform = {}
    for url, pid in rows:
        if not pid:
            if "olx.ro" in url:            pid = "olx"
            elif "storia.ro" in url:       pid = "storia"
            elif "imobiliare.ro" in url:   pid = "imobiliare"
            else:                          pid = "unknown"
        by_platform.setdefault(pid, []).append(url)

    total_ok = total_expired = total_blocked = 0

    for pid, urls in by_platform.items():
        if pid == "unknown":
            print(f"⚠️ Skipping {len(urls)} with unrecognized URLs")
            continue

        print(f"{'='*60}")
        print(f"🔶 {pid.upper()} — {len(urls)} listings")
        print(f"{'='*60}")

        if pid == "olx":
            s, e, b = backfill_olx(conn, urls)
            total_ok += s; total_expired += e; total_blocked += b
        elif pid == "storia":
            s, e, b = backfill_storia(conn, urls)
            total_ok += s; total_expired += e; total_blocked += b
        elif pid == "imobiliare":
            s, e, b = backfill_imobiliare(conn, urls)
            total_ok += s; total_expired += e; total_blocked += b
        else:
            print(f"  No handler for: {pid}")

    conn.close()
    print(f"\n{'='*60}")
    print(f"✅ Available: {total_ok}  |  ❌ Expired: {total_expired}  |  🔒 Blocked (retry): {total_blocked}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
