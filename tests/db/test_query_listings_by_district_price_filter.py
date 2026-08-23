"""
Tests for the max_price_eur server-side filter on
db_utils.query_listings_by_district.

Design: rather than converting each row's RON price to EUR inside the SQL
query (price_numeric / rate <= max_price_eur, a per-row computed
expression), the filter pre-computes max_price_eur * rate once in Python
and compares the RON branch's price_numeric directly against that literal
— algebraically identical (rate is always positive, so multiplying both
sides of the inequality by it preserves direction), but keeps both
branches of the OR as a plain column-vs-literal comparison.

Listings with price_numeric IS NULL are always kept, matching
apply_filters' existing "never penalise missing data" behaviour.
"""
import unittest
from unittest.mock import MagicMock, patch

import db_utils


class QueryListingsByDistrictPriceFilterTests(unittest.TestCase):
    def setUp(self):
        self.anon_client = MagicMock()
        self.table = self.anon_client.table.return_value
        self.table.select.return_value = self.table
        self.table.in_.return_value = self.table
        self.table.eq.return_value = self.table
        self.table.or_.return_value = self.table
        self.table.execute.return_value = MagicMock(data=[])

        self._client_patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self._client_patch.start()
        self.addCleanup(self._client_patch.stop)

        self._rate_patch = patch.object(db_utils, "get_ron_to_eur_rate", return_value=5.0)
        self._rate_patch.start()
        self.addCleanup(self._rate_patch.stop)

    def test_no_max_price_never_applies_an_or_filter(self):
        """Backward compatibility: existing callers that don't pass
        max_price_eur must see byte-for-byte the same query as before."""
        db_utils.query_listings_by_district(["Floreasca"])
        self.table.or_.assert_not_called()

    def test_zero_max_price_is_treated_as_no_filter(self):
        """Matches the existing '0 means unlimited' convention used
        elsewhere in this codebase (e.g. crawler.py --max-price)."""
        db_utils.query_listings_by_district(["Floreasca"], max_price_eur=0)
        self.table.or_.assert_not_called()

    def test_max_price_applies_the_currency_aware_or_filter(self):
        db_utils.query_listings_by_district(["Floreasca"], max_price_eur=500)

        self.table.or_.assert_called_once()
        filter_str = self.table.or_.call_args.args[0]
        self.assertIn("price_numeric.is.null", filter_str)
        self.assertIn("price_currency.eq.EUR,price_numeric.lte.500", filter_str)
        self.assertIn("price_currency.eq.RON,price_numeric.lte.2500.0", filter_str)  # 500 * rate(5.0)

    def test_district_and_availability_filters_still_applied_alongside_price(self):
        db_utils.query_listings_by_district(["Floreasca", "Aviatiei"], max_price_eur=500)

        self.table.in_.assert_called_with("district", ["Floreasca", "Aviatiei"])
        self.table.eq.assert_called_with("is_available", 1)

    def test_ron_threshold_uses_the_current_rate(self):
        with patch.object(db_utils, "get_ron_to_eur_rate", return_value=5.2581):
            db_utils.query_listings_by_district(["Floreasca"], max_price_eur=500)

        filter_str = self.table.or_.call_args.args[0]
        self.assertIn(f"price_numeric.lte.{500 * 5.2581}", filter_str)


if __name__ == "__main__":
    unittest.main()
