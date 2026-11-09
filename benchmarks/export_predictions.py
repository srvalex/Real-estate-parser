"""
benchmarks/export_predictions.py
────────────────────────────────
Pivots a benchmark predictions dump (`<task>_predictions.jsonl`, written by
run_enrichment_benchmark.py) into one CSV per task: one row per listing,
with the hand label and every model's answer side by side.

The report says which model won; this says where each one lost, on which
listing, with the description right there — which is what you need to tell
a model error apart from a prompt-wording problem or a label you'd argue
with (the `gas`->`central` heating confusion was found this way).

Column layout per field: `expected_<field>`, then `<model>_<field>` for
each model. Then per model a `<model>_correct` count, plus `models_agree`
and `any_wrong` flags for filtering/sorting in a spreadsheet.

Pure file I/O, no DB and no model calls.

Run from the project root:
    python benchmarks/export_predictions.py
    python benchmarks/export_predictions.py --predictions benchmarks/data/canonical_predictions.jsonl
"""

import argparse
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def flatten(values: dict, prefix: str = "") -> dict:
    """One level of nesting is enough for both schemas — `parking` is the
    only nested object — and dotted keys keep the CSV header aligned with
    the field names the scorer and the reports already use."""
    out = {}
    for key, value in (values or {}).items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, f"{name}."))
        else:
            out[name] = value
    return out


def load_predictions(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def pivot(predictions: list[dict]) -> tuple[list[str], list[dict]]:
    """Group per-model prediction rows into one row per listing.

    Model order follows first appearance (i.e. the order they were
    benchmarked in), not sort order, so the CSV columns line up with how
    the run was invoked. Listing order is preserved for the same reason.
    """
    models: list[str] = []
    fields: list[str] = []
    by_url: dict[str, dict] = {}

    for row in predictions:
        model = row["model"]
        if model not in models:
            models.append(model)

        expected = flatten(row["expected"])
        for field in expected:
            if field not in fields:
                fields.append(field)

        listing = by_url.setdefault(row["url"], {
            "url": row["url"],
            "title": row.get("title", ""),
            "description": " ".join((row.get("description") or "").split()),
            "_expected": expected,
            "_actual": {},
            "_scores": {},
            "_error": {},
        })
        # A failed call has no parsed output — keep the row and record the
        # error, rather than dropping the listing from the comparison.
        listing["_actual"][model] = flatten(row.get("actual"))
        listing["_scores"][model] = row.get("scores") or {}
        listing["_error"][model] = row.get("error")

    header = ["url", "title", "description"]
    for field in fields:
        header.append(f"expected_{field}")
        header += [f"{model}_{field}" for model in models]
    for model in models:
        header.append(f"{model}_correct")
    header += ["models_agree", "any_wrong", "errors"]

    rows = []
    for listing in by_url.values():
        out = {k: listing[k] for k in ("url", "title", "description")}
        for field in fields:
            out[f"expected_{field}"] = listing["_expected"].get(field)
            for model in models:
                out[f"{model}_{field}"] = listing["_actual"].get(model, {}).get(field)
        for model in models:
            scores = listing["_scores"].get(model, {})
            out[f"{model}_correct"] = f"{sum(scores.values())}/{len(scores)}" if scores else ""
        answers = [json.dumps(listing["_actual"].get(m), sort_keys=True) for m in models]
        out["models_agree"] = len(set(answers)) == 1
        out["any_wrong"] = any(
            not ok for scores in listing["_scores"].values() for ok in scores.values()
        )
        out["errors"] = "; ".join(f"{m}: {e}" for m, e in listing["_error"].items() if e)
        rows.append(out)
    return header, rows


def write_csv(header: list[str], rows: list[dict], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Export benchmark predictions as CSV")
    parser.add_argument("--predictions", nargs="*",
                        default=sorted(glob.glob(os.path.join(DATA_DIR, "*_predictions.jsonl"))),
                        help="Predictions JSONL path(s); defaults to every one in benchmarks/data")
    args = parser.parse_args()

    if not args.predictions:
        print("No predictions files found — run benchmarks/run_enrichment_benchmark.py first.")
        return

    for path in args.predictions:
        header, rows = pivot(load_predictions(path))
        output_path = path.replace("_predictions.jsonl", "_predictions.csv")
        write_csv(header, rows, output_path)
        print(f"Wrote {len(rows)} listings to {output_path}")


if __name__ == "__main__":
    main()
