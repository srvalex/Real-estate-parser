"""
analysis/fetch_cache.py
─────────────────
One-shot pull of the listings behind the LinkedIn-post exploration, cached
to analysis/cache/ so the analysis can be re-run and re-cut without hitting
Supabase again.

Uses the SERVICE-ROLE client, not the anon one. The anon key is constrained
by RLS to is_available = 1 rows (scripts/supabase_schema.sql), so an
anon-key pull could never reproduce a query that groups BY is_available —
it would silently return only the available half and look complete. This is
an admin analysis script, which is exactly what get_client() is for.

Mirrors the reporting logic of the SQL being explored:
  - price normalised to EUR (RON / _RON_TO_EUR)
  - property_type reclassified: 1 room -> "Garsoniera";
    a "Garsoniera" with more than 1 room -> "Apartament"
  - Bucharest districts mapped to sectors via api.locations.sector_for
"""
import ast
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db_utils  # noqa: E402
from api.locations import sector_for  # noqa: E402
from fees import extract as extract_fees  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_HERE, "cache")
RAW_CSV = os.path.join(CACHE_DIR, "listings_since_2026-08-01.csv")

SINCE = "2026-08-01"

# Pinned, not fetched live: every number in the cache must stay reproducible.
# db_utils.get_ron_to_eur_rate() moves daily, so re-running the analysis
# tomorrow against a live rate would shift figures that are already written
# into a post. This is the BNR rate on 2026-09-08.
_RON_TO_EUR = 5.2508

COLUMNS = (
    "url, is_available, city, district, property_type, rooms, "
    "price_numeric, price_currency, area_sqm, platform_id, first_seen_at, features, "
    "description"
)


