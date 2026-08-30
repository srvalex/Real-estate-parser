"""
inspect_extras.py
──────────────────
Read-only introspection of the `extras` JSONB column: samples listings per
platform, flattens their extras dict, and reports which keys actually occur
(frequency, platforms, value types, example values).

Output feeds the extras allowlist for the text-to-SQL query model — we
don't want to hand an LLM free-form JSONB paths against a column whose
shape differs per scraper (Storia extras = entire raw ad JSON, Imobiliare
extras = a flatter purpose-built dict). This script tells us which paths
are common/stable enough to expose as filterable fields.

Usage:
    python scripts/inspect_extras.py [--limit N] [--max-depth D]
"""

import argparse
import json
from collections import defaultdict

from db_utils import get_anon_client, get_client


def flatten(obj, prefix="", max_depth=4, depth=0, out=None):
    if out is None:
        out = {}
    if depth >= max_depth or obj is None:
        if prefix:
            out.setdefault(prefix, []).append(obj)
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            flatten(v, path, max_depth, depth + 1, out)
    elif isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            out.setdefault(prefix, []).append(obj)
        else:
            for i, x in enumerate(obj[:3]):  # cap fan-out on arrays of objects
                flatten(x, f"{prefix}[]", max_depth, depth + 1, out)
    else:
        out.setdefault(prefix, []).append(obj)
    return out


def python_type(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, list):
        return "list"
    if v is None:
        return "null"
    return "string"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=150, help="rows per platform")
    ap.add_argument("--max-depth", type=int, default=4)
    args = ap.parse_args()

    try:
        client = get_anon_client()
    except RuntimeError:
        client = get_client()  # fall back if anon key not configured locally

    platforms = ["Storia", "OLX", "Imobiliare.ro"]
    stats = defaultdict(lambda: {
        "count": 0, "platforms": set(), "types": set(), "examples": [],
    })
    per_platform_rows = {}

    for platform in platforms:
        resp = (
            client.table("listings")
            .select("url, platform, extras")
            .eq("platform", platform)
            .not_.is_("extras", "null")
            .order("scraped_at", desc=True)
            .limit(args.limit)
            .execute()
        )
        rows = resp.data or []
        per_platform_rows[platform] = len(rows)
        for row in rows:
            extras = row.get("extras")
            if not extras:
                continue
            flat = flatten(extras, max_depth=args.max_depth)
            for key, values in flat.items():
                s = stats[key]
                s["count"] += 1
                s["platforms"].add(platform)
                for v in values:
                    s["types"].add(python_type(v))
                    if len(s["examples"]) < 3:
                        sv = json.dumps(v, ensure_ascii=False)
                        if len(sv) > 80:
                            sv = sv[:77] + "..."
                        if sv not in s["examples"]:
                            s["examples"].append(sv)

    print(f"Sampled rows: { {p: n for p, n in per_platform_rows.items()} }\n")

    ranked = sorted(stats.items(), key=lambda kv: -kv[1]["count"])
    print(f"{'key':<50} {'count':>6} {'platforms':<20} {'types':<20} examples")
    print("-" * 140)
    for key, s in ranked:
        print(
            f"{key:<50} {s['count']:>6} "
            f"{','.join(sorted(s['platforms'])):<20} "
            f"{','.join(sorted(s['types'])):<20} "
            f"{s['examples']}"
        )

    out_path = "scripts/extras_key_report.json"
    with open(out_path, "w") as f:
        json.dump(
            {
                "sampled_rows": per_platform_rows,
                "keys": {
                    key: {
                        "count": s["count"],
                        "platforms": sorted(s["platforms"]),
                        "types": sorted(s["types"]),
                        "examples": s["examples"],
                    }
                    for key, s in ranked
                },
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
