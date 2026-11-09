"""
benchmarks/run_filter_benchmark.py
────────────────────────────────────
Benchmarks candidate Ollama models on the runtime filter-extraction task:
turning a natural-language search prompt into a ListingQuery (query_model.py).
Scores against benchmarks/data/filter_extraction_samples.jsonl — hand-drafted
prompts + expected ListingQuery. Review/correct those before trusting the
numbers, per ENRICHMENT_PLAN.md's "don't tune or trust without measuring"
discipline.

Run from the project root:
    python benchmarks/run_filter_benchmark.py
    python benchmarks/run_filter_benchmark.py --models qwen3:4b,llama3.2:3b
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.llm.ollama_client import call_ollama
from benchmarks.llm.scoring import aggregate_accuracy, score_filter_query
from benchmarks.report import BenchmarkModelResult, render_report
from query_model import EXTRAS_REGISTRY, ListingQuery

DEFAULT_MODELS = ["qwen3:4b", "llama3.2:3b"]
SAMPLES_PATH = os.path.join(os.path.dirname(__file__), "data", "filter_extraction_samples.jsonl")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "data", "filter_extraction_report.md")


def _extras_doc() -> str:
    lines = []
    for key, spec in EXTRAS_REGISTRY.items():
        known = f" (known values: {', '.join(spec.known_values)})" if spec.known_values else ""
        lines.append(f"- {key} ({spec.value_type}): {spec.description}{known}")
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You translate a user's natural-language real estate search request (Romanian or English) into a structured ListingQuery.

Canonical fields: price_min/price_max (EUR), rooms (list of "1","2","3","4","5+"), area_min/area_max (sqm), district (list of Bucharest neighborhood names, in Romanian, as mentioned by the user), property_type (list of "Apartament","Garsoniera","Studio","Casa/Vila"), year_built_min, floor_min/floor_max, is_available (default true).

extras: a list of {{key, op, value}} filters restricted to these registered keys ONLY — never invent a key:
{_extras_doc()}

vibe_text: free-text fallback ONLY for descriptive intent that no other field above can express (e.g. "cozy", "recently renovated", "has parking" when parking isn't a registered extras key). Never restate information already captured by a canonical field or an extras filter — e.g. if price_max is set, do not also put "under X euros" in vibe_text; if district is set, do not also put the district name in vibe_text. Leave vibe_text null whenever every part of the request is already covered by other fields.

Only set a field if the user's request actually implies it. Leave everything else at its default (null / empty list / true for is_available). The extras list must ONLY contain a key when the request clearly and specifically supports it — never emit an entry for every registered key "just in case", and never use "null" or an empty string as a value; if nothing in the request maps to a registered extras key, extras must be an empty list. Respond with only the structured fields — no commentary."""


def load_samples(path: str) -> list[dict]:
    samples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            samples.append(json.loads(line))
    return samples


def run_benchmark(models: list[str], samples: list[dict]) -> list[BenchmarkModelResult]:
    results = []
    for model in models:
        print(f"\n=== {model} ===")
        field_scores = []
        latencies = []
        prompt_tokens = []
        completion_tokens = []
        n_errors = 0

        for i, sample in enumerate(samples, 1):
            expected = ListingQuery.model_validate(sample["expected"])
            result = call_ollama(model, SYSTEM_PROMPT, sample["prompt"], ListingQuery)
            latencies.append(result.latency_seconds)
            prompt_tokens.append(result.prompt_tokens)
            completion_tokens.append(result.completion_tokens)

            if result.parsed is None:
                n_errors += 1
                print(f"  [{i}/{len(samples)}] ERROR: {result.error}")
                continue

            scores = score_filter_query(expected, result.parsed)
            field_scores.append(scores)
            print(
                f"  [{i}/{len(samples)}] field match: {sum(scores.values())}/{len(scores)}"
                f"  ({result.latency_seconds:.2f}s)"
            )

        accuracy = aggregate_accuracy(field_scores) if field_scores else {"overall": 0.0}
        results.append(BenchmarkModelResult(
            model=model,
            field_accuracy=accuracy,
            latencies_seconds=latencies,
            avg_prompt_tokens=sum(prompt_tokens) / len(prompt_tokens) if prompt_tokens else 0,
            avg_completion_tokens=sum(completion_tokens) / len(completion_tokens) if completion_tokens else 0,
            n_samples=len(samples),
            n_errors=n_errors,
        ))
    return results


def main():
    parser = argparse.ArgumentParser(description="Benchmark Ollama models on filter extraction")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS),
                        help="Comma-separated Ollama model tags")
    parser.add_argument("--samples", default=SAMPLES_PATH)
    parser.add_argument("--output", default=REPORT_PATH)
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    samples = load_samples(args.samples)
    results = run_benchmark(models, samples)
    render_report("Filter extraction", results, args.output)


if __name__ == "__main__":
    main()
