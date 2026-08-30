"""
Tests for db_utils.query_listings_by_city_paginated and its
_hard_filter_or_clauses helper — the fast path for a whole-city browse
with no ranking requested (api/main.py's all_districts=true, no vibe).

Unlike query_listings_by_city (fetch every row in the city, then filter
in a DataFrame — pipeline_core.apply_filters), this pushes every hard
filter into the SQL query as OR-clauses ("keep it if the value's missing,
apply the cutoff otherwise" — the same rule apply_filters applies in
Python) and paginates with .range() + count="exact", so exactly one
request is ever made regardless of city size. Verified live 2026-08-31
against the real project that stacking multiple .or_() calls on one
query composes them with AND, not overwrite-each-other, before trusting
that design here.
"""
import unittest
from unittest.mock import MagicMock, patch

import db_utils


class HardFilterOrClausesTests(unittest.TestCase):
    def test_no_filters_gives_no_clauses(self):
        self.assertEqual(db_utils._hard_filter_or_clauses(None, None, None, None, None), [])

    def test_zero_or_none_values_are_not_treated_as_filters(self):
        clauses = db_utils._hard_filter_or_clauses(
            max_price_eur=0, rooms=None, min_sqm=0, max_sqm=0, property_types=None
        )
        self.assertEqual(clauses, [])

    def test_max_price_clause_keeps_nulls_and_converts_ron(self):
        with patch.object(db_utils, "get_ron_to_eur_rate", return_value=5.0):
            clauses = db_utils._hard_filter_or_clauses(500, None, None, None, None)
        self.assertEqual(len(clauses), 1)
        self.assertIn("price_numeric.is.null", clauses[0])
        self.assertIn("price_currency.eq.EUR,price_numeric.lte.500", clauses[0])
        self.assertIn("price_currency.eq.RON,price_numeric.lte.2500.0", clauses[0])

    def test_rooms_clause_keeps_nulls_and_matches_exactly(self):
        clauses = db_utils._hard_filter_or_clauses(None, "5+", None, None, None)
        self.assertEqual(clauses, ["rooms.is.null,rooms.eq.5+"])

    def test_min_sqm_clause(self):
        clauses = db_utils._hard_filter_or_clauses(None, None, 40, None, None)
        self.assertEqual(clauses, ["area_sqm.is.null,area_sqm.gte.40"])

    def test_max_sqm_clause(self):
        clauses = db_utils._hard_filter_or_clauses(None, None, None, 80, None)
        self.assertEqual(clauses, ["area_sqm.is.null,area_sqm.lte.80"])

    def test_property_types_clause_joins_the_in_list(self):
        clauses = db_utils._hard_filter_or_clauses(None, None, None, None, ["Apartament", "Studio"])
        self.assertEqual(clauses, ["property_type.is.null,property_type.in.(Apartament,Studio)"])

    def test_all_filters_combine_into_separate_clauses(self):
        clauses = db_utils._hard_filter_or_clauses(500, "2", 40, 80, ["Apartament"])
        self.assertEqual(len(clauses), 5)


class QueryListingsByCityPaginatedTests(unittest.TestCase):
    def setUp(self):
        self.anon_client = MagicMock()
        self.table = self.anon_client.table.return_value
        self.table.select.return_value = self.table
        self.table.eq.return_value = self.table
        self.table.or_.return_value = self.table
        self.table.range.return_value = self.table
        self.table.execute.return_value = MagicMock(data=[{"url": "a"}], count=1)

        self._client_patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self._client_patch.start()
        self.addCleanup(self._client_patch.stop)

    def test_requests_an_exact_count(self):
        db_utils.query_listings_by_city_paginated("Iasi")
        select_kwargs = [c.kwargs for c in self.table.select.call_args_list]
        self.assertTrue(any(k.get("count") == "exact" for k in select_kwargs))

    def test_filters_by_city_and_availability(self):
        db_utils.query_listings_by_city_paginated("Iasi")
        self.table.eq.assert_any_call("city", "Iasi")
        self.table.eq.assert_any_call("is_available", 1)

    def test_returns_rows_and_count_from_a_single_request(self):
        self.table.execute.return_value = MagicMock(data=[{"url": "a"}, {"url": "b"}], count=250)
        rows, total = db_utils.query_listings_by_city_paginated("Iasi", offset=0, limit=60)
        self.assertEqual(rows, [{"url": "a"}, {"url": "b"}])
        self.assertEqual(total, 250)
        self.table.execute.assert_called_once()

    def test_paginates_using_the_given_offset_and_limit(self):
        db_utils.query_listings_by_city_paginated("Iasi", offset=120, limit=60)
        self.table.range.assert_called_once_with(120, 179)

    def test_hard_filters_are_applied_via_or_clauses(self):
        db_utils.query_listings_by_city_paginated("Iasi", rooms="2", min_sqm=40)
        or_args = [c.args[0] for c in self.table.or_.call_args_list]
        self.assertTrue(any("rooms.eq.2" in a for a in or_args))
        self.assertTrue(any("area_sqm.gte.40" in a for a in or_args))

    def test_no_hard_filters_never_calls_or(self):
        db_utils.query_listings_by_city_paginated("Iasi")
        self.table.or_.assert_not_called()

    def test_failure_returns_empty_results_and_zero_count(self):
        self.table.execute.side_effect = Exception("boom")
        rows, total = db_utils.query_listings_by_city_paginated("Iasi")
        self.assertEqual(rows, [])
        self.assertEqual(total, 0)

    def test_a_transient_failure_on_the_first_attempt_is_retried_once(self):
        """This is the only request the whole-city fast path makes now —
        confirmed live 2026-08-31 that a lone request against the real
        project occasionally throws a statement-timeout with no load
        involved. Without a retry, that turns into a search that silently
        looks like "nothing matches your filters" instead of erroring."""
        self.table.execute.side_effect = [
            Exception("canceling statement due to statement timeout"),
            MagicMock(data=[{"url": "a"}], count=1),
        ]
        rows, total = db_utils.query_listings_by_city_paginated("Iasi")
        self.assertEqual(rows, [{"url": "a"}])
        self.assertEqual(total, 1)
        self.assertEqual(self.table.execute.call_count, 2)

    def test_two_consecutive_failures_still_give_up_after_one_retry(self):
        self.table.execute.side_effect = Exception("boom")
        db_utils.query_listings_by_city_paginated("Iasi")
        self.assertEqual(self.table.execute.call_count, 2)


if __name__ == "__main__":
    unittest.main()
