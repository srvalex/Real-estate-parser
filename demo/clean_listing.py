"""
demo/clean_listing.py
──────────────────────
Presentation CLI — take the raw scrape output for a platform (written by
scrape_listing.py) and run it through the exact same canonicalisation used in
production (db_utils._clean_record) before every Supabase upsert, to show the
data-cleaning step.

Usage:
    python demo/clean_listing.py <olx|storia|imobiliare>

Output: demo/output/cleaned/<platform>_cleaned.md
"""
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_utils import _clean_record, _CANONICAL_COLUMNS
from scrapers import SCRAPERS

RAW_DIR = os.path.join(os.path.dirname(__file__), "output", "raw")
CLEAN_DIR = os.path.join(os.path.dirname(__file__), "output", "cleaned")

# raw field(s) -> canonical field, shown only when the raw field is actually present
POSSIBLE_RENAMES = {
    "price_eur":          "price_numeric + price_currency",
    "rooms_num":          "rooms",
    "m":                  "area_sqm",
    "location_full_name": "location_full",
    "floor_no":           "floor",
    "build_year":         "year_built",
}


def _extract_json_block(md_text: str) -> dict:
    m = re.search(r"```json\s*(.*?)\s*```", md_text, flags=re.S)
    if not m:
        raise RuntimeError("No JSON code block found in the raw markdown file")
    return json.loads(m.group(1))


def main():
    if len(sys.argv) != 2:
        print("Usage: python demo/clean_listing.py <olx|storia|imobiliare>")
        sys.exit(1)

    pid = sys.argv[1].strip().lower()
    if pid not in SCRAPERS:
        print(f"Unknown platform {pid!r}. Choose from: {', '.join(SCRAPERS)}")
        sys.exit(1)

    raw_path = os.path.join(RAW_DIR, f"{pid}_raw.md")
    if not os.path.exists(raw_path):
        print(f"No raw scrape found at {raw_path} -- run scrape_listing.py first")
        sys.exit(1)

    with open(raw_path, encoding="utf-8") as f:
        raw = _extract_json_block(f.read())

    cleaned = _clean_record(raw)
    if cleaned is None:
        print("_clean_record() rejected this record (missing URL)")
        sys.exit(1)

    # _clean_record() strips None/NaN values *before* filtering to canonical
    # columns, so a missing raw field and a genuinely non-canonical field both
    # end up absent from `cleaned` -- distinguish them for the presentation.
    missing_value  = sorted(k for k in raw if k not in cleaned and raw[k] is None)
    non_canonical  = sorted(
        k for k in raw
        if k not in cleaned and raw[k] is not None and k not in _CANONICAL_COLUMNS
    )
    applied_renames = [(k, v) for k, v in POSSIBLE_RENAMES.items() if k in raw]

    os.makedirs(CLEAN_DIR, exist_ok=True)
    out_path = os.path.join(CLEAN_DIR, f"{pid}_cleaned.md")
    scraper = SCRAPERS[pid]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Canonical record -- {scraper.display_name}\n\n")
        f.write(f"- **Cleaned at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- **Source:** `output/raw/{pid}_raw.md`\n")
        f.write("- Produced by `db_utils._clean_record()` -- the exact function every\n")
        f.write("  scraped listing passes through before being upserted into Supabase.\n\n")

        f.write("## Canonical record\n\n```json\n")
        f.write(json.dumps(cleaned, ensure_ascii=False, indent=2))
        f.write("\n```\n\n")

        if applied_renames:
            f.write("## Transformations applied to this record\n\n")
            f.write("| Raw field | Canonical field |\n|---|---|\n")
            for raw_f, clean_f in applied_renames:
                f.write(f"| `{raw_f}` | `{clean_f}` |\n")
            f.write("\n")

        if non_canonical:
            f.write("## Raw fields not part of the canonical schema (dropped)\n\n")
            for k in non_canonical:
                f.write(f"- `{k}`\n")
            f.write("\n")

        if missing_value:
            f.write("## Canonical fields with no value on this listing\n\n")
            for k in missing_value:
                f.write(f"- `{k}` (was `null` on the raw scrape)\n")
            f.write("\n")

    print(f"Canonical record written to {out_path}")


if __name__ == "__main__":
    main()
