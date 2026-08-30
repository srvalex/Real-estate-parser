"""
scripts/olx_params_coverage_check.py
──────────────────────────────────────
Read-only live check: re-scrapes the most recently scraped OLX listings and
reports how often the new "ad-parameters-container" extraction
(scrapers/olx.py: _extract_params) actually finds each of the four target
params (Compartimentare, Suprafata utila, An constructie, Etaj) — see
ENRICHMENT_PLAN.md Phase 1.

Unlike scripts/inspect_extras.py (which reads the `extras` already stored in
Supabase), this script re-fetches each listing URL live, because the params
container was never scraped before this change — there's nothing to inspect
in the DB yet. No writes are made to Supabase; this is a coverage/accuracy
report only, not a backfill.

Run from the project root (venv active):
    python scripts/olx_params_coverage_check.py [--limit N] [--sleep SECONDS]
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

from db_utils import get_anon_client, get_client
from scrapers.olx import OLXScraper

TARGET_FIELDS = ("m", "floor_no", "build_year", "compartimentare")


def _load_recent_olx_urls(limit: int) -> list[str]:
    try:
        client = get_anon_client()
    except Exception:
        client = get_client()  # fall back if anon key not configured locally
    resp = (
        client.table("listings")
        .select("url, scraped_at")
        .eq("platform", "OLX")
        .order("scraped_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [row["url"] for row in (resp.data or [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100, help="how many recent OLX listings to re-check")
    ap.add_argument("--sleep", type=float, default=1.5, help="delay between live requests (seconds)")
    ap.add_argument("--out", default="scripts/olx_params_coverage_report.json")
    args = ap.parse_args()

    urls = _load_recent_olx_urls(args.limit)
    print(f"Loaded {len(urls)} recent OLX listing URLs from Supabase.\n")

    scraper = OLXScraper()
    status_counts = {"success": 0, "expired": 0, "blocked": 0}
    field_counts = {f: 0 for f in TARGET_FIELDS}
    examples = {f: [] for f in TARGET_FIELDS}
    failures: list[str] = []

    for i, url in enumerate(urls, 1):
        result = scraper.scrape_listing_with_status(url)
        status = result["status"]
        status_counts[status] = status_counts.get(status, 0) + 1

        if status == "success":
            data = result["data"]
            for field in TARGET_FIELDS:
                if field in data:
                    field_counts[field] += 1
                    if len(examples[field]) < 5:
                        examples[field].append(data[field])
        else:
            failures.append(f"{url} -> {status}")

        print(f"  [{i}/{len(urls)}] {status:<8} {url[:80]}")
        if i < len(urls):
            time.sleep(args.sleep)

    success_n = status_counts.get("success", 0)
    print("\n" + "=" * 70)
    print(f"Status breakdown: {status_counts}")
    print(f"\nParam coverage (of {success_n} successfully-parsed listings):")
    for field in TARGET_FIELDS:
        n = field_counts[field]
        pct = (n / success_n * 100) if success_n else 0.0
        print(f"  {field:<16} {n:>4}/{success_n} ({pct:5.1f}%)  examples: {examples[field]}")

    report = {
        "sampled": len(urls),
        "status_counts": status_counts,
        "field_coverage": {
            f: {"count": field_counts[f], "of": success_n, "examples": examples[f]}
            for f in TARGET_FIELDS
        },
        "failures": failures,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"\nFull report written to {args.out}")


if __name__ == "__main__":
    main()
