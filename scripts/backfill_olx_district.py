"""
scripts/backfill_olx_district.py
─────────────────────────────────
Fills the missing `district` column on OLX listings by matching known
neighbourhood names against the URL slug.

OLX URL format:
  https://www.olx.ro/d/oferta/<title-slug>-ID<id>.html?...

The title slug is extracted and checked against every neighbourhood in
districts.json (slugified: lowercase, diacritics stripped, spaces → hyphens).
Longer matches are tried first so "drumul-taberei" wins over "drum".

Run from the project root:
    python scripts/backfill_olx_district.py
    python scripts/backfill_olx_district.py --dry-run
"""

import argparse
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db_utils import get_client

_DISTRICTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Streamlit Interface", "districts.json",
)


def _to_slug(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_str.lower()).strip("-")


def _build_slug_map() -> list[tuple[str, str]]:
    """Return [(slug, district_name), ...] sorted longest-slug-first."""
    with open(_DISTRICTS_PATH, encoding="utf-8") as f:
        districts = json.load(f)
    pairs = []
    for neighbourhoods in districts.values():
        for name in neighbourhoods:
            pairs.append((_to_slug(name), name))
    # Longest slug first — prevents "drum" matching before "drumul-taberei"
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs


def _extract_url_slug(url: str) -> str:
    """Extract the title slug from an OLX listing URL."""
    m = re.search(r"/oferta/(.+?)(?:-ID[a-zA-Z0-9]+)?(?:\.html)?(?:\?|$)", url)
    if not m:
        return ""
    return m.group(1).lower()


def _match_district(url_slug: str, slug_map: list[tuple[str, str]]) -> str | None:
    for slug, name in slug_map:
        if slug in url_slug:
            return name
    return None


def run_backfill(dry_run: bool = False) -> None:
    client = get_client()
    slug_map = _build_slug_map()

    # Count total
    total_r = (
        client.table("listings")
        .select("url", count="exact")
        .eq("platform_id", "olx")
        .or_("district.is.null,district.eq.Unknown")
        .limit(1)
        .execute()
    )
    total = total_r.count or 0
    print(f"\n{total:,} OLX listings with missing district.\n")
    if total == 0:
        print("Nothing to do.")
        return

    filled = 0
    unmatched = 0
    failed = 0
    offset = 0
    page_size = 500
    last_url = ""

    while True:
        resp = (
            client.table("listings")
            .select("url")
            .eq("platform_id", "olx")
            .or_("district.is.null,district.eq.Unknown")
            .gt("url", last_url)
            .order("url")
            .limit(page_size)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        last_url = batch[-1]["url"]

        updates: list[tuple[str, str]] = []
        for row in batch:
            url = row["url"]
            slug = _extract_url_slug(url)
            district = _match_district(slug, slug_map)
            if district:
                updates.append((url, district))
            else:
                unmatched += 1

        if updates and not dry_run:
            for url, district in updates:
                try:
                    client.table("listings").update({"district": district}).eq("url", url).execute()
                    filled += 1
                except Exception as e:
                    print(f"    update failed {url[-60:]}: {e}")
                    failed += 1
        else:
            filled += len(updates)

        processed = filled + unmatched + failed
        pct = processed / total * 100
        print(
            f"  [{pct:5.1f}%]  filled: {filled}  unmatched: {unmatched}  failed: {failed}",
            flush=True,
        )

    tag = " (DRY RUN)" if dry_run else ""
    print(
        f"\nBackfill done{tag}.\n"
        f"   Filled    : {filled:,}\n"
        f"   Unmatched : {unmatched:,}\n"
        f"   Failed    : {failed:,}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Backfill district column for OLX listings from URL slug"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Match but do not write to Supabase")
    args = parser.parse_args()
    run_backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
