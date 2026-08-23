"""
scripts/mark_blank_listings_unavailable.py
───────────────────────────────────────────
One-off cleanup: flips is_available -> 0 for listings that are marked "live"
(is_available=1) but carry no usable content at all (no title, description,
price, or district).

Root cause (found 2026-08-23): the old Imobiliare scraper, before the
classify_imobiliare_ld_graph fix in scripts/get_imobiliare_listing.py,
misclassified certain bot-challenge/blocked pages as a successful scrape,
producing a "live" row with every field empty. Confirmed via first_seen_at
that every affected row was created between 2026-06-16 and 2026-07-05 —
well before that fix — and none since, so this is a one-time backlog, not an
ongoing leak.

These rows are actively harmful in two ways:
  1. They can never get a text embedding (nothing to embed), so any search
     that happens to scope down to mostly/only these rows sees
     "AI ranking unavailable: No pgvector matches" with no clear explanation.
  2. They render as blank/broken listing cards (no title, no photo, no
     price) in normal search results, since is_available=1 tells the rest
     of the app to treat them as real, live listings.

Marking them is_available=0 (rather than deleting or re-scraping) was the
chosen fix: cheap, safe, reversible (the URL isn't lost, just hidden), and
matches the existing meaning of is_available=0 elsewhere in the schema
("confirmed expired / not shown to users").

Run from the project root:
    python scripts/mark_blank_listings_unavailable.py            # dry run
    python scripts/mark_blank_listings_unavailable.py --execute  # apply
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db_utils import get_client


def is_blank_listing(row: dict) -> bool:
    """True if a listing has no usable content at all: no title, description,
    price, or district. Deliberately conservative — a row with even one of
    these populated is left alone, since it has *something* worth showing or
    fixing rather than hiding."""
    return (
        not (row.get("title") or "").strip()
        and not (row.get("description") or "").strip()
        and row.get("price_numeric") is None
        and not (row.get("district") or "").strip()
    )


def find_blank_available_listings(client) -> list[dict]:
    """Fetch every is_available=1 row with no embedding (a blank listing can
    never have one), then filter down to the ones with genuinely no content."""
    rows = []
    last_url = ""
    while True:
        resp = (
            client.table("listings")
            .select("url, title, description, price_numeric, district")
            .eq("is_available", 1)
            .is_("embedding", "null")
            .gt("url", last_url)
            .order("url")
            .limit(1000)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        rows.extend(batch)
        last_url = batch[-1]["url"]
        if len(batch) < 1000:
            break
    return [r for r in rows if is_blank_listing(r)]


def run(execute: bool = False) -> None:
    client = get_client()
    blank = find_blank_available_listings(client)

    print(f"\n{len(blank):,} listings are marked available but have no usable content.\n")
    if not blank:
        print("Nothing to do.")
        return

    for r in blank[:10]:
        print(f"  {r['url']}")
    if len(blank) > 10:
        print(f"  … and {len(blank) - 10} more")

    if not execute:
        print("\nDry run only — nothing was changed. Re-run with --execute to apply.")
        return

    updated, failed = 0, 0
    for r in blank:
        try:
            resp = (
                client.table("listings")
                .update({"is_available": 0})
                .eq("url", r["url"])
                .execute()
            )
            if resp.data:
                updated += 1
            else:
                failed += 1
                print(f"    ? no row updated for {r['url'][:70]}")
        except Exception as e:
            failed += 1
            print(f"    ✗ {r['url'][:70]}: {e}")

    print(f"\n✅ Done. Marked unavailable: {updated:,}  |  failed: {failed:,}")


def main():
    parser = argparse.ArgumentParser(
        description="Mark blank (title/description/price/district all empty) "
        "is_available=1 listings as is_available=0"
    )
    parser.add_argument("--execute", action="store_true",
                        help="Apply the change (default is a dry run)")
    args = parser.parse_args()
    run(execute=args.execute)


if __name__ == "__main__":
    main()
