"""
call_ollama must never hit a live Ollama server in the test suite —
requests.post is always mocked here, per the repo's convention that LLM
calls are always mocked in unit tests (tests/agent/ note in MIGRATION_PLAN.md).
"""
import json
import unittest
from unittest.mock import MagicMock, patch

import requests
from pydantic import BaseModel

from benchmarks.llm.ollama_client import call_ollama


class _Widget(BaseModel):
    name: str
    count: int


def _mock_response(status_code=200, json_body=None, raises=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    if raises:
        resp.raise_for_status.side_effect = raises
    return resp


class CallOllamaTests(unittest.TestCase):
    @patch("benchmarks.llm.ollama_client.requests.post")
    def test_valid_structured_response_is_parsed(self, mock_post):
        mock_post.return_value = _mock_response(json_body={
            "message": {"content": json.dumps({"name": "widget", "count": 3})},
            "prompt_eval_count": 42,
            "eval_count": 7,
        })

        result = call_ollama("fake-model", "system", "user", _Widget)

        self.assertIsNone(result.error)
        self.assertEqual(result.parsed, _Widget(name="widget", count=3))
        self.assertEqual(result.prompt_tokens, 42)
        self.assertEqual(result.completion_tokens, 7)
        self.assertGreaterEqual(result.latency_seconds, 0)

    @patch("benchmarks.llm.ollama_client.requests.post")
    def test_invalid_json_content_yields_error_and_no_parsed_result(self, mock_post):
        mock_post.return_value = _mock_response(json_body={
            "message": {"content": "not valid json at all"},
            "prompt_eval_count": 10,
            "eval_count": 2,
        })

        result = call_ollama("fake-model", "system", "user", _Widget)

        self.assertIsNone(result.parsed)
        self.assertIsNotNone(result.error)

    @patch("benchmarks.llm.ollama_client.requests.post")
    def test_missing_required_field_yields_error_and_no_parsed_result(self, mock_post):
        mock_post.return_value = _mock_response(json_body={
            "message": {"content": json.dumps({"name": "widget"})},  # missing "count"
        })

        result = call_ollama("fake-model", "system", "user", _Widget)

        self.assertIsNone(result.parsed)
        self.assertIsNotNone(result.error)

    @patch("benchmarks.llm.ollama_client.requests.post")
    def test_connection_error_is_captured_not_raised(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("connection refused")

        result = call_ollama("fake-model", "system", "user", _Widget)

        self.assertIsNone(result.parsed)
        self.assertIn("request failed", result.error)

    @patch("benchmarks.llm.ollama_client.requests.post")
    def test_http_error_status_is_captured_not_raised(self, mock_post):
        mock_post.return_value = _mock_response(
            status_code=500, raises=requests.HTTPError("server error")
        )

        result = call_ollama("fake-model", "system", "user", _Widget)

        self.assertIsNone(result.parsed)
        self.assertIn("request failed", result.error)

    @patch("benchmarks.llm.ollama_client.requests.post")
    def test_transient_5xx_is_retried_once_and_succeeds(self, mock_post):
        server_error = requests.HTTPError("server error")
        server_error.response = MagicMock(status_code=500)
        failing_resp = _mock_response(status_code=500, raises=server_error)
        succeeding_resp = _mock_response(json_body={
            "message": {"content": json.dumps({"name": "widget", "count": 5})},
        })
        mock_post.side_effect = [failing_resp, succeeding_resp]

        result = call_ollama("fake-model", "system", "user", _Widget)

        self.assertEqual(mock_post.call_count, 2)
        self.assertIsNone(result.error)
        self.assertEqual(result.parsed, _Widget(name="widget", count=5))

    @patch("benchmarks.llm.ollama_client.requests.post")
    def test_connection_error_is_not_retried(self, mock_post):
        # A single side_effect item — a second call attempt would raise
        # StopIteration and fail the test, proving no retry happened for a
        # non-5xx failure.
        mock_post.side_effect = [requests.ConnectionError("connection refused")]

        result = call_ollama("fake-model", "system", "user", _Widget)

        self.assertEqual(mock_post.call_count, 1)
        self.assertIsNone(result.parsed)
        self.assertIn("request failed", result.error)

    @patch("benchmarks.llm.ollama_client.requests.post")
    def test_default_payload_disables_thinking_and_pins_zero_temperature(self, mock_post):
        mock_post.return_value = _mock_response(json_body={
            "message": {"content": json.dumps({"name": "widget", "count": 1})},
        })

        call_ollama("fake-model", "system", "user", _Widget)

        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["think"], False)
        self.assertEqual(sent_payload["options"]["temperature"], 0.0)

    @patch("benchmarks.llm.ollama_client.requests.post")
    def test_think_and_temperature_are_overridable(self, mock_post):
        mock_post.return_value = _mock_response(json_body={
            "message": {"content": json.dumps({"name": "widget", "count": 1})},
        })

        call_ollama("fake-model", "system", "user", _Widget, temperature=0.7, think=True)

        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["think"], True)
        self.assertEqual(sent_payload["options"]["temperature"], 0.7)


if __name__ == "__main__":
    unittest.main()
