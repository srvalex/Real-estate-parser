"""
benchmarks/prepare_enrichment_samples.py
───────────────────────────────────────────
Pulls a random sample of real listings (title + description) from Supabase
and writes a labeling template to benchmarks/data/enrichment_samples.jsonl —
one JSON object per line, "expected" left null for the user to fill in by
hand before running run_enrichment_benchmark.py.

Weighted toward OLX per ENRICHMENT_PLAN.md's Phase 2 guidance ("weighted
toward OLX since it has zero structured data today") — 60% OLX, 40% other
platforms by default.

Read-only against the DB — no writes, same as backfill_embeddings.py's
--dry-run mode but here there's no non-dry-run path at all.

Run from the project root:
    python benchmarks/prepare_enrichment_samples.py
    python benchmarks/prepare_enrichment_samples.py --n 25 --olx-fraction 0.6
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db_utils import get_client

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "enrichment_samples.jsonl")
# Fetch more rows than needed per platform bucket, then randomly sample down —
# postgrest has no ORDER BY random() we can reach from the client.
_FETCH_MULTIPLIER = 8


def _fetch_pool(client, platform: str | None, pool_size: int) -> list[dict]:
    query = (
        client.table("listings")
        .select("url, title, description, platform")
        .not_.is_("description", "null")
        .limit(pool_size)
    )
    if platform is not None:
        query = query.eq("platform", platform)
    else:
        query = query.neq("platform", "OLX")
    resp = query.execute()
    return resp.data or []


def prepare_samples(n: int, olx_fraction: float) -> list[dict]:
    client = get_client()
    n_olx = round(n * olx_fraction)
    n_other = n - n_olx

    olx_pool = _fetch_pool(client, "OLX", n_olx * _FETCH_MULTIPLIER)
    other_pool = _fetch_pool(client, None, n_other * _FETCH_MULTIPLIER)

    olx_sample = random.sample(olx_pool, min(n_olx, len(olx_pool)))
    other_sample = random.sample(other_pool, min(n_other, len(other_pool)))

    combined = olx_sample + other_sample
    random.shuffle(combined)
    return combined


def write_template(rows: list[dict], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({
                "url": row["url"],
                "platform": row.get("platform"),
                "title": row.get("title") or "",
                "description": row.get("description") or "",
                "expected": None,
            }, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Pull a labeling sample of real listings for the enrichment benchmark"
    )
    parser.add_argument("--n", type=int, default=25, help="Total sample size (default: 25)")
    parser.add_argument(
        "--olx-fraction", type=float, default=0.6,
        help="Fraction of the sample pulled from OLX (default: 0.6)",
    )
    parser.add_argument("--output", default=OUTPUT_PATH, help="Output JSONL path")
    args = parser.parse_args()

    rows = prepare_samples(args.n, args.olx_fraction)
    write_template(rows, args.output)

    print(f"Wrote {len(rows)} samples to {args.output}")
    print(
        'Fill in "expected" for each line as an EnrichmentResult-shaped dict, e.g.:\n'
        '  {"heating_type": "gas", "parking": {"available": true, "type": "private"}, '
        '"pets_allowed": "unknown", "renovation_status": "renovated"}'
    )


if __name__ == "__main__":
    main()
