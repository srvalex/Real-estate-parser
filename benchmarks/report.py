"""
benchmarks/report.py
──────────────────────
Shared result type and console/markdown table renderer for both benchmark
runners (run_enrichment_benchmark.py, run_filter_benchmark.py).
"""

from __future__ import annotations

import os
import statistics
from dataclasses import dataclass

from benchmarks.llm.cost_estimates import estimate_cost


@dataclass
class BenchmarkModelResult:
    model: str
    field_accuracy: dict[str, float]  # from scoring.aggregate_accuracy — includes "overall"
    latencies_seconds: list[float]
    avg_prompt_tokens: float
    avg_completion_tokens: float
    n_samples: int
    n_errors: int


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(len(ordered) * pct), len(ordered) - 1)
    return ordered[idx]


def render_report(
    task_name: str,
    results: list[BenchmarkModelResult],
    output_md_path: str | None = None,
) -> str:
    lines = [
        f"# {task_name} benchmark",
        "",
        "| Model | Accuracy | Median latency | p95 latency | Avg tokens in/out | Errors | Est. hosted cost / 1k calls |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        overall = r.field_accuracy.get("overall", 0.0)
        median_lat = statistics.median(r.latencies_seconds) if r.latencies_seconds else 0.0
        p95_lat = _percentile(r.latencies_seconds, 0.95)
        cost = estimate_cost(r.model, r.avg_prompt_tokens, r.avg_completion_tokens, 1000)
        cost_str = f"${cost:,.2f}" if cost is not None else "n/a"
        lines.append(
            f"| {r.model} | {overall:.1%} | {median_lat:.2f}s | {p95_lat:.2f}s | "
            f"{r.avg_prompt_tokens:.0f} / {r.avg_completion_tokens:.0f} | "
            f"{r.n_errors}/{r.n_samples} | {cost_str} |"
        )

    lines.append("")
    lines.append("## Per-field accuracy")
    for r in results:
        lines.append(f"\n**{r.model}**")
        for field_name, acc in sorted(r.field_accuracy.items()):
            if field_name == "overall":
                continue
            lines.append(f"- {field_name}: {acc:.1%}")

    report_text = "\n".join(lines)
    print("\n" + report_text)

    if output_md_path:
        os.makedirs(os.path.dirname(output_md_path), exist_ok=True)
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(report_text + "\n")
        print(f"\nSaved report to {output_md_path}")

    return report_text