def fetch_raw() -> pd.DataFrame:
    """Keyset ("seek") pagination on the primary key.

    NOT offset pagination. Two separate problems ruled it out:

    * Correctness. `.range()` with no ORDER BY lets Postgres return rows in
      a different order per request, so the windows overlap and skip. An
      earlier version of this pull returned 18,449 rows containing only
      13,410 distinct URLs — 27% duplicated, plus an unknown number missed.
    * Speed. Adding `.order("url")` fixed the correctness but made it time
      out: OFFSET n still has to walk and discard n rows, so each page costs
      more than the last.

    Seeking on `url > last_seen` does both jobs at once — `url` is the
    PRIMARY KEY, so its index gives a total order AND an O(log n) seek to
    each page boundary. Cost per page is flat.
    """
    client = db_utils.get_client()
    rows: list[dict] = []
    last_url = ""
    page = 1000
    while True:
        resp = (
            client.table("listings")
            .select(COLUMNS)
            .gte("first_seen_at", SINCE)
            .gt("url", last_url)
            .order("url")
            .limit(page)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        rows.extend(batch)
        last_url = batch[-1]["url"]
        print(f"  fetched {len(rows):,}", end="\r")
        if len(batch) < page:
            break
    print()
    return pd.DataFrame(rows)


def _agency_flag(value) -> object:
    """True / False / None from the `features` blob.

    `features` is TEXT holding a Python repr of a list ("['agency', 'lift',
    ...]"), not real JSON, so it is parsed with literal_eval — the same
    tolerance api/main.py::_parse_list_field applies.

    Three states, deliberately not two: a listing whose features are absent
    or unparseable is None (unknown), NOT False. Collapsing unknown into
    "private" would invent a private-landlord population out of missing
    data, which is exactly the error this flag exists to test for.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return None
    if not isinstance(value, list):
        return None
    return "agency" in {str(t).strip().lower() for t in value}


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["price_numeric"] = pd.to_numeric(df["price_numeric"], errors="coerce")
    df["area_sqm"] = pd.to_numeric(df["area_sqm"], errors="coerce")

    is_ron = df["price_currency"].eq("RON")
    df["price_eur"] = df["price_numeric"].where(~is_ron, df["price_numeric"] / _RON_TO_EUR)

    # rooms reaches us as free text ("2 camere", "2", "7"); fold to the
    # reporting buckets the dashboard uses so groupings are comparable.
    extracted = df["rooms"].astype(str).str.extract(r"(\d+)")[0]
    n = pd.to_numeric(extracted, errors="coerce")
    # Map straight off `n`. An earlier version routed this through
    # n.where(n < 5, 5) first — but `NaN < 5` is False, so where() replaced
    # every MISSING rooms value with 5, quietly filing 1,157 room-less rows
    # into the "5+" bucket. That made "5+ rooms" show a 56 m² median: a
    # two-room flat wearing a five-room label.
    df["rooms_norm"] = n.map(
        lambda v: "?" if pd.isna(v) else ("5+" if v >= 5 else str(int(v)))
    )

    # The reclassification under discussion: room count is the more reliable
    # signal than the platform's own property_type label.
    pt = df["property_type"]
    df["property_type_norm"] = pt.where(
        df["rooms_norm"] != "1", "Garsoniera"
    ).where(
        ~((df["rooms_norm"] != "1") & pt.eq("Garsoniera")), "Apartament"
    )

    # fillna before zipping: a missing district arrives from pandas as NaN,
    # which is a truthy float — `d or ""` would pass the float straight into
    # sector_for's regex and raise.
    cities = df["city"].fillna("").astype(str)
    districts = df["district"].fillna("").astype(str)
    df["sector"] = [sector_for(c, d) for c, d in zip(cities, districts)]
    df["is_agency"] = df["features"].map(_agency_flag)

    # Fee terms parsed out of the free-text description (analysis/fees.py).
    # This is the cross-platform ownership signal: `features` carries the
    # `agency` token on Storia ONLY, whereas "fara comision" / "direct
    # proprietar" is written by sellers on all three portals. Note it
    # measures a different thing from is_agency — whether a fee is charged,
    # not who posted — so the two are compared, never merged.
    fees = pd.DataFrame([extract_fees(d) for d in df["description"].fillna("")])
    df["fee_comision"] = fees["comision"].values
    df["fee_garantie"] = fees["garantie"].values
    df["fee_avans"] = fees["avans"].values
    df["fee_signal"] = df["fee_comision"].map(
        lambda v: "fara comision" if v.startswith("0%")
        else ("cu comision" if v[0].isdigit() else "nespecificat")
    )
    # Drop the raw text before caching: it is ~10x the size of every other
    # column combined and nothing downstream reads it again.
    df = df.drop(columns=["description"])
    df["price_per_sqm"] = df["price_eur"] / df["area_sqm"]
    return df


REQUIRED_COLUMNS = [c.strip() for c in COLUMNS.split(",")]


def load_export(path: str) -> pd.DataFrame:
    """Normalise a CSV exported straight from the Supabase SQL editor.

    Preferred over fetch_raw(): one statement returns the whole result set,
    so there is no pagination to get wrong, and it does not sit on a
    long-running paginated read that the PostgREST client times out on.
    """
    raw = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise SystemExit(f"ABORT: export is missing column(s): {', '.join(missing)}")
    return raw


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-csv",
        metavar="PATH",
        help="Normalise a CSV exported from the Supabase SQL editor instead of "
             "querying the API (see analysis/QUERY.sql).",
    )
    args = parser.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)
    if args.from_csv:
        print(f"Loading export: {args.from_csv}")
        raw = load_export(args.from_csv)
    else:
        print(f"Fetching listings first_seen_at >= {SINCE} (service-role, includes expired)…")
        raw = fetch_raw()
    print(f"  {len(raw):,} rows")

    dupes = raw["url"].duplicated().sum()
    if dupes:
        raise SystemExit(
            f"ABORT: {dupes:,} duplicate URLs in the pull — pagination is not stable. "
            "Do not trust this cache."
        )

    df = normalise(raw)
    df.to_csv(RAW_CSV, index=False)
    print(f"  cached -> {RAW_CSV}")

    print("\nSanity check")
    print(f"  is_available mix : {df['is_available'].value_counts().to_dict()}")
    print(f"  cities           : {df['city'].value_counts().to_dict()}")
    print(f"  currency mix     : {df['price_currency'].value_counts().to_dict()}")
    print(f"  rooms buckets    : {df['rooms_norm'].value_counts().to_dict()}")
    print(f"  with price       : {df['price_eur'].notna().sum():,}")
    print(f"  with area        : {df['area_sqm'].notna().sum():,}")
    reclassified = (df["property_type"] != df["property_type_norm"]).sum()
    print(f"  reclassified rows: {reclassified:,}")


if __name__ == "__main__":
    main()
