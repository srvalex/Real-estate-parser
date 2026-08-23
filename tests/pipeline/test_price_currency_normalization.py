"""
Regression tests for cross-currency price handling in
streamlit_interface/pipeline/utils.py's apply_filters / apply_price_fairness.

Bug: the dataset has both EUR and RON listings (price_currency), but
apply_filters' max_price cutoff and apply_price_fairness's "% vs avg"
badge both compared/aggregated raw price_numeric values with no currency
awareness at all.

Concretely, before this fix:
  - A max_price=500 (EUR) filter would silently exclude a listing priced
    at 2000 RON (~392 EUR — well within budget) because 2000 > 500
    numerically. Not an error, not a warning — the listing just vanished
    from results with nothing to indicate why.
  - get_price_stats() buckets are EUR-only (it filters price_currency=EUR
    before averaging), so a RON row's raw price_numeric compared against
    that EUR average produced a wildly wrong badge — e.g. a genuinely
    fairly-priced 4000 RON (~784 EUR) listing against an 850 EUR district
    average came out as "+371% vs avg" instead of the accurate "-8%".

Fix: price_in_eur() converts RON -> EUR before any cross-currency
comparison, using get_ron_to_eur_rate(). Both now live in db_utils.py (see
tests/db/test_bnr_rate_fetch.py for their own tests) — pipeline/utils.py
imports them. Note the mock target below: price_in_eur's internal call to
get_ron_to_eur_rate() resolves in db_utils's own namespace (that's where
the function is defined), not pipeline_utils's, even though pipeline_utils
also has a name bound to the same function via its import — so these tests
patch db_utils.get_ron_to_eur_rate, not putils.get_ron_to_eur_rate.
"""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import db_utils

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UTILS_PATH = _REPO_ROOT / "streamlit_interface" / "pipeline" / "utils.py"

_TEST_RATE = 5.0  # a clean round number, easy to hand-verify expected results


def _load_pipeline_utils():
    spec = importlib.util.spec_from_file_location("pipeline_utils_under_test_price", _UTILS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


putils = _load_pipeline_utils()


class PrepareDataframePriceTests(unittest.TestCase):
    def test_price_num_is_eur_normalized_for_mixed_currency_rows(self):
        df = pd.DataFrame({
            "url": ["https://a", "https://b"],
            "price_numeric": [500.0, 2000.0],
            "price_currency": ["EUR", "RON"],
        })
        with patch.object(db_utils, "get_ron_to_eur_rate", return_value=_TEST_RATE):
            result = putils.prepare_dataframe(df)
        self.assertEqual(result.loc[0, "_price_num"], 500.0)
        self.assertAlmostEqual(result.loc[1, "_price_num"], 2000.0 / _TEST_RATE, places=4)


class ApplyFiltersMaxPriceCurrencyTests(unittest.TestCase):
    def test_affordable_ron_listing_is_not_wrongly_excluded(self):
        """The exact reported symptom: a 2000 RON listing (~400 EUR at the
        test rate) must pass a max_price=500 (EUR) filter, not get
        silently dropped because 2000 > 500 as raw numbers."""
        df = pd.DataFrame({
            "url": ["https://cheap-eur", "https://affordable-ron", "https://expensive-ron"],
            "price_numeric": [450.0, 2000.0, 20000.0],
            "price_currency": ["EUR", "RON", "RON"],
        })
        with patch.object(db_utils, "get_ron_to_eur_rate", return_value=_TEST_RATE):
            df = putils.prepare_dataframe(df)
            result = putils.apply_filters(df, max_price=500, sel_rooms="Orice")

        self.assertIn("https://cheap-eur", result["url"].values)
        self.assertIn("https://affordable-ron", result["url"].values)
        self.assertNotIn("https://expensive-ron", result["url"].values)


class ApplyPriceFairnessCurrencyTests(unittest.TestCase):
    def test_ron_listing_compared_against_eur_average_produces_sane_percentage(self):
        """4000 RON at the test rate (800 EUR) against an 850 EUR average
        should read as a modest negative percentage, not the wildly wrong
        value you'd get comparing the raw RON number to a EUR average."""
        df = pd.DataFrame({
            "district": ["Floreasca"],
            "rooms": ["2"],
            "price_numeric": [4000.0],
            "price_currency": ["RON"],
        })

        with patch.object(db_utils, "get_ron_to_eur_rate", return_value=_TEST_RATE), \
             patch.object(
                 putils, "_cached_price_stats",
                 return_value={("Floreasca", "2"): {"avg": 850.0, "count": 10}},
             ):
            result = putils.apply_price_fairness(df)

        self.assertEqual(result.loc[0, "price_fairness"], "-6% vs avg")

    def test_eur_listing_still_works_as_before(self):
        df = pd.DataFrame({
            "district": ["Floreasca"],
            "rooms": ["2"],
            "price_numeric": [1000.0],
            "price_currency": ["EUR"],
        })

        with patch.object(
            putils, "_cached_price_stats",
            return_value={("Floreasca", "2"): {"avg": 850.0, "count": 10}},
        ):
            result = putils.apply_price_fairness(df)

        self.assertEqual(result.loc[0, "price_fairness"], "+18% vs avg")


if __name__ == "__main__":
    unittest.main()
