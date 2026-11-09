"""
benchmarks/cost_analysis.py
───────────────────────────
What this workload would cost on the OpenAI API, measured rather than
guessed: token counts come from tiktoken over the *real* corpora — the 200
hand-labeled OLX listings for the offline backfill, and the filter-benchmark
prompt set for the interactive path — not from a rule of thumb.

Two analyses, because they are different decisions:

  1. **Backfill** — one pass over the whole active dataset (~10-15k rows),
     offline, latency-irrelevant, so Batch API pricing applies.
  2. **Per user prompt** — the interactive text-to-SQL path
     (`query_model.py` / MIGRATION_PLAN.md Phase 5), where the user is
     waiting, so neither Batch nor a slow local model is an option, and
     the cost is per search rather than one-off.

Counting notes, since they move the answer more than the model choice does:
  - The JSON schema sent for structured output is billed as input tokens,
    so it is counted here (it is 255-760 tokens depending on the task —
    more than the system prompt in two of the three cases).
  - Output token counts are the *actual* JSON the benchmarked local model
    produced, re-tokenized with OpenAI's tokenizer; they are not estimates.
  - Prompt caching is only applied where the prompt clears OpenAI's
    minimum length (see cost_estimates.CACHE_MINIMUM_PROMPT_TOKENS).

Run from the project root:
    python benchmarks/cost_analysis.py
"""

import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.llm.cost_estimates import (
    BATCH_DISCOUNT,
    CACHE_MINIMUM_PROMPT_TOKENS,
    OPENAI_PRICE_PER_MILLION_TOKENS,
    openai_cost,
)
from benchmarks.llm.enrichment_schema import (
    CANONICAL_FILL_SYSTEM_PROMPT,
    ENRICHMENT_SYSTEM_PROMPT,
    CanonicalFill,
    EnrichmentResult,
)
from benchmarks.run_filter_benchmark import SYSTEM_PROMPT as FILTER_SYSTEM_PROMPT
from query_model import ListingQuery

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
REPORT_PATH = os.path.join(DATA_DIR, "openai_cost_analysis.md")

BACKFILL_SIZES = (10_000, 12_500, 15_000)
SEARCH_VOLUMES = (1_000, 10_000, 100_000)
MODELS = tuple(OPENAI_PRICE_PER_MILLION_TOKENS)


def get_token_counter():
    """tiktoken encoder for the GPT-5 family, as a plain str -> int."""
    import tiktoken

    encoding = tiktoken.get_encoding("o200k_base")
    return lambda text: len(encoding.encode(text))


def schema_tokens(schema, count) -> int:
    return count(json.dumps(schema.model_json_schema()))


def measure_task(system_prompt, schema, user_contents, outputs, count) -> dict:
    """Per-call token profile for one task, over its real corpus.

    `static_input_tokens` (system prompt + schema) is reported separately
    because it is identical on every call — it is the part a prompt cache
    could serve, and the part a merged two-task call would pay once
    instead of twice.
    """
    static = count(system_prompt) + schema_tokens(schema, count)
    variable = [count(text) for text in user_contents]
    output = [count(text) for text in outputs]
    return {
        "static_input_tokens": static,
        "mean_variable_input_tokens": statistics.mean(variable),
        "mean_input_tokens": static + statistics.mean(variable),
        "median_input_tokens": static + statistics.median(variable),
        "max_input_tokens": static + max(variable),
        "mean_output_tokens": statistics.mean(output),
        "n_samples": len(variable),
    }


def _load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def measure_backfill_tasks(count) -> dict[str, dict]:
    listings = _load_jsonl(os.path.join(DATA_DIR, "olx_validation_set.jsonl"))
    user_contents = [f"Title: {r['title']}\nDescription: {r['description']}" for r in listings]

    profiles = {}
    for name, prompt, schema in (
        ("enrichment", ENRICHMENT_SYSTEM_PROMPT, EnrichmentResult),
        ("canonical", CANONICAL_FILL_SYSTEM_PROMPT, CanonicalFill),
    ):
        predictions = _load_jsonl(os.path.join(DATA_DIR, f"{name}_predictions.jsonl"))
        outputs = [json.dumps(p["actual"], ensure_ascii=False)
                   for p in predictions if p.get("actual")]
        profiles[name] = measure_task(prompt, schema, user_contents, outputs, count)
    return profiles


