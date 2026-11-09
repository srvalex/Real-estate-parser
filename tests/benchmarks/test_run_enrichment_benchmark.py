"""
The benchmark runner's own logic — task wiring, sample loading, and the
prediction capture the post-run analysis reads — exercised with
call_ollama patched. No Ollama server is ever contacted here, per the
repo's convention that LLM calls are always mocked in unit tests.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.llm.enrichment_schema import CanonicalFill, EnrichmentResult
from benchmarks.llm.ollama_client import OllamaResult
from benchmarks.run_enrichment_benchmark import TASKS, load_samples, run_task, write_predictions

_ENRICHMENT = {"own_heating": "yes", "parking_available": "yes",
               "pets_allowed": "no", "renovation_status": "unknown"}
_CANONICAL = {"rooms": "2", "area_sqm": 50.0, "floor": "3",
              "total_floors": None, "year_built": None}


def _sample(url="https://olx.ro/x", **overrides):
    row = {"url": url, "title": "t", "description": "d",
           "expected": _ENRICHMENT, "expected_canonical": _CANONICAL}
    row.update(overrides)
    return row


def _ok(parsed):
    return OllamaResult(parsed=parsed, raw_content="{}", latency_seconds=1.5,
                        prompt_tokens=400, completion_tokens=40, error=None)


def _failed(error="schema validation failed"):
    return OllamaResult(parsed=None, raw_content="oops", latency_seconds=0.5,
                        prompt_tokens=400, completion_tokens=0, error=error)


def _write_jsonl(rows, directory):
    path = os.path.join(directory, "samples.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return path


class LoadSamplesTests(unittest.TestCase):
    def test_skips_rows_not_labeled_for_the_running_task(self):
        """A dataset can be labeled for one task and not the other — those
        rows must be skipped, not scored against a null label."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_jsonl([
                _sample("a"),
                _sample("b", expected_canonical=None),
            ], tmp)
            self.assertEqual(len(load_samples(path, "expected")), 2)
            self.assertEqual([r["url"] for r in load_samples(path, "expected_canonical")], ["a"])

    def test_ignores_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(_sample()) + "\n\n")
            self.assertEqual(len(load_samples(path, "expected")), 1)


class RunTaskTests(unittest.TestCase):
    def test_scores_a_perfect_model_at_full_accuracy(self):
        with patch("benchmarks.run_enrichment_benchmark.call_ollama",
                   return_value=_ok(EnrichmentResult.model_validate(_ENRICHMENT))):
            results = run_task(TASKS["enrichment"], ["m"], [_sample()])
        self.assertEqual(results[0].field_accuracy["overall"], 1.0)
        self.assertEqual(results[0].n_errors, 0)

    def test_canonical_task_sends_its_own_prompt_and_schema(self):
        """The two tasks must not share a prompt/schema — that mix-up would
        still 'work' and quietly score the wrong thing."""
        task = TASKS["canonical"]
        with patch("benchmarks.run_enrichment_benchmark.call_ollama",
                   return_value=_ok(CanonicalFill.model_validate(_CANONICAL))) as mock:
            run_task(task, ["m"], [_sample()])
        _model, system_prompt, _user, schema = mock.call_args.args
        self.assertIs(schema, CanonicalFill)
        self.assertIn("square metres", system_prompt)

    def test_a_failed_call_counts_as_an_error_and_does_not_score(self):
        with patch("benchmarks.run_enrichment_benchmark.call_ollama", return_value=_failed()):
            results = run_task(TASKS["enrichment"], ["m"], [_sample()])
        self.assertEqual(results[0].n_errors, 1)
        self.assertEqual(results[0].field_accuracy, {"overall": 0.0})

    def test_a_failed_call_still_contributes_its_latency(self):
        """A model that times out is not thereby 'fast' — dropping failed
        calls from the latency sample would flatter exactly the worst case."""
        with patch("benchmarks.run_enrichment_benchmark.call_ollama", return_value=_failed()):
            results = run_task(TASKS["enrichment"], ["m"], [_sample()])
        self.assertEqual(results[0].latencies_seconds, [0.5])

    def test_every_model_is_scored_over_every_sample(self):
        with patch("benchmarks.run_enrichment_benchmark.call_ollama",
                   return_value=_ok(EnrichmentResult.model_validate(_ENRICHMENT))) as mock:
            results = run_task(TASKS["enrichment"], ["m1", "m2"], [_sample("a"), _sample("b")])
        self.assertEqual(mock.call_count, 4)
        self.assertEqual([r.n_samples for r in results], [2, 2])

    def test_records_one_prediction_per_call_with_expected_and_actual(self):
        wrong = EnrichmentResult.model_validate({**_ENRICHMENT, "pets_allowed": "yes"})
        predictions: list[dict] = []
        with patch("benchmarks.run_enrichment_benchmark.call_ollama", return_value=_ok(wrong)):
            run_task(TASKS["enrichment"], ["m"], [_sample()], predictions)
        self.assertEqual(len(predictions), 1)
        row = predictions[0]
        self.assertEqual(row["expected"]["pets_allowed"], "no")
        self.assertEqual(row["actual"]["pets_allowed"], "yes")
        self.assertFalse(row["scores"]["pets_allowed"])

    def test_records_a_prediction_for_a_failed_call_too(self):
        predictions: list[dict] = []
        with patch("benchmarks.run_enrichment_benchmark.call_ollama", return_value=_failed("boom")):
            run_task(TASKS["enrichment"], ["m"], [_sample()], predictions)
        self.assertEqual(len(predictions), 1)
        self.assertIsNone(predictions[0]["actual"])
        self.assertEqual(predictions[0]["error"], "boom")


