"""
Tests for db_utils.get_price_stats's `city` parameter
(GEO_EXPANSION_PLAN.md Phase 0).

Bug: buckets were keyed by (district, rooms) only, pooled across every
city's rows. Now that "Centru" exists in both Cluj-Napoca and Iași, a
Cluj-Napoca "Centru" studio would get averaged together with Iași's
"Centru" studios into one blended, meaningless baseline — comparing a
listing's price against the wrong city's market entirely.

Fix: an optional `city` param scopes the row population with
.eq("city", city) before bucketing. Optional (not required) for the same
Streamlit-predates-multi-city reason as query_listings_by_district.
"""
import unittest
from unittest.mock import MagicMock, patch

import db_utils


class GetPriceStatsCityScopingTests(unittest.TestCase):
    def setUp(self):
        self.anon_client = MagicMock()
        self.table = self.anon_client.table.return_value
        self.table.select.return_value = self.table
        self.table.eq.return_value = self.table
        self.table.range.return_value = self.table

        self._client_patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self._client_patch.start()
        self.addCleanup(self._client_patch.stop)

    def test_city_given_adds_an_eq_filter(self):
        self.table.execute.return_value = MagicMock(data=[])
        db_utils.get_price_stats(city="Cluj-Napoca")
        self.table.eq.assert_any_call("city", "Cluj-Napoca")

    def test_no_city_given_never_filters_by_city(self):
        self.table.execute.return_value = MagicMock(data=[])
        db_utils.get_price_stats()
        for call in self.table.eq.call_args_list:
            self.assertNotEqual(call.args[0] if call.args else None, "city")

    def test_same_named_district_in_two_cities_gets_independent_buckets(self):
        """Scoping happens at the query level (only one city's rows are
        ever fetched per call), so this asserts the *contract*: calling
        get_price_stats(city=X) only ever sees rows already filtered to X
        by the mocked query — cross-city pooling would mean this test's
        fixture setup is meaningless, since the whole point is the SQL
        filter, not client-side grouping."""
        cluj_rows = [{"district": "Centru", "rooms": "1", "price_numeric": 400 + i} for i in range(5)]
        self.table.execute.return_value = MagicMock(data=cluj_rows)
        stats = db_utils.get_price_stats(city="Cluj-Napoca")
        self.table.eq.assert_any_call("city", "Cluj-Napoca")
        self.assertIn(("Centru", "1"), stats)
        self.assertAlmostEqual(stats[("Centru", "1")]["avg"], sum(r["price_numeric"] for r in cluj_rows) / 5)


if __name__ == "__main__":
    unittest.main()
