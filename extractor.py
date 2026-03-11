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


def build_links_df(olx_url=None, storia_url=None, olx_pages=1, storia_pages=1) -> pd.DataFrame:
    print("📡 Collecting listing links...")
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

    def classify(link):
        domain = urlparse(link).netloc
        if "olx.ro" in domain:
            return "olx", link
        elif "storia.ro" in domain:
            return "storia", link.split(".html")[0]
        return "unknown", link

    df = pd.DataFrame({"link": offers})
    df[["platform", "link"]] = df["link"].apply(lambda x: pd.Series(classify(x)))
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
    """Call get_rendered_description.py as a subprocess (handles JS rendering)."""
    if not urls:
        return []
    script = os.path.join(os.path.dirname(__file__), "get_rendered_description.py")
    try:
        proc = subprocess.Popen(
            ["python", script] + urls,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        stdout, stderr = proc.communicate()
        if stdout.strip():
            return json.loads(stdout.strip())
        else:
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

def run_pipeline(
    olx_url:      str | None = None,
    storia_url:   str | None = None,
    olx_pages:    int = 1,
    storia_pages: int = 1,
    storia_batch: int = 5,
    out_csv:      str = "results.csv",
) -> pd.DataFrame:
    """
    Full end-to-end extraction.
    Returns a combined DataFrame and saves it to `out_csv`.
    """

    # ── 1. Collect links ──────────────────────
    links_df = build_links_df(olx_url, storia_url, olx_pages, storia_pages)

    olx_links    = links_df[links_df["platform"] == "olx"]["link"].tolist()
    storia_links = links_df[links_df["platform"] == "storia"]["link"].tolist()

    results_olx    = []
    results_storia = []

    # ── 2a. Scrape OLX (sequential, polite) ──
    def process_olx():
        print(f"\n🔶 Scraping {len(olx_links)} OLX listings...")
        for link in tqdm(olx_links, desc="OLX", ncols=70):
            data = scrape_olx(link)
            if data:
                results_olx.append(data)
            time.sleep(1.2)

    # ── 2b. Scrape Storia (batched via Playwright) ──
    def process_storia():
        print(f"\n🔷 Scraping {len(storia_links)} Storia listings (batch={storia_batch})...")
        for i in tqdm(range(0, len(storia_links), storia_batch), desc="Storia batches", ncols=70):
            chunk  = storia_links[i : i + storia_batch]
            batch  = scrape_storia_batch(chunk)
            parsed = [extract_storia(r) for r in batch]
            results_storia.extend(r for r in parsed if r)
            time.sleep(2)

    # Run both in parallel
    with ThreadPoolExecutor(max_workers=2) as ex:
        ex.submit(process_olx)
        ex.submit(process_storia)

    # ── 3. Combine & save ────────────────────
    df_olx    = pd.DataFrame(results_olx)    if results_olx    else pd.DataFrame()
    df_storia = pd.DataFrame(results_storia) if results_storia else pd.DataFrame()
    combined  = pd.concat([df_olx, df_storia], ignore_index=True)

    combined["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    out_path = os.path.join(os.path.dirname(__file__), out_csv)
    combined.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n✅ Done. {len(combined)} listings saved → {out_path}")

    return combined


# ─────────────────────────────────────────────
#  Entry point — configure your job here
# ─────────────────────────────────────────────

JOB = {
    "olx_url":    "https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/?currency=EUR",
    "storia_url": "https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti?ownerTypeSingleSelect=ALL",
    "olx_pages":    1,
    "storia_pages": 1,
    "storia_batch": 5,          # how many Storia tabs open at once
    "out_csv":    "results.csv", # saved next to this script
}

if __name__ == "__main__":
    df = run_pipeline(**JOB)
    print(df[["platform", "title", "rent", "district"]].head(10).to_string())
