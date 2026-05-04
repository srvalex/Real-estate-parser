"""
db_utils.py
───────────
Supabase client — replaces firebase_utils.py.

Callers that previously imported from firebase_utils can switch with a
one-line change:
    from firebase_utils import save_to_firestore, query_listings_by_district
    →  from db_utils import save_to_firestore, query_listings_by_district

Credentials are read from environment variables (or a .env file):
    SUPABASE_URL  — https://xxxx.supabase.co
    SUPABASE_KEY  — service_role secret key (Settings → API in Supabase dashboard)
"""

import json
import math
import os
import re
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase import create_client, Client

SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")

_client: Client | None = None

# Columns that exist in the canonical Supabase schema.
# Fields NOT in this set are stripped before upserting to avoid PostgREST 400 errors.
_CANONICAL_COLUMNS = frozenset({
    "url", "platform_id", "platform", "source_id",
    "title", "description",
    "price_eur", "price_numeric", "price_currency",
    "district", "location_full",
    "rooms", "area_sqm", "floor", "total_floors", "year_built", "heating",
    "features", "image_urls", "extras",
    "is_available", "scraped_at", "first_seen_at", "last_seen_at",
    "embedding", "image_embedding",
})


def get_client() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set in .env or environment"
            )
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ─────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────

def _clean_record(item: dict) -> dict | None:
    """Normalise and map a listing dict to canonical Supabase columns.

    Handles both already-normalised data (from normalize_listings.py) and raw
    scraped dicts (from extractor.py / crawler.py) that use legacy field names.
    Unknown columns are stripped to avoid PostgREST 400 errors.
    """
    # 1. Strip None / NaN
    clean: dict = {}
    for k, v in item.items():
        if v is None:
            continue
        if isinstance(v, float) and math.isnan(v):
            continue
        clean[k] = v

    # 2. Canonical URL
    url = clean.get("url") or clean.get("link")
    if not url:
        return None
    clean["url"] = url

    # 3. image_urls: JSON string → native list for JSONB
    if "image_urls" in clean and isinstance(clean["image_urls"], str):
        try:
            clean["image_urls"] = json.loads(clean["image_urls"])
        except Exception:
            del clean["image_urls"]

    # 4. Fill canonical columns from raw scraped field names (runs only when
    #    the canonical field is absent — already-normalised data is untouched).

    # price_numeric / price_currency
    if "price_numeric" not in clean:
        raw = clean.get("price_eur") or clean.get("rent") or clean.get("price")
        if raw:
            s = str(raw)
            currency = "RON" if ("lei" in s.lower() or "ron" in s.lower()) else "EUR"
            digits = re.sub(r"\s", "", s)
            m = re.search(r"(\d+(?:[.,]\d+)?)", digits)
            if m:
                try:
                    clean["price_numeric"] = float(m.group(1).replace(",", "."))
                except ValueError:
                    pass
            clean.setdefault("price_currency", currency)

    # rooms: normalise '3 camere' / '3' → '1'…'5+'
    if "rooms" not in clean:
        raw = clean.get("rooms_num")
        if raw:
            m = re.search(r"(\d+)", str(raw))
            if m:
                n = int(m.group(1))
                clean["rooms"] = "5+" if n >= 5 else str(n)

    # area_sqm: accept plain float or parse from string '64 m²'
    if "area_sqm" not in clean or not isinstance(clean.get("area_sqm"), (int, float)):
        raw = clean.get("m") or clean.get("area_sqm")
        if raw and not isinstance(raw, (int, float)):
            m = re.search(r"(\d+(?:[.,]\d+)?)", str(raw))
            if m:
                try:
                    clean["area_sqm"] = float(m.group(1).replace(",", "."))
                except ValueError:
                    pass

    # location_full ← location_full_name
    if "location_full" not in clean and "location_full_name" in clean:
        clean["location_full"] = clean["location_full_name"]

    # floor ← floor_no
    if "floor" not in clean and "floor_no" in clean:
        clean["floor"] = clean["floor_no"]

    # year_built ← build_year
    if "year_built" not in clean and "build_year" in clean:
        clean["year_built"] = clean["build_year"]

    # 5. vector columns: pgvector needs '[x,y,z,...]' string, not a JSON array
    for vec_col in ("embedding", "image_embedding"):
        if vec_col in clean and isinstance(clean[vec_col], list):
            clean[vec_col] = "[" + ",".join(str(float(v)) for v in clean[vec_col]) + "]"

    # 6. Strip columns that don't exist in the canonical schema
    return {k: v for k, v in clean.items() if k in _CANONICAL_COLUMNS}


def _is_transient(exc: Exception) -> bool:
    """Return True for network/DNS errors that are worth retrying."""
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    msg = str(exc).lower()
    return any(s in msg for s in (
        "name or service not known", "connection", "timeout",
        "reset by peer", "eof", "network", "unreachable",
    ))


