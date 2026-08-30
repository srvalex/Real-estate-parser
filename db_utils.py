"""
db_utils.py
───────────
Supabase client — replaces firebase_utils.py.

Callers that previously imported from firebase_utils can switch with a
one-line change:
    from firebase_utils import save_to_firestore, query_listings_by_district
    →  from db_utils import save_to_firestore, query_listings_by_district

Credentials are read from environment variables (or a .env file):
    SUPABASE_URL       — https://xxxx.supabase.co
    SUPABASE_KEY       — service_role secret key (Settings → API in Supabase
                         dashboard). Full read/write, bypasses Row Level
                         Security entirely. BACKEND USE ONLY — the crawler,
                         the embedder job, and admin scripts. Never expose
                         this to the Streamlit deployment.
    SUPABASE_ANON_KEY  — anon/public key (same dashboard page). Used for
                         every read the Streamlit app performs, via
                         get_anon_client(). Constrained by the Row Level
                         Security policy in scripts/supabase_schema.sql
                         (read-only, is_available = 1 rows only) — safe to
                         ship in a public-facing deployment even if it leaks,
                         which anon keys are designed to tolerate.

Two separate clients exist on purpose (get_client() vs get_anon_client()).
Before this split, every function — including the ones only the public
Streamlit app calls — used the service-role client, so a leaked Streamlit
env var would have handed out full read/write/delete on the whole table.
Run the RLS section of scripts/supabase_schema.sql once before relying on
this split; get_anon_client() falls back to the service-role key with a
loud warning if SUPABASE_ANON_KEY isn't set, so nothing breaks before then
— but that fallback defeats the point and must not be relied on in any
deployed environment.
"""

import json
import math
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
    # Also try a file named "env" (without the dot) as a fallback
    if not os.environ.get("SUPABASE_URL"):
        _env_path = os.path.join(os.path.dirname(__file__), "env")
        if os.path.exists(_env_path):
            load_dotenv(_env_path)
except ImportError:
    pass

from supabase import create_client, Client

# Supabase renamed its API keys (legacy JWT "anon"/"service_role" -> newer
# "publishable"/"secret" API keys) and the dashboard now hands out the new
# names by default. Accept both so a .env copy-pasted from either era of
# the dashboard works without translation:
#   SUPABASE_URL      <- or SUPABASE_DATA_API      (project REST API URL)
#   SUPABASE_KEY      <- or SUPABASE_SECRET_API_KEY (service-role / "secret")
#   SUPABASE_ANON_KEY <- or SUPABASE_PUBLISH_KEY    (anon / "publishable")
#
# SUPABASE_DATA_API is the dashboard's "Data API URL", which already
# includes the /rest/v1 suffix (e.g. "https://xxxx.supabase.co/rest/v1/").
# create_client() appends /rest/v1 itself, so that suffix must be stripped
# here or every request doubles the path and PostgREST rejects it
# (PGRST125 "Invalid path specified in request URL").
def _strip_rest_suffix(url: str) -> str:
    return url.split("/rest/v1")[0].rstrip("/") if url else url

SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "") or _strip_rest_suffix(os.environ.get("SUPABASE_DATA_API", ""))
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "") or os.environ.get("SUPABASE_SECRET_API_KEY", "")
SUPABASE_ANON_KEY: str = os.environ.get("SUPABASE_ANON_KEY", "") or os.environ.get("SUPABASE_PUBLISH_KEY", "")

_client: Client | None = None
_anon_client: Client | None = None

# Columns that exist in the canonical Supabase schema.
# Fields NOT in this set are folded into `extras` before upserting (see
# _clean_record step 7) rather than sent as top-level PostgREST columns,
# which would 400.
_CANONICAL_COLUMNS = frozenset({
    "url", "platform_id", "platform", "source_id",
    "title", "description",
    "price_eur", "price_numeric", "price_currency",
    "city", "district", "location_full",
    "rooms", "area_sqm", "floor", "total_floors", "year_built", "heating",
    "features", "image_urls", "extras",
    "property_type",
    "is_available", "scraped_at", "first_seen_at", "last_seen_at",
    "embedding", "image_embedding",
})

