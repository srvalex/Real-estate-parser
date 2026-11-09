"""
benchmarks/summarize_olx_validation_set.py
──────────────────────────────────────────
Reports what the hand-labeled OLX validation set
(benchmarks/data/olx_validation_set.jsonl) actually contains: label
distribution per field, and — the number that decides whether Phase 2 is
worth running at all — how many canonical DB blanks the description text
can fill that the scraper's params block did not.

Pure file I/O, no DB and no model calls.

Run from the project root:
    python benchmarks/summarize_olx_validation_set.py
"""

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.prepare_olx_validation_set import DB_SNAPSHOT_COLUMNS

DATASET_PATH = os.path.join(os.path.dirname(__file__), "data", "olx_validation_set.jsonl")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "data", "olx_validation_set_report.md")

ENRICHMENT_FIELDS = ("own_heating", "parking_available", "pets_allowed", "renovation_status")


def load_rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def label_distribution(rows: list[dict]) -> dict[str, Counter]:
    return {
        field: Counter(str(r["expected"][field]) for r in rows)
        for field in ENRICHMENT_FIELDS
    }


def _same_value(column: str, db_value, text_value) -> bool:
    """Compare a DB value against a text-stated one the way the column
    means it. `area_sqm` is numeric and the scraper rounds ("63,3 mp" is
    stored as 63) — a sub-1 m² gap is the same number written twice, not a
    contradiction. Everything else is a TEXT column compared case- and
    whitespace-insensitively; note that OLX's params block stores fuzzy
    `year_built` buckets ("Dupa 2000"), so a text-stated exact year will
    always read as a contradiction there — that is a real difference in
    precision, not a bug in either value.
    """
    if column == "area_sqm":
        try:
            return abs(float(db_value) - float(text_value)) < 1
        except (TypeError, ValueError):
            return False
    return str(db_value).strip().lower() == str(text_value).strip().lower()


def canonical_coverage(rows: list[dict]) -> dict[str, dict[str, int]]:
    """Per canonical column: how many rows are blank in the DB today, and of
    those, how many the description states a value for (`fills_blank`) —
    i.e. what LLM extraction would actually add on top of Phase 1's params
    block. `contradicts` counts rows where the DB has a value AND the text
    states a different one; those are worth eyeballing before any writer
    is allowed to overwrite scraper-confirmed data.
    """
    stats = {col: dict(db_blank=0, fills_blank=0, text_states=0, contradicts=0)
             for col in DB_SNAPSHOT_COLUMNS}
    for row in rows:
        for col in DB_SNAPSHOT_COLUMNS:
            db_value = row["db"].get(col)
            text_value = row["expected_canonical"].get(col)
            if text_value is not None:
                stats[col]["text_states"] += 1
            if db_value in (None, ""):
                stats[col]["db_blank"] += 1
                if text_value is not None:
                    stats[col]["fills_blank"] += 1
            elif text_value is not None and not _same_value(col, db_value, text_value):
                stats[col]["contradicts"] += 1
    return stats


def render(rows: list[dict]) -> str:
    lines = [
        "# OLX validation set — label summary",
        "",
        f"{len(rows)} hand-labeled OLX listings "
        f"({rows[-1]['scraped_at']} .. {rows[0]['scraped_at']}).",
        "",
        "## Enrichment label distribution",
        "",
        "| field | value | n |",
        "|---|---|---:|",
    ]
    for field, counts in label_distribution(rows).items():
        for value, n in counts.most_common():
            lines.append(f"| {field} | {value} | {n} |")

    lines += [
        "",
        "## Canonical column coverage",
        "",
        "`db_blank` = NULL in the DB today; `fills_blank` = of those, how many "
        "the description states (what extraction would add); `contradicts` = "
        "DB has a value and the text states a different one.",
        "",
        "| column | db_blank | fills_blank | text_states | contradicts |",
        "|---|---:|---:|---:|---:|",
    ]
    for col, s in canonical_coverage(rows).items():
        lines.append(
            f"| {col} | {s['db_blank']} | {s['fills_blank']} | {s['text_states']} | {s['contradicts']} |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Summarize the OLX enrichment validation set")
    parser.add_argument("--dataset", default=DATASET_PATH)
    parser.add_argument("--output", default=REPORT_PATH)
    args = parser.parse_args()

    rows = load_rows(args.dataset)
    report = render(rows)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
