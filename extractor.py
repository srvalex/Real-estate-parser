"""
extractor.py
────────────
Platform-agnostic extraction pipeline.

Platform-specific logic lives entirely in scrapers/.
Adding a new source = add a scraper there; this file never changes.

run_pipeline() accepts a list of scrape jobs:
    jobs = [
        {"platform_id": "olx",    "urls": [...], "pages": 1},
        {"platform_id": "storia",  "urls": [...], "pages": 1},
    ]
"""

import json
import pandas as pd
import time
import sqlite3
from tqdm import tqdm
from datetime import datetime
import os
from db_utils import save_to_firestore
from scrapers import SCRAPERS
from scrapers.storia import StoriaScraper
from scrapers.imobiliare import ImobiliareRoScraper

# ─────────────────────────────────────────────
#  Database
# ─────────────────────────────────────────────

DB_NAME = os.path.join(os.path.dirname(__file__), "Streamlit Interface", "real_estate.db")

_embed_model = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            print("  [embed] Loading SentenceTransformer…")
            _embed_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        except Exception as e:
            print(f"  [embed] Model unavailable, skipping embeddings: {e}")
    return _embed_model


DB_COLS = (
    "url TEXT PRIMARY KEY, platform_id TEXT, platform TEXT, source_id TEXT, "
    "title TEXT, price_eur TEXT, rent TEXT, price TEXT, description TEXT, "
    "district TEXT, location_full_name TEXT, rooms TEXT, area_sqm TEXT, "
    "features TEXT, scraped_at TEXT"
)


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_NAME)
    conn.execute(f"CREATE TABLE IF NOT EXISTS listings ({DB_COLS})")
    return conn