def measure_search_task(count) -> dict:
    samples = _load_jsonl(os.path.join(DATA_DIR, "filter_extraction_samples.jsonl"))
    # No recorded hosted-model outputs for this task, so the labeled
    # expected query stands in — it is the exact JSON a correct answer
    # would emit, which is what the output charge is levied on.
    outputs = [ListingQuery.model_validate(s["expected"]).model_dump_json() for s in samples]
    return measure_task(FILTER_SYSTEM_PROMPT, ListingQuery,
                        [s["prompt"] for s in samples], outputs, count)


def render(backfill: dict[str, dict], search: dict) -> str:
    per_listing_in = sum(p["mean_input_tokens"] for p in backfill.values())
    per_listing_out = sum(p["mean_output_tokens"] for p in backfill.values())

    lines = [
        "# OpenAI cost analysis",
        "",
        "Token counts measured with tiktoken (`o200k_base`) over the real "
        "corpora — the 200-listing validation set and the filter-benchmark "
        "prompt set. Prices are the 2026-09-06 snapshot in "
        "`benchmarks/llm/cost_estimates.py`; re-check before committing spend.",
        "",
        "## 1. Offline backfill of the active dataset",
        "",
        "Two calls per listing (enrichment + canonical fill), matching how "
        "the benchmark actually ran.",
        "",
        "| task | static input (prompt+schema) | mean listing text | mean input | mean output |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, p in backfill.items():
        lines.append(
            f"| {name} | {p['static_input_tokens']:.0f} | "
            f"{p['mean_variable_input_tokens']:.0f} | {p['mean_input_tokens']:.0f} | "
            f"{p['mean_output_tokens']:.0f} |"
        )
    lines += [
        f"| **per listing (both)** | | | **{per_listing_in:.0f}** | **{per_listing_out:.0f}** |",
        "",
        f"Both prompts sit under the {CACHE_MINIMUM_PROMPT_TOKENS}-token cache "
        "minimum, so no cached-input discount applies. Batch API "
        f"({BATCH_DISCOUNT:.0%} of standard) does — the backfill is offline by "
        "definition.",
        "",
        "| model | " + " | ".join(f"{n:,} listings" for n in BACKFILL_SIZES) + " | batch (12,500) |",
        "|---|" + "---:|" * (len(BACKFILL_SIZES) + 1),
    ]
    for model in MODELS:
        costs = [openai_cost(model, per_listing_in, per_listing_out, n) for n in BACKFILL_SIZES]
        batched = openai_cost(model, per_listing_in, per_listing_out, 12_500, batch=True)
        lines.append(
            f"| {model} | " + " | ".join(f"${c:,.2f}" for c in costs) + f" | ${batched:,.2f} |"
        )

    cached = search["static_input_tokens"]
    lines += [
        "",
        "## 2. Per user prompt (interactive text-to-SQL)",
        "",
        f"One call per search. Mean input {search['mean_input_tokens']:.0f} tokens "
        f"({cached:.0f} of them the fixed system prompt + schema, "
        f"{search['mean_variable_input_tokens']:.0f} the user's own words), mean "
        f"output {search['mean_output_tokens']:.0f} tokens, measured over "
        f"{search['n_samples']} real sample prompts.",
        "",
        f"This prompt *does* clear the {CACHE_MINIMUM_PROMPT_TOKENS}-token cache "
        "minimum, so the cached column below assumes the fixed prefix is served "
        "from cache — true only under sustained traffic, since the cache expires "
        "after minutes of inactivity. Batch pricing does not apply: the user is "
        "waiting.",
        "",
        "| model | per search | per 1k searches | " +
        " | ".join(f"{n:,}/mo" for n in SEARCH_VOLUMES) + " | per 1k (cached prefix) |",
        "|---|---:|---:|" + "---:|" * (len(SEARCH_VOLUMES) + 1),
    ]
    for model in MODELS:
        per_call = openai_cost(model, search["mean_input_tokens"], search["mean_output_tokens"])
        volumes = [per_call * n for n in SEARCH_VOLUMES]
        cached_per_1k = openai_cost(
            model, search["mean_input_tokens"], search["mean_output_tokens"],
            1_000, cached_input_tokens=cached,
        )
        lines.append(
            f"| {model} | ${per_call:.6f} | ${per_call * 1000:,.2f} | "
            + " | ".join(f"${c:,.2f}" for c in volumes)
            + f" | ${cached_per_1k:,.2f} |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Estimate OpenAI cost for both extraction paths")
    parser.add_argument("--output", default=REPORT_PATH)
    args = parser.parse_args()

    count = get_token_counter()
    report = render(measure_backfill_tasks(count), measure_search_task(count))
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
