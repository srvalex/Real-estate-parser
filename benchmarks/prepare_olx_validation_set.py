"""
benchmarks/prepare_olx_validation_set.py
────────────────────────────────────────
Pulls the N most recently scraped OLX listings (title + description) into a
labeling template at benchmarks/data/olx_validation_set.jsonl — the
validation set the local-model enrichment benchmark is scored against
(ENRICHMENT_PLAN.md Phase 2/3).

Differs from prepare_enrichment_samples.py, which draws a small *random,
cross-platform* sample: this one is OLX-only and recency-ordered, because
OLX is the platform with zero native structured data
(ENRICHMENT_PLAN.md "Why this exists") and recent rows reflect the current
scraper output (post the Phase 1 `_extract_params` fix), not historical
rows scraped before it.

Each row carries the listing's CURRENT canonical DB values under "db" so a
labeler (and any later coverage report) can see which canonical columns are
blank and would be filled by text extraction. "expected" / "expected_canonical"
are left null for hand-labeling.

Read-only against the DB — there is no write path here.

Run from the project root:
    python benchmarks/prepare_olx_validation_set.py
    python benchmarks/prepare_olx_validation_set.py --n 200
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db_utils import get_client

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "olx_validation_set.jsonl")

# Canonical `listings` columns this dataset tracks: the physical
# characteristics an OLX description can plausibly state. `heating` is
# deliberately excluded — it's covered by the enrichment schema's
# `heating_type` enum instead of being labeled twice in two shapes.
DB_SNAPSHOT_COLUMNS = ("rooms", "area_sqm", "floor", "total_floors", "year_built")

_SELECT = (
    "url, platform, platform_id, title, description, price_numeric, "
    "price_currency, district, city, scraped_at, " + ", ".join(DB_SNAPSHOT_COLUMNS)
)
# Over-fetch: rows with an empty description are dropped client-side (the
# `is null` filter can't catch a whitespace-only one).
_FETCH_MARGIN = 60


def fetch_latest_olx(client, n: int) -> list[dict]:
    resp = (
        client.table("listings")
        .select(_SELECT)
        .eq("platform_id", "olx")
        .not_.is_("description", "null")
        .order("scraped_at", desc=True)
        .limit(n + _FETCH_MARGIN)
        .execute()
    )
    rows = [r for r in (resp.data or []) if (r.get("description") or "").strip()]
    return rows[:n]


def to_template_row(row: dict) -> dict:
    return {
        "url": row["url"],
        "platform": row.get("platform"),
        "scraped_at": row.get("scraped_at"),
        "title": row.get("title") or "",
        "description": row.get("description") or "",
        "db": {col: row.get(col) for col in DB_SNAPSHOT_COLUMNS},
        "expected": None,
        "expected_canonical": None,
    }


def write_template(rows: list[dict], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(to_template_row(row), ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Pull the latest OLX listings into an enrichment labeling template"
    )
    parser.add_argument("--n", type=int, default=200, help="Sample size (default: 200)")
    parser.add_argument("--output", default=OUTPUT_PATH, help="Output JSONL path")
    args = parser.parse_args()

    rows = fetch_latest_olx(get_client(), args.n)
    write_template(rows, args.output)
    print(f"Wrote {len(rows)} OLX listings to {args.output}")


if __name__ == "__main__":
    main()
