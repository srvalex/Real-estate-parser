"""
extractor.py
────────────
Standalone extraction pipeline for real estate listings.

Usage (from project root):
    python extractor.py

Input is configured via the `JOB` dict at the bottom of this file.
Output is a CSV saved to the project root.
"""

from bs4 import BeautifulSoup
import pandas as pd
import json
import time
import subprocess
import sqlite3
from tqdm import tqdm
from curl_cffi import requests
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from firebase_utils import save_to_firestore, init_firebase

# ─────────────────────────────────────────────
#  Hardcoded request header
# ─────────────────────────────────────────────
HEADER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}

# ─────────────────────────────────────────────
#  Step 1 — Fetch & collect listing links
# ─────────────────────────────────────────────

def get_content(url: str) -> str | None:
    try:
        response = requests.get(url, headers=HEADER, impersonate="chrome120")
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"  [fetch error] {url}: {e}")
        return None


def get_olx_listings(url: str):
    html = get_content(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    return soup.find_all("div", attrs={"data-cy": "l-card"})


def get_storia_listings(url: str):
    html = get_content(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    return soup.find_all("div", attrs={"data-sentry-element": "ContentContainer"})


def get_all_offers(raw_listings: list) -> list[str]:
    offers = []
    for listing in raw_listings:
        anchor = listing.find("a", href=True)
        if anchor:
            href = anchor["href"]
            if href.startswith("https"):       # OLX → Storia redirect
                offers.append(href)
            elif href.startswith("/d/o"):      # OLX native
                offers.append("https://www.olx.ro" + href)
            else:                              # Storia
                offers.append("https://www.storia.ro" + href)
    return offers


def _flatten(lst):
    return [item for batch in lst for item in batch]


def collect_olx_links(url: str, num_pages: int) -> list:
    if num_pages == 1:
        return get_olx_listings(url)
    pages = []
    for n in range(1, num_pages + 1):
        paged_url = url if n == 1 else f"{url}?page={n}"
        pages.append(get_olx_listings(paged_url))
    return _flatten(pages)


def collect_storia_links(url: str, num_pages: int) -> list:
    if num_pages == 1:
        return get_storia_listings(url)
    pages = []
    for n in range(1, num_pages + 1):
        paged_url = url if n == 1 else f"{url}&page={n}"
        pages.append(get_storia_listings(paged_url))
    return _flatten(pages)


def _classify_link(link: str) -> tuple[str, str]:
    """Return (platform, normalised_link) for a raw listing URL."""
    domain = urlparse(link).netloc
    if "olx.ro" in domain:
        return "olx", link
    elif "storia.ro" in domain:
        return "storia", link.split(".html")[0]
    return "unknown", link


def build_links_df(olx_url=None, storia_url=None, olx_pages=1, storia_pages=1) -> pd.DataFrame:
    raw = []
    if olx_url:
        raw += collect_olx_links(olx_url, olx_pages)
        print(f"  OLX: found {len(raw)} raw cards")
    storia_raw = []
    if storia_url:
        storia_raw = collect_storia_links(storia_url, storia_pages)
        print(f"  Storia: found {len(storia_raw)} raw cards")
    raw += storia_raw

    offers = get_all_offers(raw)
    df = pd.DataFrame({"link": offers})
    df[["platform", "link"]] = df["link"].apply(lambda x: pd.Series(_classify_link(x)))
    df = df[df["platform"] != "unknown"].drop_duplicates("link").reset_index(drop=True)
    print(f"  Total unique links: {len(df)}")
    return df


# ─────────────────────────────────────────────
#  Step 2 — Scrape individual listings
# ─────────────────────────────────────────────

def scrape_olx(url: str) -> dict | None:
    try:
        html = get_content(url)
        soup = BeautifulSoup(html, "html.parser")

        title = soup.find("div", attrs={"data-cy": "offer_title"}).find("h4").get_text(strip=True)
        price = soup.find("div", attrs={"data-testid": "ad-price-container"}).find("h3").get_text(strip=True)

        desc_container = soup.find("div", attrs={"data-cy": "ad_description"})
        for tag in desc_container.find_all(["style", "h3"]):
            tag.decompose()
        description = desc_container.get_text(separator="\n", strip=True)

        listing_id = soup.find("div", attrs={"data-cy": "ad-footer-bar-section"}).find("span").contents[2]

        return {
            "id":          str(listing_id).strip(),
            "platform":    "OLX",
            "title":       title,
            "rent":        price,
            "description": description,
            "url":         url,
        }
    except Exception as e:
        print(f"  [olx parse error] {url}: {e}")
        return None

def scrape_storia_batch(urls: list[str]) -> list[dict]:
    if not urls:
        return []
    script = os.path.join(os.path.dirname(__file__), "get_rendered_description.py")
    try:
        # We NO LONGER add + urls to the list
        proc = subprocess.Popen(
            ["python", script], 
            stdin=subprocess.PIPE,  # Enable stdin
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        
        # Pass the URLs as a JSON string through communicate
        stdout, stderr = proc.communicate(input=json.dumps(urls))
        
        if stdout.strip():
            try:
                return json.loads(stdout.strip())
            except json.JSONDecodeError:
                print(f"  [storia json error] Invalid output: {stdout[:100]}")
                return []
        else:
            if stderr:
                print(f"  [storia batch error] {stderr[:200]}")
            return []
    except Exception as e:
        print(f"  [storia subprocess error] {e}")
        return []


def extract_storia(raw: dict) -> dict | None:
    """Flatten raw Storia JSON into a flat dict."""
    data = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
    if not data or not isinstance(data, dict):
        return None
    try:
        chars = {"id": data.get("id"), "platform": "Storia"}
        for el in data.get("characteristics", []):
            chars[el["key"]] = el.get("localizedValue")

        locs = data.get("location", {}).get("reverseGeocoding", {}).get("locations", [])
        chars["district"]           = locs[-1].get("name", "Unknown") if locs else "Unknown"
        chars["location_full_name"] = locs[-1].get("fullName", "Unknown") if locs else "Unknown"

        desc_raw = data.get("description", "")
        if desc_raw:
            soup = BeautifulSoup(desc_raw, "html.parser")
            chars["description"] = "\n".join(
                line.strip() for line in soup.get_text(separator="\n").splitlines() if line.strip()
            )
        else:
            chars["description"] = ""

        chars["title"]    = data.get("title", "")
        chars["url"]      = data.get("url", raw.get("url", ""))
        chars["features"] = str(data.get("features", []))
        return chars
    except Exception as e:
        print(f"  [storia extract error] {e}")
        return None


# ─────────────────────────────────────────────
#  Step 3 — Orchestration
# ─────────────────────────────────────────────
DB_NAME = os.path.join(os.path.dirname(__file__), "Streamlit Interface", "real_estate.db")

DB_COLS = (
    "link TEXT PRIMARY KEY, id TEXT, platform TEXT, title TEXT, rent TEXT, "
    "description TEXT, url TEXT, price TEXT, m TEXT, rooms_num TEXT, "
    "building_type TEXT, floor_no TEXT, building_floors_num TEXT, "
    "building_material TEXT, windows_type TEXT, heating TEXT, build_year TEXT, "
    "construction_status TEXT, free_from TEXT, district TEXT, "
    "location_full_name TEXT, features TEXT, deposit TEXT, "
    "remote_services TEXT, scraped_at TEXT"
)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute(f"CREATE TABLE IF NOT EXISTS listings ({DB_COLS})")
    return conn


def _evolve_schema(conn, df: pd.DataFrame):
    """Add any columns present in df but missing from the SQLite table.
    This lets the schema grow automatically when scrapers return new fields.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    new_cols = [col for col in df.columns if col not in existing]
    for col in new_cols:
        conn.execute(f'ALTER TABLE listings ADD COLUMN "{col}" TEXT')
        print(f"  [schema] Added new column: {col}")
    if new_cols:
        conn.commit()


def _save_new_listings(new_results: list, conn) -> pd.DataFrame:
    """Persist new listings to SQLite and Firestore. Returns a DataFrame of what was saved."""
    if not new_results:
        return pd.DataFrame()

    df_new = pd.DataFrame(new_results)
    df_new["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _evolve_schema(conn, df_new)

    try:
        df_new.to_sql("listings", conn, if_exists="append", index=False)
        print(f"💾 Added {len(df_new)} new records to local database.")
    except Exception as e:
        print(f"⚠️ Batch DB insert failed ({e}), retrying row by row…")
        saved, failed = 0, 0
        for _, row in df_new.iterrows():
            try:
                row.to_frame().T.to_sql("listings", conn, if_exists="append", index=False)
                saved += 1
            except Exception as row_err:
                print(f"  [skip] {row.get('url', '?')}: {row_err}")
                failed += 1
        print(f"💾 Row-by-row: {saved} saved, {failed} skipped.")

    try:
        firestore_ready = df_new.where(pd.notnull(df_new), None).to_dict(orient="records")
        save_to_firestore(firestore_ready)
    except Exception as e:
        print(f"⚠️ Failed to save to Firestore: {e}")

    return df_new


def run_pipeline(
    olx_url:      str | None = None,
    storia_url:   str | None = None,
    olx_pages:    int = 1,
    storia_pages: int = 1,
    storia_batch: int = 10,
    out_csv:      str = "results.csv",
) -> pd.DataFrame:
    """
    Full end-to-end extraction with SQLite caching.
    Yields intermediate state: (status_string, partial_dataframe)
    """
    # ── 0. Initialize DB ──────────────────────
    conn = init_db() # Assumes the init_db function provided earlier

    # ── 1. Collect all links from search pages ──
    links_df = build_links_df(olx_url, storia_url, olx_pages, storia_pages)
    all_found_links = links_df["link"].tolist()

    if not all_found_links:
        print("⚠️ No links found to process.")
        yield "done", pd.DataFrame()
        return

    # ── 2. Check Database for existing records ──
    # We query the DB to see which of these links we already have
    placeholders = ', '.join(['?'] * len(all_found_links))
    query = f"SELECT * FROM listings WHERE url IN ({placeholders})"
    
    # Existing data from DB
    df_cached = pd.read_sql_query(query, conn, params=all_found_links)
    cached_urls = set(df_cached["url"].tolist())

    # Filter links that actually need scraping
    olx_to_scrape = [l for l in all_found_links if l not in cached_urls and "olx.ro" in l]
    storia_to_scrape = [l for l in all_found_links if l not in cached_urls and "storia.ro" in l]

    print(f"📊 Cache: {len(df_cached)} found | 🚀 To Scrape: {len(olx_to_scrape)} OLX, {len(storia_to_scrape)} Storia")

    # Yield the cached data immediately so the UI can display it
    yield "db_cache", df_cached

    results_olx = []
    results_storia = []

    # ── 3a. Scrape OLX (New only) ──
    if olx_to_scrape:
        print(f"\n🔶 Scraping {len(olx_to_scrape)} NEW OLX listings...")
        for link in tqdm(olx_to_scrape, desc="OLX", ncols=70):
            data = scrape_olx(link)
            if data:
                # Ensure it fits your DB columns (rent vs price)
                data['price'] = data.get('rent') 
                results_olx.append(data)
                yield "progress", pd.DataFrame([data])
            time.sleep(1.2)

    # ── 3b. Scrape Storia (New only) ──
    if storia_to_scrape:
        print(f"\n🔷 Scraping {len(storia_to_scrape)} NEW Storia listings (batch={storia_batch})...")
        for i in tqdm(range(0, len(storia_to_scrape), storia_batch), desc="Storia batches", ncols=70):
            chunk  = storia_to_scrape[i : i + storia_batch]
            batch  = scrape_storia_batch(chunk)
            parsed = [extract_storia(r) for r in batch]
            new_this_batch = []
            for p in parsed:
                if p:
                    # Sync price/rent columns
                    p['rent'] = p.get('price') 
                    results_storia.append(p)
                    new_this_batch.append(p)
            if new_this_batch:
                yield "progress", pd.DataFrame(new_this_batch)
            time.sleep(2)

    # ── 4. Save New Data to DB & Firestore ───
    df_new = _save_new_listings(results_olx + results_storia, conn)

    # ── 5. Combine & Finalize ─────────────────
    combined = pd.concat([df_cached, df_new], ignore_index=True)
    conn.close()

    out_path = os.path.join(os.path.dirname(__file__), out_csv)
    combined.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n✅ Done. Total pipeline output: {len(combined)} listings.")

    yield "done", combined


# ─────────────────────────────────────────────
#  Entry point — configure your job here
# ─────────────────────────────────────────────

JOB = {
    "olx_url":    "https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/?currency=EUR",
    "storia_url": "https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti?ownerTypeSingleSelect=ALL",
    "olx_pages":    1,
    "storia_pages": 1,
    "storia_batch": 10,          # how many Storia tabs open at once
    "out_csv":    "results.csv", # saved next to this script
}

if __name__ == "__main__":
    for status, data in run_pipeline(**JOB):
        print(f"Status: {status}, Extracted {len(data)} items.")



