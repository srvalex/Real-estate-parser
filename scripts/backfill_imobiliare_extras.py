"""
scripts/backfill_imobiliare_extras.py
──────────────────────────────────────
Re-scrapes every imobiliare.ro listing that has extras IS NULL and writes
the extras (and improved area_sqm) back to Supabase.

Re-scraping is done in batches of 10 via the existing Playwright subprocess
(same path as the live crawler — no new dependencies needed).

Run from the project root:
    python scripts/backfill_imobiliare_extras.py
    python scripts/backfill_imobiliare_extras.py --batch-size 5 --dry-run

Safe to Ctrl-C and re-run: the IS NULL filter skips already-filled rows.
Expired listings are flagged is_available=0 during the pass.
Blocked (network/parse errors) are skipped and will be retried next run.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db_utils import get_client
from scrapers.imobiliare import ImobiliareRoScraper


SCRAPER = ImobiliareRoScraper()


def _fetch_total(client) -> int:
    r = (
        client.table("listings")
        .select("url", count="exact")
        .eq("platform_id", "imobiliare")
        .is_("extras", "null")
        .limit(1)
        .execute()
    )
    return r.count or 0


def _fetch_batch(client, last_url: str, batch_size: int) -> list[dict]:
    r = (
        client.table("listings")
        .select("url")
        .eq("platform_id", "imobiliare")
        .is_("extras", "null")
        .gt("url", last_url)
        .order("url")
        .limit(batch_size)
        .execute()
    )
    return r.data or []


def _update_row(client, url: str, extras: dict, area_sqm: str | None) -> bool:
    payload: dict = {"extras": extras}
    if area_sqm is not None:
        payload["area_sqm"] = area_sqm
    try:
        resp = (
            client.table("listings")
            .update(payload)
            .eq("url", url)
            .execute()
        )
        return bool(resp.data)
    except Exception as e:
        print(f"    ✗ update failed {url[:70]}: {e}")
        return False


def _mark_expired(client, url: str) -> None:
    try:
        client.table("listings").update({"is_available": 0}).eq("url", url).execute()
    except Exception:
        pass


def run_backfill(batch_size: int = 10, dry_run: bool = False) -> None:
    client = get_client()

    total = _fetch_total(client)
    print(f"\n{total:,} imobiliare rows need extras backfill.\n")
    if total == 0:
        print("Nothing to do.")
        return

    done = 0
    expired = 0
    blocked = 0
    failed = 0
    last_url = ""

    while True:
        db_rows = _fetch_batch(client, last_url, batch_size)
        if not db_rows:
            break

        last_url = db_rows[-1]["url"]
        urls = [r["url"] for r in db_rows]

        print(f"  scraping {len(urls)} URLs (done so far: {done}/{total})…", flush=True)

        raw_results = SCRAPER._fetch_batch_raw(urls)

        # Index results by URL for O(1) lookup
        result_map = {r.get("url"): r for r in raw_results if r.get("url")}

        for url in urls:
            raw = result_map.get(url)

            if raw is None:
                # subprocess returned nothing for this URL — network/timeout
                blocked += 1
                continue

            status = raw.get("status", "blocked")

            if status == "expired":
                if not dry_run:
                    _mark_expired(client, url)
                expired += 1
                continue

            if status != "success":
                blocked += 1
                continue

            parsed = SCRAPER._parse_raw(raw)
            if not parsed:
                blocked += 1
                continue

            extras   = parsed.get("extras")
            area_sqm = parsed.get("area_sqm")

            if not extras:
                # Page loaded but yielded no extras (rare) — skip so IS NULL
                # filter catches it again on the next run
                blocked += 1
                continue

            if not dry_run:
                if _update_row(client, url, extras, area_sqm):
                    done += 1
                else:
                    failed += 1
            else:
                done += 1

        pct = (done + expired + blocked + failed) / total * 100
        print(
            f"    [{pct:5.1f}%]  filled: {done}  expired: {expired}"
            f"  blocked/retry: {blocked}  failed: {failed}"
        )

        time.sleep(0.2)   # brief pause between Playwright subprocess calls

    tag = " (DRY RUN)" if dry_run else ""
    print(
        f"\nBackfill done{tag}.\n"
        f"   Extras filled : {done:,}\n"
        f"   Expired       : {expired:,}\n"
        f"   Blocked/retry : {blocked:,}\n"
        f"   Failed (DB)   : {failed:,}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Backfill extras column for imobiliare.ro listings"
    )
    parser.add_argument(
        "--batch-size", type=int, default=10,
        help="Listing URLs per Playwright subprocess call (default: 10)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scrape but do not write to Supabase",
    )
    args = parser.parse_args()
    run_backfill(batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
