"""
scripts/normalize_listings.py
──────────────────────────────
Reads all rows from SQLite, maps the three platform schemas to a single
canonical structure, and saves the result to normalized_listings.csv for
inspection. Once you are happy with the output, run with --upload to push
directly to Supabase.

Run from the project root:
    python scripts/normalize_listings.py             # inspect only
    python scripts/normalize_listings.py --upload    # inspect + upload
"""

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "Streamlit Interface", "real_estate.db"
)
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "..", "normalized_listings.csv")
BATCH_SIZE = 500

# Storia-specific columns that go into extras JSONB rather than top-level columns
STORIA_EXTRAS = [
    "building_type", "building_material", "windows_type",
    "construction_status", "free_from", "deposit",
    "remote_services", "offered_estates_type", "state",
    "number_of_properties", "area_from", "area_to",
    "building_floors_num", "floors_num",
]


# ─────────────────────────────────────────────
#  Normalisation helpers
# ─────────────────────────────────────────────

def detect_platform(url: str) -> str:
    if not url:
        return "unknown"
    if "olx.ro" in url:
        return "olx"
    if "storia.ro" in url:
        return "storia"
    if "imobiliare.ro" in url:
        return "imobiliare"
    return "unknown"


def normalize_rooms(row: dict) -> str | None:
    raw = row.get("rooms_num") or row.get("rooms")
    if not raw:
        return None
    m = re.search(r"(\d+)", str(raw))
    if not m:
        return None
    n = int(m.group(1))
    return "5+" if n >= 5 else str(n)


def normalize_area(row: dict) -> float | None:
    # Storia: "64 m²" (² often corrupted) — extract leading number
    # Imobiliare: "68" — plain string
    raw = row.get("m") or row.get("area_sqm")
    if not raw:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(raw))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def normalize_price(row: dict) -> tuple[float | None, str | None]:
    """Returns (price_numeric, price_currency)."""
    raw = row.get("price_eur") or row.get("rent") or row.get("price")
    if not raw:
        return None, None
    raw = str(raw)

    # Detect currency before stripping text
    if "lei" in raw.lower() or "ron" in raw.lower():
        currency = "RON"
    else:
        currency = "EUR"  # €, EUR, or corrupted encoding — default EUR

    # Extract the first number (handles "1 200", "1,200", "1200")
    digits = re.sub(r"\s", "", raw)          # remove whitespace used as thousands sep
    m = re.search(r"(\d+(?:[.,]\d+)?)", digits)
    if not m:
        return None, currency
    try:
        return float(m.group(1).replace(",", ".")), currency
    except ValueError:
        return None, currency


def build_extras(row: dict, platform_id: str) -> dict | None:
    if platform_id != "storia":
        return None
    extras = {k: row[k] for k in STORIA_EXTRAS if row.get(k)}
    return extras if extras else None


def normalize_row(raw: dict) -> dict:
    url = raw.get("url") or raw.get("link") or ""
    platform_id = raw.get("platform_id") or detect_platform(url)

    price_numeric, price_currency = normalize_price(raw)

    # image_urls: stored as JSON string in SQLite, need to parse
    image_urls = raw.get("image_urls")
    if isinstance(image_urls, str) and image_urls:
        try:
            image_urls = json.loads(image_urls)
        except Exception:
            image_urls = None

    return {
        "url":            url,
        "platform_id":    platform_id,
        "platform":       raw.get("platform"),
        "source_id":      raw.get("source_id") or raw.get("id"),
        "title":          raw.get("title"),
        "description":    raw.get("description"),
        "price_eur":      raw.get("price_eur") or raw.get("rent") or raw.get("price"),
        "price_numeric":  price_numeric,
        "price_currency": price_currency,
        "district":       raw.get("district"),
        "location_full":  raw.get("location_full_name"),
        "rooms":          normalize_rooms(raw),
        "area_sqm":       normalize_area(raw),
        "floor":          raw.get("floor_no"),
        "total_floors":   raw.get("building_floors_num") or raw.get("floors_num"),
        "year_built":     raw.get("build_year"),
        "heating":        raw.get("heating"),
        "features":       raw.get("features"),
        "image_urls":     image_urls,
        "extras":         build_extras(raw, platform_id),
        "is_available":   raw.get("is_available", 1),
        "scraped_at":     raw.get("scraped_at"),
    }


