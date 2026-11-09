"""
benchmarks/run_enrichment_benchmark.py
─────────────────────────────────────────
Benchmarks candidate Ollama models on the two offline extraction tasks a
listing's title + description supports:

  - `enrichment` — the v1 ENRICHMENT_PLAN.md fields (`EnrichmentResult`).
  - `canonical`  — canonical `listings` columns the scraper left blank
                   (`CanonicalFill`).

They are scored as separate tasks, each with its own prompt and schema,
rather than one merged call: the two have different failure modes (an
invented enum value vs. an invented number), different value to the
product, and merging them would make a model that is good at one and bad
at the other unreadable in the results.

Scores against a labeled JSONL dataset — `benchmarks/data/olx_validation_set.jsonl`
by default (200 hand-labeled OLX listings; see benchmarks/LABELING_GUIDE.md).
Rows whose label for the running task is null are skipped as not-yet-labeled.

Run from the project root:
    python benchmarks/run_enrichment_benchmark.py
    python benchmarks/run_enrichment_benchmark.py --task canonical
    python benchmarks/run_enrichment_benchmark.py --models qwen3:14b,phi4:14b --task both
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Callable, Type

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import BaseModel

from benchmarks.llm.enrichment_schema import (
    CANONICAL_FILL_SYSTEM_PROMPT,
    ENRICHMENT_SYSTEM_PROMPT,
    CanonicalFill,
    EnrichmentResult,
    sanitize_canonical_fill,
)
from benchmarks.llm.ollama_client import call_ollama
from benchmarks.llm.scoring import aggregate_accuracy, score_canonical_fill, score_enrichment
from benchmarks.report import BenchmarkModelResult, render_report

DEFAULT_MODELS = ["qwen3:14b", "phi4:14b"]
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SAMPLES_PATH = os.path.join(DATA_DIR, "olx_validation_set.jsonl")


@dataclass(frozen=True)
class Task:
    """One extraction task: which label column it is scored against, which
    prompt/schema produce it, and how a result is scored."""

    name: str
    label_key: str
    system_prompt: str
    schema: Type[BaseModel]
    score: Callable[[BaseModel, BaseModel], dict[str, bool]]
    report_title: str
    # Measured and reported, but kept out of the headline "overall" that
    # models are ranked on — see scoring.aggregate_accuracy.
    secondary_fields: frozenset[str] = frozenset()
    # Applied to the model's parsed output before scoring, when the writer
    # that would consume it applies the same guard. Scoring the guarded
    # value is what makes the number mean "what would land in the DB"
    # rather than "what the model said"; predictions keep both.
    postprocess: Callable[[BaseModel], BaseModel] | None = None

    @property
    def report_path(self) -> str:
        return os.path.join(DATA_DIR, f"{self.name}_report.md")

    @property
    def predictions_path(self) -> str:
        return os.path.join(DATA_DIR, f"{self.name}_predictions.jsonl")


TASKS = {
    "enrichment": Task(
        name="enrichment",
        label_key="expected",
        system_prompt=ENRICHMENT_SYSTEM_PROMPT,
        schema=EnrichmentResult,
        score=score_enrichment,
        report_title="Description enrichment",
    ),
    "canonical": Task(
        name="canonical",
        label_key="expected_canonical",
        system_prompt=CANONICAL_FILL_SYSTEM_PROMPT,
        schema=CanonicalFill,
        score=score_canonical_fill,
        report_title="Canonical column fill",
        postprocess=sanitize_canonical_fill,
    ),
}


def load_samples(path: str, label_key: str) -> list[dict]:
    samples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get(label_key) is None:
                continue  # not yet labeled for this task — skip
            samples.append(row)
    return samples


def run_task(
    task: Task,
    models: list[str],
    samples: list[dict],
    predictions: list[dict] | None = None,
) -> list[BenchmarkModelResult]:
    """Score every model on every sample. When `predictions` is given, each
    call's raw output and per-field scores are appended to it — the report
    alone says which model won, not *where* it lost, and a re-run costs
    another hour of local inference to find out."""
    results = []
    for model in models:
        print(f"\n=== {task.name} / {model} ===")
        field_scores = []
        latencies = []
        prompt_tokens = []
        completion_tokens = []
        n_errors = 0

        for i, sample in enumerate(samples, 1):
            expected = task.schema.model_validate(sample[task.label_key])
            user_content = f"Title: {sample['title']}\nDescription: {sample['description']}"
            result = call_ollama(model, task.system_prompt, user_content, task.schema)
            latencies.append(result.latency_seconds)
            prompt_tokens.append(result.prompt_tokens)
            completion_tokens.append(result.completion_tokens)

            if result.parsed is None:
                n_errors += 1
                print(f"  [{i}/{len(samples)}] ERROR: {result.error}")
                if predictions is not None:
                    predictions.append({
                        "task": task.name,
                        "model": model,
                        "url": sample["url"],
                        "title": sample.get("title", ""),
                        "description": sample.get("description", ""),
                        "expected": expected.model_dump(),
                        "actual": None,
                        "scores": None,
                        "error": result.error,
                        "latency_seconds": result.latency_seconds,
                    })
                continue

            raw = result.parsed
            parsed = task.postprocess(raw) if task.postprocess else raw
            scores = task.score(expected, parsed)
            field_scores.append(scores)
            if predictions is not None:
                predictions.append({
                    "task": task.name,
                    "model": model,
                    "url": sample["url"],
                    "title": sample.get("title", ""),
                    "description": sample.get("description", ""),
                    "expected": expected.model_dump(),
                    "actual": parsed.model_dump(),
                    "actual_raw": raw.model_dump(),
                    "scores": scores,
                    "latency_seconds": result.latency_seconds,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                })
            print(
                f"  [{i}/{len(samples)}] field match: {sum(scores.values())}/{len(scores)}"
                f"  ({result.latency_seconds:.2f}s)"
            )

        accuracy = (
            aggregate_accuracy(field_scores, task.secondary_fields)
            if field_scores else {"overall": 0.0}
        )
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


def write_predictions(predictions: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in predictions:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Saved {len(predictions)} predictions to {path}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark Ollama models on offline extraction")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS),
                        help="Comma-separated Ollama model tags")
    parser.add_argument("--task", default="both", choices=[*TASKS, "both"])
    parser.add_argument("--samples", default=SAMPLES_PATH)
    parser.add_argument("--limit", type=int, default=None,
                        help="Score only the first N labeled samples (smoke runs)")
    parser.add_argument("--output", default=None,
                        help="Markdown report path (single-task runs only; "
                             "'both' writes one report per task)")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    task_names = list(TASKS) if args.task == "both" else [args.task]
    if args.output and len(task_names) > 1:
        parser.error("--output cannot be combined with --task both (two reports are written)")

    for name in task_names:
        task = TASKS[name]
        samples = load_samples(args.samples, task.label_key)[: args.limit]
        if not samples:
            print(
                f'No labeled samples for task {name!r} in {args.samples} — '
                f'fill in "{task.label_key}" for at least one row first.'
            )
            continue
        predictions: list[dict] = []
        results = run_task(task, models, samples, predictions)
        render_report(task.report_title, results, args.output or task.report_path)
        write_predictions(predictions, task.predictions_path)


if __name__ == "__main__":
    main()