# Raw scraper field names read and mapped by _clean_record's step 4, and
# intentionally superseded by their canonical equivalent (e.g. rooms_num ->
# rooms). Discarding these afterward is expected on every listing, not a
# landmine — excluded here so the fold-into-extras logging below only fires
# for genuinely unmapped fields.
_KNOWN_RAW_ALIASES = frozenset({
    "link", "rent", "price", "rooms_num", "m",
    "location_full_name", "floor_no", "build_year",
})

# Columns read by the Streamlit results pipeline
# (streamlit_interface/components/results.py, pipeline/utils.py) plus
# api/main.py's freshness badge and match-receipt feature checklist
# (MIGRATION_PLAN.md Phase 1/3). Everything else in _CANONICAL_COLUMNS is
# deliberately left out:
#   - "extras", "embedding" (384-dim), "image_embedding" (512-dim): the
#     heaviest columns in the table. Semantic-search similarity is computed
#     server-side inside the match_listings/match_listings_by_image RPCs
#     (pgvector's <=> operator) and joined back in by url afterward — this
#     query never needs to see a raw vector. Pulling them for every row in a
#     large district's result set is what caused the statement timeout on
#     district queries like "Militari" (see BUGS.md #1). "features",
#     "scraped_at" and "first_seen_at" are cheap scalar/small-JSONB columns
#     by comparison, not part of what caused that timeout — safe to include.
#   - "is_available": already enforced by the .eq() filter below: PostgREST
#     filters on it independent of whether it's in the select list, and this
#     result set is never displayed with an availability badge.
#   - "platform_id", "source_id", "floor", "total_floors", "year_built",
#     "heating": only used by the Analytics tab, which already has its own
#     separately-scoped query (fetch_analytics_data()) — dropping them here
#     costs that tab nothing. Add a column back here if a future UI (e.g. a
#     "more details" expander) actually starts reading it.
_DISTRICT_QUERY_COLUMNS = (
    "url, title, description, "
    "price_eur, price_numeric, price_currency, "
    "district, location_full, "
    "rooms, area_sqm, property_type, platform, image_urls, "
    "features, scraped_at, first_seen_at"
)


def get_client() -> Client:
    """Service-role client: full read/write, bypasses Row Level Security.

    Backend use only (crawler, embedder job, admin scripts). Never call
    this from Streamlit-facing code — use get_anon_client() there.
    """
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set in .env or environment"
            )
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def get_anon_client() -> Client:
    """Anon-role client: read-only, constrained by the Row Level Security
    policy in scripts/supabase_schema.sql (is_available = 1 rows only, no
    write access). Every function the Streamlit app calls uses this.

    Raises if SUPABASE_ANON_KEY isn't configured — it used to silently fall
    back to the service-role key instead (with a one-time warning), so a
    Streamlit-facing deployment missing that one env var would quietly hand
    out full read/write/delete instead of failing loudly. Now that RLS is
    confirmed working (BUGS.md #8), there's no reason to keep tolerating a
    missing anon key: fail immediately instead of degrading into exactly the
    vulnerability this split exists to prevent.
    """
    global _anon_client
    if _anon_client is None:
        if not SUPABASE_URL:
            raise RuntimeError("SUPABASE_URL must be set in .env or environment")
        if not SUPABASE_ANON_KEY:
            raise RuntimeError(
                "SUPABASE_ANON_KEY (or SUPABASE_PUBLISH_KEY) must be set — "
                "get_anon_client() no longer falls back to the service-role "
                "key. Set it from the Supabase dashboard -> Settings -> API "
                "-> anon/public key."
            )
        _anon_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _anon_client


# ─────────────────────────────────────────────
#  Currency conversion (RON<->EUR)
#
#  Lives here, not in streamlit_interface/pipeline/utils.py, even though
#  that's the only place that used to need it: this module is the
#  Streamlit-independent foundational layer, reused by crawler.py and (per
#  MIGRATION_PLAN.md) the future API. Defining live-rate fetching in the
#  Streamlit-coupled pipeline module and having this module reach into it
#  for a SQL price filter would tie the crawler and the future API to a
#  Streamlit dependency they must never need. pipeline/utils.py now imports
#  get_ron_to_eur_rate/price_in_eur from here instead.
# ─────────────────────────────────────────────

