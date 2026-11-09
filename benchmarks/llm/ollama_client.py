"""
benchmarks/llm/ollama_client.py
─────────────────────────────────
Thin wrapper over Ollama's local REST API (http://localhost:11434) for the
model benchmark harness. No new pip dependency — uses `requests`, already
a project dependency (requirements.txt).

Uses Ollama's structured-output support: passing a JSON schema as `format`
constrains the model's response to that schema (Ollama >= 0.5). A model
that still returns malformed JSON is recorded as a failure via `.error`,
never raised, so one bad call doesn't abort a benchmark sweep.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Type, TypeVar

import requests
from pydantic import BaseModel, ValidationError

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_TIMEOUT_SECONDS = 120

T = TypeVar("T", bound=BaseModel)


@dataclass
class OllamaResult:
    parsed: BaseModel | None
    raw_content: str
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    error: str | None


def _is_transient_server_error(exc: requests.RequestException) -> bool:
    return (
        isinstance(exc, requests.HTTPError)
        and exc.response is not None
        and 500 <= exc.response.status_code < 600
    )


def call_ollama(
    model: str,
    system_prompt: str,
    user_content: str,
    schema: Type[T],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    base_url: str = OLLAMA_BASE_URL,
    temperature: float = 0.0,
    think: bool = False,
    max_retries: int = 1,
) -> OllamaResult:
    """Call a local Ollama model with a structured-output schema, and time it.

    Never raises for model/network failure — timeouts, connection errors,
    and invalid-JSON responses all come back as an OllamaResult with
    `.error` set and `.parsed is None`, so a benchmark sweep over many
    samples/models can keep going past a single failure.

    `temperature=0` by default for reproducible benchmark runs — sampling
    noise otherwise means the same prompt can pass on one run and fail
    schema validation on the next. `think=False` by default: hybrid
    reasoning models (e.g. Qwen3) default to emitting a long chain-of-thought
    even under a structured-output schema, which is both slow (observed
    >120s timeouts on qwen3:4b with thinking on) and not representative of
    the fast/cheap production path this harness is evaluating for.

    A 5xx from Ollama (observed on the first call right after a cold model
    switch) is retried once by default — it's infrastructure noise, not a
    model-quality signal the benchmark should count as an error.
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "format": schema.model_json_schema(),
        "stream": False,
        "think": think,
        "options": {"temperature": temperature},
    }

    start = time.monotonic()
    body = None
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(f"{base_url}/api/chat", json=payload, timeout=timeout)
            resp.raise_for_status()
            body = resp.json()
            last_error = None
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt < max_retries and _is_transient_server_error(exc):
                continue
            break

    if last_error is not None:
        return OllamaResult(
            parsed=None,
            raw_content="",
            latency_seconds=time.monotonic() - start,
            prompt_tokens=0,
            completion_tokens=0,
            error=f"request failed: {last_error}",
        )

    latency = time.monotonic() - start
    raw_content = (body.get("message") or {}).get("content", "")
    prompt_tokens = body.get("prompt_eval_count", 0) or 0
    completion_tokens = body.get("eval_count", 0) or 0

    try:
        parsed = schema.model_validate_json(raw_content)
        error = None
    except ValidationError as exc:
        parsed = None
        error = f"schema validation failed: {exc}"

    return OllamaResult(
        parsed=parsed,
        raw_content=raw_content,
        latency_seconds=latency,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        error=error,
    )
