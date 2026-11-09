"""
benchmarks/llm/cost_estimates.py
──────────────────────────────────
Static hosted-API pricing reference for the local Ollama models this
benchmark tests, so a local run can extrapolate "what would this cost if
we hosted it instead of running it locally." NOT a live pricing lookup —
snapshot values, re-check against the provider before trusting for a real
hosting decision.

Prices are $ per 1M tokens, (input, output), sourced from OpenRouter /
DeepInfra listings as of 2026-09.
"""

from __future__ import annotations

# Ollama model tag -> ($/M input tokens, $/M output tokens) for the closest
# hosted equivalent. None means no confident hosted mapping is known yet.
HOSTED_PRICE_PER_MILLION_TOKENS: dict[str, tuple[float, float] | None] = {
    "qwen3:14b": (0.32, 1.28),      # Qwen3.8 Flash-tier pricing, closest public equivalent
    "phi4:14b": None,               # no major hosted API lists Phi-4 at time of writing
    "qwen3:4b": (0.32, 1.28),
    "llama3.2:3b": (0.075, 0.15),   # Llama 3.x small-model tier, low end of OpenRouter's range
}


def estimate_cost(
    model: str,
    avg_prompt_tokens: float,
    avg_completion_tokens: float,
    n_calls: int,
) -> float | None:
    """Estimated $ cost for `n_calls` hosted calls at this model's observed
    average token usage. Returns None if the model has no known hosted
    price mapping."""
    prices = HOSTED_PRICE_PER_MILLION_TOKENS.get(model)
    if prices is None:
        return None
    input_price, output_price = prices
    per_call_cost = (
        avg_prompt_tokens / 1_000_000 * input_price
        + avg_completion_tokens / 1_000_000 * output_price
    )
    return per_call_cost * n_calls


# ─────────────────────────────────────────────────────────────────────
# Hosted OpenAI pricing, $ per 1M tokens: (input, cached input, output).
# Snapshot taken 2026-09-06 from https://developers.openai.com/api/docs/pricing
# — same caveat as the table above: re-check before committing spend.
#
# Only the tiers worth considering for this workload are listed. The
# extraction tasks here are short, schema-constrained and offline; the
# flagship reasoning tiers (gpt-5.5-pro, gpt-6-astra) are 100-600x the
# price of gpt-5-nano for a job that two local 14B models already do at
# ~92-96% accuracy, so they are deliberately not in the comparison.
OPENAI_PRICE_PER_MILLION_TOKENS: dict[str, tuple[float, float, float]] = {
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5": (1.25, 0.125, 10.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
}

# The Batch API halves both input and output rates in exchange for an
# asynchronous (up to 24h) turnaround. That trade is free for the offline
# backfill — it already runs as a batch job — and unusable for the
# interactive query path, where the user is waiting.
BATCH_DISCOUNT = 0.5

# OpenAI only serves cached input above a minimum prompt length; shorter
# prompts are billed at the full input rate no matter how repetitive their
# prefix is. This is why the two extraction prompts here (~700-900 tokens
# with their schema) get no caching benefit while the user-facing filter
# prompt (~1.4k) does.
CACHE_MINIMUM_PROMPT_TOKENS = 1024


def openai_cost(
    model: str,
    input_tokens: float,
    output_tokens: float,
    n_calls: int = 1,
    cached_input_tokens: float = 0.0,
    batch: bool = False,
) -> float:
    """Estimated $ for `n_calls` OpenAI calls at the given per-call token
    counts. `cached_input_tokens` is the portion of `input_tokens` served
    from the prompt cache — pass 0 (the default) for an uncached estimate.

    Raises KeyError for an unlisted model rather than silently returning a
    number: a made-up price is worse than no price in a spend decision.
    """
    input_price, cached_price, output_price = OPENAI_PRICE_PER_MILLION_TOKENS[model]
    if cached_input_tokens > input_tokens:
        raise ValueError("cached_input_tokens cannot exceed input_tokens")
    fresh_input = input_tokens - cached_input_tokens
    per_call = (
        fresh_input / 1_000_000 * input_price
        + cached_input_tokens / 1_000_000 * cached_price
        + output_tokens / 1_000_000 * output_price
    )
    if batch:
        per_call *= BATCH_DISCOUNT
    return per_call * n_calls