def _evolve_schema(conn: sqlite3.Connection, df: pd.DataFrame):
    """Add columns present in df but missing from the SQLite table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    new_cols = [col for col in df.columns if col not in existing]
    for col in new_cols:
        conn.execute(f'ALTER TABLE listings ADD COLUMN "{col}" TEXT')
        print(f"  [schema] Added column: {col}")
    if new_cols:
        conn.commit()


def _save_new_listings(new_results: list, conn: sqlite3.Connection) -> pd.DataFrame:
    """Persist new listings to SQLite and Firestore. Returns saved DataFrame."""
    if not new_results:
        return pd.DataFrame()

    # Serialize image_urls (list[dict]) → JSON string for SQLite column storage.
    # Preserve the original lists so Firestore receives native arrays.
    original_images = {}
    for item in new_results:
        if "image_urls" in item and isinstance(item["image_urls"], list):
            original_images[item.get("url", "")] = item["image_urls"]
            item["image_urls"] = json.dumps(item["image_urls"], ensure_ascii=False)

    # Generate text embeddings for live listings before saving to Supabase.
    model = _get_embed_model()
    if model:
        for item in new_results:
            if item.get("is_available", 1) == 1 and "embedding" not in item:
                text = (item.get("description") or item.get("title") or "").strip()
                if text:
                    try:
                        item["embedding"] = model.encode(text, normalize_embeddings=True).tolist()
                    except Exception:
                        pass

    df_new = pd.DataFrame(new_results)
    df_new["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # SQLite cannot store vector lists — drop the embedding column for local insert.
    df_sqlite = df_new.drop(columns=["embedding"], errors="ignore")
    _evolve_schema(conn, df_sqlite)

    try:
        df_sqlite.to_sql("listings", conn, if_exists="append", index=False)
        print(f"💾 Saved {len(df_new)} new records to SQLite.")
    except Exception as e:
        print(f"⚠️ Batch insert failed ({e}), retrying row by row…")
        saved, failed = 0, 0
        for _, row in df_sqlite.iterrows():
            try:
                row.to_frame().T.to_sql("listings", conn, if_exists="append", index=False)
                saved += 1
            except Exception as row_err:
                print(f"  [skip] {row.get('url', '?')}: {row_err}")
                failed += 1
        print(f"💾 Row-by-row: {saved} saved, {failed} skipped.")

    # Restore original image_urls lists for Firestore (native array support)
    try:
        firestore_records = df_new.where(pd.notnull(df_new), None).to_dict(orient="records")
        for rec in firestore_records:
            url = rec.get("url", "")
            if url in original_images:
                rec["image_urls"] = original_images[url]
        save_to_firestore(firestore_records)
    except Exception as e:
        print(f"⚠️ Firestore save failed: {e}")

    return df_new


# ─────────────────────────────────────────────
#  Pipeline
# ─────────────────────────────────────────────

def run_pipeline(
    jobs: list[dict],
    out_csv: str = "results.csv",
):
    """
    Full extraction pipeline. Platform-agnostic.
    Yields (status, partial_df):
        "db_cache"  → rows already in SQLite for the requested URLs
        "progress"  → each freshly scraped listing or batch
        "done"      → final combined DataFrame

    Args:
        jobs: list of dicts, each with keys:
              platform_id (str), urls (list[str]), pages (int)
    """
    conn = init_db()

    # ── 1. Collect all listing links across all platforms ─────────────────────
    all_links: list[tuple[str, str]] = []   # (url, platform_id)
    for job in jobs:
        scraper = SCRAPERS.get(job["platform_id"])
        if not scraper:
            print(f"  [warning] Unknown platform: {job['platform_id']}, skipping.")
            continue
        for search_url in job["urls"]:
            links = scraper.collect_links(search_url, job.get("pages", 1))
            all_links.extend((link, job["platform_id"]) for link in links)

    # Deduplicate by URL
    seen = set()
    unique_links = []
    for url, pid in all_links:
        if url not in seen:
            seen.add(url)
            unique_links.append((url, pid))

    if not unique_links:
        print("⚠️ No links found.")
        yield "done", pd.DataFrame()
        return

    all_urls = [url for url, _ in unique_links]
    print(f"  Total unique links: {len(all_urls)}")

    # ── 2. Check SQLite cache ─────────────────────────────────────────────────
    placeholders = ", ".join(["?"] * len(all_urls))
    df_cached = pd.read_sql_query(
        f"SELECT * FROM listings WHERE url IN ({placeholders})",
        conn, params=all_urls,
    )
    cached_urls = set(df_cached["url"].tolist())
    print(f"📊 Cache: {len(df_cached)} found | To scrape: {len(all_urls) - len(cached_urls)}")

    yield "db_cache", df_cached

    # ── 3. Scrape new listings, grouped by platform ───────────────────────────
    # Re-classify each URL by domain ownership — OLX search pages can contain
    # redirect links pointing to Storia, so the collector's platform_id may
    # not match the actual URL domain.
    def _owner(url: str) -> str:
        for sid, s in SCRAPERS.items():
            if s.owns_url(url):
                return sid
        return "unknown"

    to_scrape: dict[str, list[str]] = {}
    for url, _ in unique_links:
        if url not in cached_urls:
            pid = _owner(url)
            if pid != "unknown":
                to_scrape.setdefault(pid, []).append(url)
            else:
                print(f"  [skip] No scraper owns URL: {url}")

    all_new = []

    for pid, urls in to_scrape.items():
        scraper = SCRAPERS[pid]

        # Batch scrapers (Storia, Imobiliare) use subprocess rendering
        if isinstance(scraper, (StoriaScraper, ImobiliareRoScraper)):
            print(f"\n🔷 Scraping {len(urls)} new {scraper.display_name} listings…")
            for i in tqdm(range(0, len(urls), scraper.BATCH_SIZE), desc=scraper.display_name, ncols=70):
                chunk = urls[i: i + scraper.BATCH_SIZE]
                batch = scraper.scrape_batch(chunk)
                if batch:
                    # blocked → is_available is None; skip them (retried next crawl)
                    definitive = [r for r in batch if r.get("is_available") is not None]
                    all_new.extend(definitive)
                    # Only yield live listings to the UI — tombstones have no display data
                    live = [r for r in definitive if r.get("is_available", 1) == 1]
                    if live:
                        yield "progress", pd.DataFrame(live)
                time.sleep(2)

        # All other platforms: one listing at a time
        else:
            print(f"\n🔶 Scraping {len(urls)} new {scraper.display_name} listings…")
            for url in tqdm(urls, desc=scraper.display_name, ncols=70):
                result = scraper.scrape_listing_with_status(url)
                status = result.get("status")
                if status == "success":
                    data = result["data"]
                    data["is_available"] = 1
                    all_new.append(data)
                    yield "progress", pd.DataFrame([data])
                elif status == "expired":
                    # Write a minimal tombstone row so reruns skip this URL
                    all_new.append({
                        "url":          url,
                        "platform_id":  pid,
                        "is_available": 0,
                        "scraped_at":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                # blocked → don't write anything, will be retried next scrape
                time.sleep(1.2)

    # ── 4. Save & finalize ────────────────────────────────────────────────────
    df_new = _save_new_listings(all_new, conn)
    combined = pd.concat([df_cached, df_new], ignore_index=True)
    conn.close()

    out_path = os.path.join(os.path.dirname(__file__), out_csv)
    combined.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n✅ Done. Total: {len(combined)} listings.")

    yield "done", combined


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    from scrapers import SCRAPERS
    import json

    with open("districts.json", encoding="utf-8") as f:
        districts = json.load(f)

    jobs = []
    for scraper in SCRAPERS.values():
        urls = scraper.build_search_urls(
            selected_neighbourhoods=[n for ns in districts.values() for n in ns],
            districts=districts,
            max_price=0,
        )
        jobs.append({"platform_id": scraper.platform_id, "urls": urls, "pages": 1})

    for status, data in run_pipeline(jobs):
        print(f"[{status}] {len(data)} rows")