BNR_RATES_URL = "https://curs.bnr.ro/nbrfxrates.xml"
_BNR_XML_NAMESPACE = {"bnr": "https://www.bnr.ro/xsd"}

# BNR publishes exactly one reference rate per calendar day, at 13:00
# Bucharest time -- so there's nothing to gain from a rolling TTL. Fetch at
# most once per Bucharest calendar day and reuse it for the rest of that day.
_BUCHAREST_TZ = ZoneInfo("Europe/Bucharest")
# If today's fetch fails, don't retry on every single subsequent call (that
# would mean every price comparison pays a network timeout during a BNR
# outage) -- wait at least this long before trying again, serving the last
# known rate (or the fallback, if we've never had one) in the meantime.
_RATE_RETRY_BACKOFF_SECONDS = 5 * 60
# Last resort only: BNR unreachable AND no rate has ever been fetched
# successfully in this process. Approximate, not live -- better than
# refusing to compare prices at all.
_FALLBACK_RON_TO_EUR_RATE = 5.1

_rate_cache: dict = {"rate": None, "fetched_date": None, "last_attempt": 0.0}


def _fetch_bnr_eur_rate(timeout: float = 5.0) -> float:
    """Fetch today's official RON-per-EUR reference rate from BNR's public
    feed. Raises on any failure (network, unexpected XML shape, missing
    EUR entry) -- get_ron_to_eur_rate() is responsible for falling back;
    this function is intentionally strict so that fallback logic is
    centralised in one place rather than swallowed here.
    """
    import requests
    import xml.etree.ElementTree as ET

    resp = requests.get(BNR_RATES_URL, timeout=timeout)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    rate_el = root.find(".//bnr:Rate[@currency='EUR']", _BNR_XML_NAMESPACE)
    if rate_el is None or not rate_el.text:
        raise ValueError("EUR rate not found in BNR feed")
    multiplier = float(rate_el.get("multiplier", "1"))
    return float(rate_el.text) / multiplier


def get_ron_to_eur_rate() -> float:
    """Return today's RON-per-EUR rate, fetched at most once per Bucharest
    calendar day (BNR publishes once daily at 13:00 Bucharest time — no
    reason to check more often than that).

    Never raises: any fetch failure logs a warning and falls back to the
    last successfully-fetched rate (even if it's from a prior day — a
    day-old real BNR rate is still far more accurate than a hardcoded
    constant from whenever this code was written), or to
    _FALLBACK_RON_TO_EUR_RATE if no rate has ever been fetched at all.
    """
    today = datetime.now(_BUCHAREST_TZ).date()
    if _rate_cache["rate"] is not None and _rate_cache["fetched_date"] == today:
        return _rate_cache["rate"]

    now = time.time()
    if (now - _rate_cache["last_attempt"]) < _RATE_RETRY_BACKOFF_SECONDS:
        # Recently attempted today's fetch and it evidently failed (a
        # success would have already satisfied the check above) -- don't
        # hit the network again immediately, even if we've never had a
        # real rate at all (that case must back off too, or a sustained
        # outage means every single call pays a fresh network timeout).
        return _rate_cache["rate"] if _rate_cache["rate"] is not None else _FALLBACK_RON_TO_EUR_RATE

    _rate_cache["last_attempt"] = now
    try:
        rate = _fetch_bnr_eur_rate()
        _rate_cache["rate"] = rate
        _rate_cache["fetched_date"] = today
        return rate
    except Exception as e:
        print(f"  [bnr] failed to fetch live RON/EUR rate: {e}")
        return _rate_cache["rate"] if _rate_cache["rate"] is not None else _FALLBACK_RON_TO_EUR_RATE