def _upsert_batch(client: Client, batch: list[dict], table: str, max_retries: int = 3) -> tuple[int, int]:
    """Upsert one batch with exponential-backoff retry on transient network errors."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            client.table(table).upsert(batch, on_conflict="url").execute()
            return len(batch), 0
        except Exception as e:
            last_exc = e
            if _is_transient(e) and attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s
                print(f"  [supabase] network error ({e}), retry {attempt + 1}/{max_retries - 1} in {wait}s…")
                time.sleep(wait)
            else:
                break

    print(f"  [supabase] batch upsert failed ({last_exc}), retrying row by row…")
    saved, failed = 0, 0
    for row in batch:
        for attempt in range(max_retries):
            try:
                client.table(table).upsert(row, on_conflict="url").execute()
                saved += 1
                break
            except Exception as row_err:
                if _is_transient(row_err) and attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    print(f"  [supabase] skip {row.get('url', '?')}: {row_err}")
                    failed += 1
                    break
    return saved, failed


# ─────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────

def save_to_db(data_list: list[dict], table: str = "listings") -> None:
    """Upsert a list of listing dicts into Supabase."""
    if not data_list:
        return

    client = get_client()
    cleaned = [r for r in (_clean_record(item) for item in data_list) if r]

    if not cleaned:
        return

    total_saved, total_failed = 0, 0
    chunk_size = 500
    for i in range(0, len(cleaned), chunk_size):
        saved, failed = _upsert_batch(client, cleaned[i : i + chunk_size], table)
        total_saved += saved
        total_failed += failed

    print(f"✅ Supabase: {total_saved} upserted" + (f", {total_failed} failed" if total_failed else ""))


# Alias so extractor.py works without changing its import name
save_to_firestore = save_to_db


def query_listings_by_district(district_names: list, table: str = "listings") -> list:
    """
    Fetch available listings whose district matches any of the given names.
    Drop-in replacement for the Firestore version — returns list of dicts.
    """
    if not district_names:
        return []

    client = get_client()
    results = []

    # Batch at 100 names per request to stay well inside URL length limits
    for i in range(0, len(district_names), 100):
        chunk = district_names[i : i + 100]
        try:
            resp = (
                client.table(table)
                .select("*")
                .in_("district", chunk)
                .eq("is_available", 1)
                .execute()
            )
            results.extend(resp.data or [])
        except Exception as e:
            print(f"  [supabase] query_listings_by_district failed (chunk {i}): {e}")

    return results


def get_all_db_urls(table: str = "listings") -> set[str]:
    """Return all URLs stored in Supabase. Replaces get_all_firestore_urls."""
    client = get_client()
    urls: set[str] = set()
    offset, page_size = 0, 1000

    while True:
        try:
            resp = (
                client.table(table)
                .select("url")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            rows = resp.data or []
            for row in rows:
                if row.get("url"):
                    urls.add(row["url"])
            if len(rows) < page_size:
                break
            offset += page_size
        except Exception as e:
            print(f"  [supabase] get_all_db_urls failed: {e}")
            break

    return urls


def get_listings_for_availability_check(platform_id: str | None = None) -> list[dict]:
    """Return [{url, platform_id}] for all listings not yet confirmed expired.

    Includes is_available=1 (re-confirm still live) and NULL (never checked).
    Skips is_available=0 (already confirmed expired — no point re-checking).
    """
    client = get_client()
    rows: list[dict] = []
    offset, page_size = 0, 1000

    while True:
        try:
            q = (
                client.table("listings")
                .select("url, platform_id")
                .or_("is_available.eq.1,is_available.is.null")
            )
            if platform_id:
                q = q.eq("platform_id", platform_id)
            resp = q.range(offset, offset + page_size - 1).execute()
            batch = resp.data or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        except Exception as e:
            print(f"  [supabase] get_listings_for_availability_check failed: {e}")
            break

    return rows


def batch_update_availability(updates: list[dict]) -> int:
    """Bulk-update is_available for a list of {url, is_available} dicts.

    Uses upsert on_conflict=url so only is_available is touched; all other
    columns remain unchanged.  Returns the number of rows processed.
    """
    if not updates:
        return 0
    client = get_client()
    total = 0
    CHUNK = 500
    for i in range(0, len(updates), CHUNK):
        chunk = updates[i : i + CHUNK]
        try:
            client.table("listings").upsert(chunk, on_conflict="url").execute()
            total += len(chunk)
        except Exception as e:
            print(f"  [supabase] batch_update_availability failed: {e}")
    return total


def search_by_text_vibe(
    query_embedding: list,
    limit: int = 200,
    min_available: int = 1,
) -> dict:
    """
    Call the match_listings pgvector RPC.
    Returns {url: similarity_score} where similarity is in [0, 1].
    """
    client = get_client()
    try:
        resp = client.rpc(
            "match_listings",
            {
                "query_embedding": query_embedding,
                "match_count":     limit,
                "min_available":   min_available,
            },
        ).execute()
        return {row["url"]: float(row["similarity"]) for row in (resp.data or [])}
    except Exception as e:
        print(f"  [supabase] search_by_text_vibe failed: {e}")
        return {}


def get_price_stats(table: str = "listings") -> dict:
    """
    Return average EUR price per (district, rooms) bucket for available listings.
    Buckets with fewer than 5 comparables are suppressed.
    Result: {("Floreasca", "2"): {"avg": 850.0, "count": 23}, ...}
    """
    MIN_COMPARABLES = 5
    client = get_client()
    rows: list[dict] = []
    offset, page_size = 0, 1000

    while True:
        try:
            resp = (
                client.table(table)
                .select("district, rooms, price_numeric")
                .eq("is_available", 1)
                .eq("price_currency", "EUR")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            chunk = resp.data or []
            rows.extend(chunk)
            if len(chunk) < page_size:
                break
            offset += page_size
        except Exception as e:
            print(f"  [supabase] get_price_stats failed: {e}")
            break

    from collections import defaultdict
    buckets: dict = defaultdict(list)
    for row in rows:
        if not row.get("district") or not row.get("rooms") or row.get("price_numeric") is None:
            continue
        try:
            buckets[(row["district"], row["rooms"])].append(float(row["price_numeric"]))
        except (TypeError, ValueError):
            pass

    return {
        key: {"avg": sum(prices) / len(prices), "count": len(prices)}
        for key, prices in buckets.items()
        if len(prices) >= MIN_COMPARABLES
    }


def get_listings_missing_text_embedding(limit: int = 64, table: str = "listings") -> list[dict]:
    """Return listings where embedding IS NULL and title or description is non-empty."""
    client = get_client()
    try:
        resp = (
            client.table(table)
            .select("url, title, description")
            .is_("embedding", "null")
            .limit(limit)
            .execute()
        )
        return [r for r in (resp.data or []) if r.get("title") or r.get("description")]
    except Exception as e:
        print(f"  [supabase] get_listings_missing_text_embedding failed: {e}")
        return []


def get_listings_missing_image_embedding(limit: int = 50, table: str = "listings") -> list[dict]:
    """Return available listings that have image_urls but no image_embedding yet."""
    client = get_client()
    try:
        resp = (
            client.table(table)
            .select("url, image_urls")
            .eq("is_available", 1)
            .not_.is_("image_urls", "null")
            .is_("image_embedding", "null")
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"  [supabase] get_listings_missing_image_embedding failed: {e}")
        return []


def update_image_embedding(url: str, embedding: list, table: str = "listings") -> bool:
    """Update the image_embedding column for a single listing URL."""
    client = get_client()
    vec_str = "[" + ",".join(str(float(v)) for v in embedding) + "]"
    try:
        client.table(table).update({"image_embedding": vec_str}).eq("url", url).execute()
        return True
    except Exception as e:
        print(f"  [supabase] update_image_embedding failed for {url}: {e}")
        return False


def search_by_image_embedding(query_embedding: list, limit: int = 200) -> dict:
    """
    Call the match_listings_by_image pgvector RPC.
    Returns {url: similarity_score} where similarity is in [0, 1].
    query_embedding must be a 512-dim CLIP vector.
    """
    client = get_client()
    vec_str = "[" + ",".join(str(float(v)) for v in query_embedding) + "]"
    try:
        resp = client.rpc(
            "match_listings_by_image",
            {"query_embedding": vec_str, "match_count": limit},
        ).execute()
        return {row["url"]: float(row["similarity"]) for row in (resp.data or [])}
    except Exception as e:
        print(f"  [supabase] search_by_image_embedding failed: {e}")
        return {}


def fetch_analytics_data() -> list[dict]:
    """Fetch all listings with the columns needed for the analytics dashboard.

    Returns a flat list of dicts — safe to pass directly to pd.DataFrame().
    Only analytics-relevant columns are selected to keep payload small.
    Pre-filtered to available listings with a known property_type.
    """
    client = get_client()
    rows: list[dict] = []
    offset, page_size = 0, 1000

    while True:
        try:
            resp = (
                client.table("listings")
                .select(
                    "platform_id, district, title, price_numeric, price_currency, "
                    "rooms, area_sqm, is_available, scraped_at, first_seen_at, property_type"
                )
                .eq("is_available", 1)
                .not_.is_("property_type", "null")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            batch = resp.data or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        except Exception as e:
            print(f"  [supabase] fetch_analytics_data failed: {e}")
            break

    return rows


if __name__ == "__main__":
    client = get_client()
    resp = client.table("listings").select("url", count="exact").limit(1).execute()
    print(f"✅ Connected to Supabase. Listings count: {resp.count}")
