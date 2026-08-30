"""
Tests for db_utils.query_listings_by_city — the "whole city" search mode
(api/main.py's `all_districts=true`), added alongside GEO_EXPANSION_PLAN.md
Phase 0's multi-city work.

Unlike query_listings_by_district (which chunks by district-name list but
never paginates row-wise), a city with no district filter can easily exceed
PostgREST's default page size, so this paginates via .range() like
get_price_stats/get_all_db_urls.

A concurrent-fan-out version of this function was tried (to cut the ~34s
it takes for a big city like București) and reverted 2026-08-31: firing
even 3 simultaneous page requests reliably hit Supabase's statement
timeout on most of them against the real project, silently returning a
fraction of the city's listings. Sequential-but-correct stays until the
real fix (push pagination + hard filters into the SQL query so a plain
whole-city browse never needs more than one page from the DB) is built.
"""
import unittest
from unittest.mock import MagicMock, patch

import db_utils


class QueryListingsByCityTests(unittest.TestCase):
    def setUp(self):
        self.anon_client = MagicMock()
        self.table = self.anon_client.table.return_value
        self.table.select.return_value = self.table
        self.table.eq.return_value = self.table
        self.table.or_.return_value = self.table
        self.table.range.return_value = self.table

        self._client_patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self._client_patch.start()
        self.addCleanup(self._client_patch.stop)

    def test_filters_by_city_and_availability_only(self):
        self.table.execute.return_value = MagicMock(data=[])
        db_utils.query_listings_by_city("Iasi")
        self.table.eq.assert_any_call("city", "Iasi")
        self.table.eq.assert_any_call("is_available", 1)
        self.table.or_.assert_not_called()

    def test_no_max_price_never_applies_an_or_filter(self):
        self.table.execute.return_value = MagicMock(data=[])
        db_utils.query_listings_by_city("Iasi", max_price_eur=None)
        self.table.or_.assert_not_called()

    def test_max_price_applies_an_or_filter(self):
        self.table.execute.return_value = MagicMock(data=[])
        with patch.object(db_utils, "get_ron_to_eur_rate", return_value=5.0):
            db_utils.query_listings_by_city("Iasi", max_price_eur=500)
        self.table.or_.assert_called_once()

    def test_paginates_until_a_short_page_is_returned(self):
        full_page = [{"url": f"https://x/{i}"} for i in range(1000)]
        short_page = [{"url": "https://x/last"}]
        self.table.execute.side_effect = [MagicMock(data=full_page), MagicMock(data=short_page)]

        results = db_utils.query_listings_by_city("Iasi")

        self.assertEqual(len(results), 1001)
        self.assertEqual(self.table.range.call_args_list[0].args, (0, 999))
        self.assertEqual(self.table.range.call_args_list[1].args, (1000, 1999))

    def test_stops_on_exception_instead_of_looping_forever(self):
        self.table.execute.side_effect = Exception("boom")
        results = db_utils.query_listings_by_city("Iasi")
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