def price_in_eur(price_numeric, price_currency) -> float | None:
    """Convert a price to EUR for cross-currency comparison.

    Returns None if price_numeric is missing/unparseable. Treats a missing
    currency as EUR (matches _clean_record's own default).
    """
    if price_numeric is None or (isinstance(price_numeric, float) and math.isnan(price_numeric)):
        return None
    try:
        value = float(price_numeric)
    except (TypeError, ValueError):
        return None
    if str(price_currency or "").strip().upper() == "RON":
        return value / get_ron_to_eur_rate()
    return value


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

    # 6. property_type: infer from title when not explicitly set by the scraper
    if not clean.get("property_type"):
        title_norm = (
            str(clean.get("title", "")).lower()
            .replace("ă", "a").replace("î", "i").replace("â", "a")
            .replace("ș", "s").replace("ț", "t")
        )
        if any(kw in title_norm for kw in ("garsonier",)):
            clean["property_type"] = "Garsoniera"
        elif "studio" in title_norm:
            clean["property_type"] = "Studio"
        elif any(kw in title_norm for kw in ("casa", "vila", "duplex")):
            clean["property_type"] = "Casa/Vila"
        elif clean.get("title"):
            clean["property_type"] = "Apartament"

    # 7. Fold columns that don't exist in the canonical schema into `extras`
    #    instead of discarding them. Originally these were just dropped —
    #    that already caused one real production bug silently (Milestone 19:
    #    property_type wasn't in _CANONICAL_COLUMNS yet, so every scraper's
    #    attempt to set it vanished with no visible error for an unknown
    #    period — only noticed when analytics looked empty). The drop-logging
    #    added afterward caught a live, ongoing case of exactly this pattern:
    #    Storia's `characteristics` array gets flattened onto the raw item as
    #    top-level fields (building_floors_num, building_material, deposit,
    #    etc.), none of which are in _CANONICAL_COLUMNS, so they were being
    #    silently discarded on every single Storia listing (see BUGS.md #3c).
    #    Folding into `extras` (already a JSONB catch-all for platform-
    #    specific fields) keeps that data queryable for future use instead of
    #    losing it, without needing a schema migration for every new field a
    #    platform happens to expose.
    non_canonical = set(clean.keys()) - _CANONICAL_COLUMNS - _KNOWN_RAW_ALIASES
    if non_canonical:
        extras = clean.get("extras")
        extras = dict(extras) if isinstance(extras, dict) else {}
        for field in non_canonical:
            extras.setdefault(field, clean[field])
        clean["extras"] = extras
        print(
            f"  [supabase] _clean_record: folded non-canonical field(s) "
            f"{sorted(non_canonical)} into extras for {clean.get('url', '?')}"
        )
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


def query_listings_by_district(
    district_names: list,
    table: str = "listings",
    max_price_eur: float | None = None,
) -> list:
    """
    Fetch available listings whose district matches any of the given names.
    Drop-in replacement for the Firestore version — returns list of dicts.

    max_price_eur, if given, filters server-side across both currencies:
    EUR listings compared directly, RON listings compared against
    max_price_eur * today's RON/EUR rate. That multiplication happens once
    here (not per row) — algebraically identical to converting each row's
    RON price to EUR and comparing (price_ron / rate <= max_price_eur is
    the same inequality as price_ron <= max_price_eur * rate, since rate is
    always positive), but it means both branches of the filter are a plain
    column-vs-literal comparison that can use an ordinary index, rather
    than a per-row computed expression on price_numeric.

    Listings with no price_numeric at all are always kept regardless of
    max_price_eur — matches apply_filters' existing behaviour of never
    penalising missing data.
    """
    if not district_names:
        return []

    client = get_anon_client()
    results = []

    price_or_filter = None
    if max_price_eur is not None and max_price_eur > 0:
        rate = get_ron_to_eur_rate()
        max_price_ron = max_price_eur * rate
        price_or_filter = (
            "price_numeric.is.null,"
            f"and(price_currency.eq.EUR,price_numeric.lte.{max_price_eur}),"
            f"and(price_currency.eq.RON,price_numeric.lte.{max_price_ron})"
        )

    # Batch at 100 names per request to stay well inside URL length limits
    for i in range(0, len(district_names), 100):
        chunk = district_names[i : i + 100]
        try:
            query = (
                client.table(table)
                .select(_DISTRICT_QUERY_COLUMNS)
                .in_("district", chunk)
                .eq("is_available", 1)
            )
            if price_or_filter:
                query = query.or_(price_or_filter)
            resp = query.execute()
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


