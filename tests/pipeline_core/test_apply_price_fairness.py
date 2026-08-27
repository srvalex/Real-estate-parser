"""
Direct tests for pipeline_core.apply_price_fairness — new coverage,
including its price_fairness_pct column (the raw signed number the API
returns, alongside the pre-existing price_fairness display label Streamlit
uses).
"""
import unittest
from unittest.mock import patch

import pandas as pd

import db_utils
import pipeline_core

_STATS = {("Dristor", "2"): {"avg": 500.0, "count": 10}}


class PriceFairnessTests(unittest.TestCase):
    def test_empty_stats_suppresses_both_columns(self):
        df = pd.DataFrame([{"district": "Dristor", "rooms": "2", "price_numeric": 500, "price_currency": "EUR"}])
        result = pipeline_core.apply_price_fairness(df, price_stats={})
        self.assertIsNone(result.loc[0, "price_fairness"])
        self.assertIsNone(result.loc[0, "price_fairness_pct"])

    def test_price_above_average_labelled_and_signed_positive(self):
        df = pd.DataFrame([{"district": "Dristor", "rooms": "2", "price_numeric": 600, "price_currency": "EUR"}])
        result = pipeline_core.apply_price_fairness(df, price_stats=_STATS)
        self.assertEqual(result.loc[0, "price_fairness"], "+20% vs avg")
        self.assertEqual(result.loc[0, "price_fairness_pct"], 20)

    def test_price_below_average_labelled_and_signed_negative(self):
        df = pd.DataFrame([{"district": "Dristor", "rooms": "2", "price_numeric": 400, "price_currency": "EUR"}])
        result = pipeline_core.apply_price_fairness(df, price_stats=_STATS)
        self.assertEqual(result.loc[0, "price_fairness"], "-20% vs avg")
        self.assertEqual(result.loc[0, "price_fairness_pct"], -20)

    def test_within_threshold_is_suppressed(self):
        df = pd.DataFrame([{"district": "Dristor", "rooms": "2", "price_numeric": 510, "price_currency": "EUR"}])
        result = pipeline_core.apply_price_fairness(df, price_stats=_STATS)
        self.assertIsNone(result.loc[0, "price_fairness"])
        self.assertIsNone(result.loc[0, "price_fairness_pct"])

    def test_missing_district_or_rooms_is_suppressed(self):
        df = pd.DataFrame([{"district": None, "rooms": "2", "price_numeric": 600, "price_currency": "EUR"}])
        result = pipeline_core.apply_price_fairness(df, price_stats=_STATS)
        self.assertIsNone(result.loc[0, "price_fairness_pct"])

    def test_no_bucket_for_this_district_rooms_is_suppressed(self):
        df = pd.DataFrame([{"district": "Floreasca", "rooms": "2", "price_numeric": 600, "price_currency": "EUR"}])
        result = pipeline_core.apply_price_fairness(df, price_stats=_STATS)
        self.assertIsNone(result.loc[0, "price_fairness_pct"])

    def test_ron_price_is_converted_before_comparing_to_eur_bucket(self):
        """4000 RON at a 5.0 rate = 800 EUR -> +60% vs the 500 EUR avg,
        not the wildly wrong number a raw-RON comparison would produce."""
        df = pd.DataFrame([{"district": "Dristor", "rooms": "2", "price_numeric": 4000, "price_currency": "RON"}])
        with patch.object(db_utils, "get_ron_to_eur_rate", return_value=5.0):
            result = pipeline_core.apply_price_fairness(df, price_stats=_STATS)
        self.assertEqual(result.loc[0, "price_fairness_pct"], 60)


if __name__ == "__main__":
    unittest.main()