# ─────────────────────────────────────────────
#  Reporting
# ─────────────────────────────────────────────

def print_report(df: pd.DataFrame) -> None:
    total = len(df)
    print(f"\n{'='*55}")
    print(f"  NORMALISATION REPORT  ({total:,} rows)")
    print(f"{'='*55}")

    print("\nPlatform breakdown:")
    for pid, count in df["platform_id"].value_counts().items():
        print(f"  {pid:<15} {count:>5,}")

    print("\nField coverage (% of rows with a value):")
    key_cols = ["rooms", "area_sqm", "price_numeric", "district",
                "image_urls", "description", "floor", "heating"]
    for col in key_cols:
        if col not in df.columns:
            continue
        filled = df[col].notna().sum()
        pct = filled / total * 100
        bar = "█" * int(pct / 5)
        print(f"  {col:<15} {pct:5.1f}%  {bar}")

    print("\nPrice currency breakdown:")
    for cur, count in df["price_currency"].value_counts().items():
        print(f"  {cur:<6} {count:,}")

    print("\nRooms distribution:")
    for rooms, count in df["rooms"].value_counts().sort_index().items():
        print(f"  {rooms:<5} {count:,}")

    print(f"\nRows with no platform detected: {(df['platform_id'] == 'unknown').sum()}")
    print(f"Rows with no URL:               {df['url'].isna().sum()}")
    print(f"{'='*55}\n")


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Normalise SQLite listings → canonical schema")
    parser.add_argument("--upload", action="store_true", help="Upload to Supabase after normalising")
    args = parser.parse_args()

    # ── Read SQLite ───────────────────────────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    raw_rows = [dict(r) for r in conn.execute("SELECT * FROM listings")]
    conn.close()
    print(f"Read {len(raw_rows):,} rows from SQLite")

    # ── Normalise ─────────────────────────────────────────────────────────────
    normalised = [normalize_row(r) for r in raw_rows]
    df = pd.DataFrame(normalised)

    # Drop rows with no URL (shouldn't exist, but be safe)
    before = len(df)
    df = df[df["url"].notna() & (df["url"] != "")]
    if len(df) < before:
        print(f"  Dropped {before - len(df)} rows with no URL")

    # ── Report ────────────────────────────────────────────────────────────────
    print_report(df)

    # ── Save CSV ──────────────────────────────────────────────────────────────
    # Serialise JSONB columns to strings for CSV
    csv_df = df.copy()
    for col in ("image_urls", "extras"):
        if col in csv_df.columns:
            csv_df[col] = csv_df[col].apply(
                lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
            )
    csv_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"Saved to {OUTPUT_CSV}")

    # ── Upload ────────────────────────────────────────────────────────────────
    if args.upload:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        from db_utils import get_client

        print(f"\nUploading {len(df):,} rows to Supabase in batches of {BATCH_SIZE}…")
        client = get_client()
        records = df.to_dict(orient="records")

        # Replace NaN/None uniformly — Supabase needs None not float('nan')
        def clean(rec: dict) -> dict:
            return {
                k: (None if (v is None or (isinstance(v, float) and math.isnan(v))) else v)
                for k, v in rec.items()
            }

        uploaded, failed = 0, 0
        for i in range(0, len(records), BATCH_SIZE):
            batch = [clean(r) for r in records[i : i + BATCH_SIZE]]
            try:
                client.table("listings").upsert(batch, on_conflict="url").execute()
                uploaded += len(batch)
                print(f"  {uploaded:,} / {len(records):,} uploaded…")
            except Exception as e:
                print(f"  batch {i} failed ({e}), retrying row by row…")
                for r in batch:
                    try:
                        client.table("listings").upsert(r, on_conflict="url").execute()
                        uploaded += 1
                    except Exception as re:
                        print(f"  skip {r.get('url','?')}: {re}")
                        failed += 1

        resp = client.table("listings").select("url", count="exact").limit(1).execute()
        print(f"\n✅ Upload done.  Uploaded: {uploaded:,}  Failed: {failed:,}")
        print(f"   Supabase total rows: {resp.count:,}")


if __name__ == "__main__":
    main()
