"""
benchmarks/export_olx_validation_set.py
───────────────────────────────────────
Flattens benchmarks/data/olx_validation_set.jsonl into a CSV for reading
and spot-checking by hand (spreadsheet, diff, whatever) — the JSONL stays
the source of truth that the benchmark scores against.

Column groups, left to right: the listing (url/title/description), `db_*`
= what the canonical columns hold today, `label_*` = the hand-labeled
enrichment fields, `text_*` = the canonical values the description states.
`db_*` vs. `text_*` side by side is the point: that is where extraction
would add a value, or disagree with the scraper.

Pure file I/O, no DB and no model calls.

Run from the project root:
    python benchmarks/export_olx_validation_set.py
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.prepare_olx_validation_set import DB_SNAPSHOT_COLUMNS
from benchmarks.summarize_olx_validation_set import DATASET_PATH, load_rows

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "olx_validation_set.csv")

_LABEL_FIELDS = ("own_heating", "parking_available", "pets_allowed", "renovation_status")
_CANONICAL_FIELDS = ("rooms", "area_sqm", "floor", "total_floors", "year_built")

FIELDNAMES = (
    ["url", "scraped_at", "title", "description"]
    + [f"db_{c}" for c in DB_SNAPSHOT_COLUMNS]
    + [f"label_{f}" for f in _LABEL_FIELDS]
    + [f"text_{f}" for f in _CANONICAL_FIELDS]
)


def to_csv_row(row: dict) -> dict:
    """One dataset row flattened to FIELDNAMES.

    An unlabeled row (`expected` still null, as prepare_olx_validation_set
    writes it) exports with empty label columns rather than blowing up, so
    a partially-labeled file is still readable.
    """
    expected = row.get("expected") or {}
    canonical = row.get("expected_canonical") or {}

    out = {
        "url": row["url"],
        "scraped_at": row.get("scraped_at"),
        "title": row.get("title", ""),
        # Newlines survive CSV quoting fine, but they make the file
        # unreadable in a terminal and in some spreadsheet importers.
        "description": " ".join((row.get("description") or "").split()),
    }
    for col in DB_SNAPSHOT_COLUMNS:
        out[f"db_{col}"] = row.get("db", {}).get(col)
    for field in _LABEL_FIELDS:
        out[f"label_{field}"] = expected.get(field)
    for field in _CANONICAL_FIELDS:
        out[f"text_{field}"] = canonical.get(field)
    return out


def write_csv(rows: list[dict], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(to_csv_row(row) for row in rows)


def main():
    parser = argparse.ArgumentParser(description="Export the OLX validation set as CSV")
    parser.add_argument("--dataset", default=DATASET_PATH)
    parser.add_argument("--output", default=OUTPUT_PATH)
    args = parser.parse_args()

    rows = load_rows(args.dataset)
    write_csv(rows, args.output)
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