def get_listings_for_availability_check(
    platform_id: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Return [{url, platform_id, city}] for listings not yet confirmed expired.

    Includes is_available=1 (re-confirm still live), NULL (never checked),
    and -1 (blocked/transient on a prior attempt — must be retried, not left
    in limbo forever). Skips is_available=0 (already confirmed expired — no
    point re-checking).
    If limit is set, returns at most that many rows.

    `city` is selected alongside url/platform_id so a recheck can tell OLX's
    scrape_listing_with_status which city a row belongs to (it gates
    Bucharest-only title-based district matching) — without it, rechecking a
    Cluj/Iași row would silently default to "Bucuresti" and risk a
    false-positive district match.
    """
    client = get_client()
    rows: list[dict] = []
    offset, page_size = 0, 1000

    while True:
        try:
            q = (
                client.table("listings")
                .select("url, platform_id, city")
                .or_("is_available.eq.1,is_available.eq.-1,is_available.is.null")
            )
            if platform_id:
                q = q.eq("platform_id", platform_id)
            resp = q.range(offset, offset + page_size - 1).execute()
            batch = resp.data or []
            if limit is not None:
                remaining = limit - len(rows)
                if remaining <= 0:
                    break
                batch = batch[:remaining]
            rows.extend(batch)
            if len(batch) < page_size or (limit is not None and len(rows) >= limit):
                break
            offset += page_size
        except Exception as e:
            print(f"  [supabase] get_listings_for_availability_check failed: {e}")
            break

    return rows


def batch_update_availability(updates: list[dict]) -> int:
    """Bulk-update is_available for a list of {url, is_available} dicts.

    Uses UPDATE ... WHERE url IN (...) grouped by status value so only
    is_available is touched and no NOT-NULL columns are at risk.
    Also stamps last_seen_at when confirming a listing is still live.
    Returns the number of rows processed.
    """
    if not updates:
        return 0
    from collections import defaultdict
    from datetime import datetime
    client = get_client()
    total = 0
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    CHUNK = 500
    for i in range(0, len(updates), CHUNK):
        chunk = updates[i : i + CHUNK]
        # One UPDATE per distinct is_available value (typically just 0 and 1).
        by_status: dict[int, list[str]] = defaultdict(list)
        for row in chunk:
            by_status[row["is_available"]].append(row["url"])
        try:
            for status, urls in by_status.items():
                fields = {"is_available": status}
                if status == 1:
                    fields["last_seen_at"] = now
                client.table("listings").update(fields).in_("url", urls).execute()
            total += len(chunk)
        except Exception as e:
            print(f"  [supabase] batch_update_availability failed: {e}")
    return total


# Max candidate_urls sent in a single RPC call. Chunking at this size (rather
# than capping the total candidate set and falling back to an unscoped global
# search past some threshold — the old behaviour) keeps every request a
# reasonable payload while still scoring every candidate the caller actually
# cares about, no matter how many districts/filters they combine (see
# BUGS.md #7: a niche-filtered search must never silently lose good matches
# to a global top-K cutoff just because its candidate set is large).
#
# 1000 (not a rounder or larger number) is load-bearing, not arbitrary:
# live-tested against production 2026-08-23 — 2000-URL batches reproducibly
# hit Postgres's statement_timeout (57014) on the match_listings RPC, while
# 1000-URL batches did not, in repeated trials.
#
# Even at 1000, an individual call can still occasionally time out — this
# isn't a hard size cliff, it looks like a cold query-plan cost: the FIRST
# call with a given candidate_urls array shape is markedly slower (observed
# up to ~3.5s) than an immediate repeat with a different array of the same
# size (observed 0.3-1.3s), consistent with Postgres/PostgREST not having a
# cached plan yet for this exact RPC+array-length combination. See
# _rpc_with_retry below and BUGS.md #7's follow-up note for the DB-side
# investigation this points at (this is a mitigation, not a root fix).
_RPC_CANDIDATE_CHUNK_SIZE = 1000


def _chunk(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _rpc_with_retry(client, fn_name: str, params: dict):
    """Call an RPC, retrying once on failure.

    Covers the cold-plan latency spike described above: a chunk that times
    out is very likely to succeed on an immediate retry once Postgres has a
    plan cached for this call shape, rather than being genuinely unservable.
    """
    try:
        return client.rpc(fn_name, params).execute()
    except Exception:
        return client.rpc(fn_name, params).execute()


def search_by_text_vibe(
    query_embedding: list,
    limit: int = 200,
    min_available: int = 1,
    candidate_urls: list[str] | None = None,
) -> dict:
    """
    Call the match_listings pgvector RPC.

    When candidate_urls is given, every one of those URLs gets scored,
    regardless of table size or how many candidates there are — the search
    is scoped to exactly that set instead of relying on being within some
    global top-`limit` cutoff, which silently drops good matches from a
    filtered result set once the table grows large enough. Large candidate
    sets are split into batches of _RPC_CANDIDATE_CHUNK_SIZE URLs so no
    single request sends an unbounded payload; results from every batch are
    merged. `limit` only applies when candidate_urls is omitted entirely
    (unscoped, global top-K search).

    Returns {url: similarity_score} where similarity is in [0, 1].
    """
    client = get_anon_client()

    if candidate_urls:
        scores: dict = {}
        for batch in _chunk(candidate_urls, _RPC_CANDIDATE_CHUNK_SIZE):
            try:
                params = {
                    "query_embedding": query_embedding,
                    "match_count":     limit,
                    "min_available":   min_available,
                    "candidate_urls":  batch,
                }
                resp = _rpc_with_retry(client, "match_listings", params)
                scores.update({row["url"]: float(row["similarity"]) for row in (resp.data or [])})
            except Exception as e:
                print(f"  [supabase] search_by_text_vibe failed (batch of {len(batch)}): {e}")
        return scores

    try:
        params = {
            "query_embedding": query_embedding,
            "match_count":     limit,
            "min_available":   min_available,
        }
        resp = client.rpc("match_listings", params).execute()
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
    client = get_anon_client()
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
            .order("scraped_at", desc=True)
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


def search_by_image_embedding(
    query_embedding: list,
    limit: int = 200,
    candidate_urls: list[str] | None = None,
) -> dict:
    """
    Call the match_listings_by_image pgvector RPC.

    Same candidate_urls scoping (and same _RPC_CANDIDATE_CHUNK_SIZE batching
    for large candidate sets) as search_by_text_vibe: when given, every URL
    in that set gets scored instead of relying on a global top-`limit`
    cutoff. query_embedding must be a 512-dim CLIP vector.

    Returns {url: similarity_score} where similarity is in [0, 1].
    """
    client = get_anon_client()
    vec_str = "[" + ",".join(str(float(v)) for v in query_embedding) + "]"

    if candidate_urls:
        scores: dict = {}
        for batch in _chunk(candidate_urls, _RPC_CANDIDATE_CHUNK_SIZE):
            try:
                params = {
                    "query_embedding": vec_str,
                    "match_count":     limit,
                    "candidate_urls":  batch,
                }
                resp = _rpc_with_retry(client, "match_listings_by_image", params)
                scores.update({row["url"]: float(row["similarity"]) for row in (resp.data or [])})
            except Exception as e:
                print(f"  [supabase] search_by_image_embedding failed (batch of {len(batch)}): {e}")
        return scores

    try:
        params = {"query_embedding": vec_str, "match_count": limit}
        resp = client.rpc("match_listings_by_image", params).execute()
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
    client = get_anon_client()
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


# ─────────────────────────────────────────────
#  Observability: crawl run / availability check / user search logs
#
#  All backend-only (service-role client). Logging must never break the
#  operation it's observing — every function here catches its own
#  exceptions and returns a sentinel (None / False) rather than raising,
#  and every "finish_*" function no-ops gracefully if run_id is None
#  (meaning the matching "start_*" call already failed).
# ─────────────────────────────────────────────

def start_crawl_run_log(
    mode: str,
    platforms: list[str],
    max_price: int | None = None,
    max_pages: int | None = None,
    stop_threshold: float | None = None,
    proxy_display: str | None = None,
) -> int | None:
    """Insert a 'running' crawl_run_logs row. Returns its id, or None on failure."""
    client = get_client()
    try:
        resp = client.table("crawl_run_logs").insert({
            "mode": mode,
            "platforms": platforms,
            "max_price": max_price,
            "max_pages": max_pages,
            "stop_threshold": stop_threshold,
            "proxy_display": proxy_display,
        }).execute()
        rows = resp.data or []
        return rows[0]["id"] if rows else None
    except Exception as e:
        print(f"  [supabase] start_crawl_run_log failed: {e}")
        return None


def finish_crawl_run_log(
    run_id: int | None,
    listings_new: int = 0,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    """Mark a crawl_run_logs row finished. No-op if run_id is None."""
    if run_id is None:
        return
    from datetime import datetime, timezone
    client = get_client()
    try:
        client.table("crawl_run_logs").update({
            "finished_at":   datetime.now(timezone.utc).isoformat(),
            "listings_new":  listings_new,
            "status":        status,
            "error_message": error_message,
        }).eq("id", run_id).execute()
    except Exception as e:
        print(f"  [supabase] finish_crawl_run_log failed for run {run_id}: {e}")


def start_availability_check_log(platforms: list[str] | None = None) -> int | None:
    """Insert a 'running' availability_check_logs row. Returns its id, or None on failure."""
    client = get_client()
    try:
        resp = client.table("availability_check_logs").insert({
            "platforms": platforms,
        }).execute()
        rows = resp.data or []
        return rows[0]["id"] if rows else None
    except Exception as e:
        print(f"  [supabase] start_availability_check_log failed: {e}")
        return None


def finish_availability_check_log(
    run_id: int | None,
    listings_checked: int = 0,
    listings_expired: int = 0,
    listings_blocked: int = 0,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    """Mark an availability_check_logs row finished. No-op if run_id is None."""
    if run_id is None:
        return
    from datetime import datetime, timezone
    client = get_client()
    try:
        client.table("availability_check_logs").update({
            "finished_at":      datetime.now(timezone.utc).isoformat(),
            "listings_checked": listings_checked,
            "listings_expired": listings_expired,
            "listings_blocked": listings_blocked,
            "status":           status,
            "error_message":    error_message,
        }).eq("id", run_id).execute()
    except Exception as e:
        print(f"  [supabase] finish_availability_check_log failed for run {run_id}: {e}")


def log_user_search(
    session_id: str,
    visitor_id: str,
    http_method: str,
    http_path: str,
    form_fields: dict,
    results_count: int,
    http_query: str | None = None,
    http_body: dict | None = None,
    vibe_text: str | None = None,
    returned_listings: list[dict] | None = None,
    embedding_sorted: bool | None = None,
    error_message: str | None = None,
) -> bool:
    """Insert one user_searches row.

    Not called anywhere yet — there's no HTTP-facing search endpoint until
    MIGRATION_PLAN.md Phase 1 exists. Schema and this function are ready so
    that work is "call this" rather than "design this under time pressure."

    form_fields must be shaped as {field_name: {"value": ..., "source":
    "user" | "nlp" | "unset"}, ...} — the per-field source is what makes
    this table queryable for NLP mistakes later.
    """
    client = get_client()
    try:
        client.table("user_searches").insert({
            "session_id":        session_id,
            "visitor_id":        visitor_id,
            "http_method":       http_method,
            "http_path":         http_path,
            "http_query":        http_query,
            "http_body":         http_body,
            "form_fields":       form_fields,
            "vibe_text":         vibe_text,
            "results_count":     results_count,
            "returned_listings": returned_listings,
            "embedding_sorted":  embedding_sorted,
            "error_message":     error_message,
        }).execute()
        return True
    except Exception as e:
        print(f"  [supabase] log_user_search failed: {e}")
        return False


def log_user_event(
    event_type: str,
    visitor_id: str,
    session_id: str | None = None,
    path: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """Insert one user_events row — minimal alpha traffic tracking
    (page views, listing clicks). Search-specific detail belongs in
    user_searches/log_user_search instead of here.

    Fail-safe like log_user_search: a logging error must never break the
    request that triggered it.
    """
    client = get_client()
    try:
        client.table("user_events").insert({
            "event_type": event_type,
            "visitor_id": visitor_id,
            "session_id": session_id,
            "path":       path,
            "metadata":   metadata,
        }).execute()
        return True
    except Exception as e:
        print(f"  [supabase] log_user_event failed: {e}")
        return False


if __name__ == "__main__":
    client = get_client()
    resp = client.table("listings").select("url", count="exact").limit(1).execute()
    print(f"✅ Connected to Supabase. Listings count: {resp.count}")
