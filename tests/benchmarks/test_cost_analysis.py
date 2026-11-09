"""
Cost math and token-profile measurement. `openai_cost` is pure arithmetic
over a price table; `measure_task` takes its token counter as an argument,
so these run with a trivial fake counter and never load tiktoken's BPE
files (which would make the suite depend on a network download).
"""
import unittest

from benchmarks.cost_analysis import measure_task, render, schema_tokens
from benchmarks.llm.cost_estimates import (
    BATCH_DISCOUNT,
    OPENAI_PRICE_PER_MILLION_TOKENS,
    openai_cost,
)
from benchmarks.llm.enrichment_schema import EnrichmentResult


def _count(text: str) -> int:
    """One 'token' per character — deterministic and easy to assert on."""
    return len(text)


class OpenAICostTests(unittest.TestCase):
    def test_prices_input_and_output_at_their_separate_rates(self):
        # gpt-5-mini: $0.25/M in, $2.00/M out
        cost = openai_cost("gpt-5-mini", input_tokens=1_000_000, output_tokens=1_000_000)
        self.assertAlmostEqual(cost, 2.25)

    def test_scales_linearly_with_call_count(self):
        one = openai_cost("gpt-5-nano", 1000, 100)
        self.assertAlmostEqual(openai_cost("gpt-5-nano", 1000, 100, 500), one * 500)

    def test_batch_applies_the_discount_to_the_whole_call(self):
        standard = openai_cost("gpt-5", 1000, 100, 10)
        self.assertAlmostEqual(openai_cost("gpt-5", 1000, 100, 10, batch=True),
                               standard * BATCH_DISCOUNT)

    def test_cached_input_is_billed_at_the_cached_rate(self):
        """The cached portion must come off the fresh-input charge, not be
        added on top of it — double-counting here would understate the
        saving and could flip a build-vs-buy call."""
        input_price, cached_price, _out = OPENAI_PRICE_PER_MILLION_TOKENS["gpt-5-mini"]
        cost = openai_cost("gpt-5-mini", input_tokens=1000, output_tokens=0,
                           cached_input_tokens=800)
        expected = (200 * input_price + 800 * cached_price) / 1_000_000
        self.assertAlmostEqual(cost, expected)

    def test_fully_cached_prompt_costs_the_cached_rate_throughout(self):
        _in, cached_price, _out = OPENAI_PRICE_PER_MILLION_TOKENS["gpt-5-nano"]
        cost = openai_cost("gpt-5-nano", 1000, 0, cached_input_tokens=1000)
        self.assertAlmostEqual(cost, 1000 * cached_price / 1_000_000)

    def test_cached_tokens_cannot_exceed_the_prompt(self):
        with self.assertRaises(ValueError):
            openai_cost("gpt-5-nano", 100, 0, cached_input_tokens=101)

    def test_unknown_model_raises_rather_than_guessing_a_price(self):
        with self.assertRaises(KeyError):
            openai_cost("some-model-we-have-not-priced", 1000, 100)

    def test_every_listed_model_has_cached_cheaper_than_fresh_input(self):
        for model, (fresh, cached, _out) in OPENAI_PRICE_PER_MILLION_TOKENS.items():
            self.assertLess(cached, fresh, model)


class MeasureTaskTests(unittest.TestCase):
    def test_static_input_counts_system_prompt_plus_schema(self):
        profile = measure_task("sys", EnrichmentResult, ["abc"], ["ab"], _count)
        self.assertEqual(profile["static_input_tokens"],
                         len("sys") + schema_tokens(EnrichmentResult, _count))

    def test_mean_input_includes_the_static_prefix_on_every_call(self):
        """A per-call estimate that forgets the fixed prefix understates
        the bill by more than the listing text costs."""
        profile = measure_task("sys", EnrichmentResult, ["a", "aaa"], ["x"], _count)
        self.assertEqual(profile["mean_variable_input_tokens"], 2)
        self.assertEqual(profile["mean_input_tokens"],
                         profile["static_input_tokens"] + 2)

    def test_reports_median_and_max_for_the_long_tail(self):
        profile = measure_task("", EnrichmentResult, ["a", "aa", "a" * 100], ["x"], _count)
        static = profile["static_input_tokens"]
        self.assertEqual(profile["median_input_tokens"], static + 2)
        self.assertEqual(profile["max_input_tokens"], static + 100)

    def test_sample_count_is_the_number_of_calls_not_of_outputs(self):
        profile = measure_task("", EnrichmentResult, ["a", "b"], ["x", "y", "z", "w"], _count)
        self.assertEqual(profile["n_samples"], 2)


class RenderTests(unittest.TestCase):
    def _profile(self, static=100, variable=200, output=40):
        return {
            "static_input_tokens": static,
            "mean_variable_input_tokens": variable,
            "mean_input_tokens": static + variable,
            "median_input_tokens": static + variable,
            "max_input_tokens": static + variable,
            "mean_output_tokens": output,
            "n_samples": 18,
        }

    def test_report_covers_every_priced_model_in_both_sections(self):
        report = render({"enrichment": self._profile()}, self._profile())
        for model in OPENAI_PRICE_PER_MILLION_TOKENS:
            self.assertEqual(report.count(f"| {model} |"), 2, model)

    def test_backfill_row_sums_both_tasks_per_listing(self):
        report = render({"enrichment": self._profile(), "canonical": self._profile()},
                        self._profile())
        self.assertIn("**600**", report)  # (100 + 200) x 2 tasks
        self.assertIn("**80**", report)   # 40 x 2 tasks


if __name__ == "__main__":
    unittest.main()