class WritePredictionsTests(unittest.TestCase):
    def test_writes_one_json_object_per_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.jsonl")
            write_predictions([{"url": "a"}, {"url": "b"}], path)
            with open(path, encoding="utf-8") as f:
                rows = [json.loads(line) for line in f]
        self.assertEqual([r["url"] for r in rows], ["a", "b"])


class TaskTableTests(unittest.TestCase):
    def test_each_task_reads_a_distinct_label_column_and_report_path(self):
        label_keys = {t.label_key for t in TASKS.values()}
        report_paths = {t.report_path for t in TASKS.values()}
        self.assertEqual(len(label_keys), len(TASKS))
        self.assertEqual(len(report_paths), len(TASKS))


if __name__ == "__main__":
    unittest.main()


class PostprocessTests(unittest.TestCase):
    """The canonical task scores the *guarded* value — what would actually
    be written — while keeping the model's raw answer in the predictions
    so the guard's effect stays visible."""

    def _junk_fill(self):
        return CanonicalFill(rooms="2", area_sqm=50.0, floor="3",
                             total_floors=None, year_built="bloc nou")

    def test_scores_the_sanitized_value_not_the_raw_one(self):
        predictions: list[dict] = []
        with patch("benchmarks.run_enrichment_benchmark.call_ollama",
                   return_value=_ok(self._junk_fill())):
            results = run_task(TASKS["canonical"], ["m"], [_sample()], predictions)
        # gold year_built is None; "bloc nou" is guarded away, so it matches
        self.assertTrue(predictions[0]["scores"]["year_built"])
        self.assertEqual(results[0].field_accuracy["overall"], 1.0)

    def test_keeps_the_raw_model_answer_alongside_the_guarded_one(self):
        predictions: list[dict] = []
        with patch("benchmarks.run_enrichment_benchmark.call_ollama",
                   return_value=_ok(self._junk_fill())):
            run_task(TASKS["canonical"], ["m"], [_sample()], predictions)
        self.assertEqual(predictions[0]["actual_raw"]["year_built"], "bloc nou")
        self.assertIsNone(predictions[0]["actual"]["year_built"])

    def test_enrichment_task_has_no_postprocess_and_is_scored_as_returned(self):
        self.assertIsNone(TASKS["enrichment"].postprocess)
