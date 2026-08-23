"""
Tests for two efficiency/correctness properties of
db_utils.query_listings_by_district (BUGS.md #1):

1. It must SELECT only the columns the Streamlit results pipeline
   (streamlit_interface/components/results.py, pipeline/utils.py) actually
   reads for rendering and AI-ranking input — not "*", and not every
   _CANONICAL_COLUMNS entry either. Excluded: "extras" (raw JSONB blob) and
   the two pgvector columns ("embedding" 384-dim, "image_embedding" 512-dim)
   — semantic-search similarity is computed server-side inside the
   match_listings/match_listings_by_image RPCs and joined back in by url,
   never read off this query; "is_available" — already enforced by .eq()
   independent of the select list, and never displayed here; and the
   Analytics-tab-only fields ("platform_id", "source_id", "floor",
   "total_floors", "year_built", "heating", "features", "scraped_at",
   "first_seen_at", "last_seen_at"), which have their own separately-scoped
   query (fetch_analytics_data()). The vector/blob columns in particular were
   the prime suspect for the observed Postgres statement timeout on district
   queries like "Militari".

2. is_available must be filtered with a strict eq(1), never widened to
   include -1 (blocked/transient) or 0 (expired) rows — showing either to
   a user looking at "available" listings is a real UX regression, not
   just a data-quality nit.
"""
import unittest
from unittest.mock import MagicMock, patch

import db_utils

_EXPECTED_COLUMNS = frozenset({
    "url", "title", "description",
    "price_eur", "price_numeric", "price_currency",
    "district", "location_full",
    "rooms", "area_sqm", "property_type", "platform", "image_urls",
})

_DELIBERATELY_EXCLUDED_COLUMNS = frozenset({
    "extras", "embedding", "image_embedding", "is_available",
    "platform_id", "source_id", "floor", "total_floors", "year_built",
    "heating", "features", "scraped_at", "first_seen_at", "last_seen_at",
})


class QueryListingsByDistrictColumnScopeTests(unittest.TestCase):
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

    def test_does_not_select_star(self):
        db_utils.query_listings_by_district(["Floreasca"])
        selected = self.table.select.call_args.args[0]
        self.assertNotEqual(selected.strip(), "*")

    def test_excludes_heavy_and_unused_columns(self):
        db_utils.query_listings_by_district(["Floreasca"])
        selected = self.table.select.call_args.args[0]
        columns = {c.strip() for c in selected.split(",")}
        self.assertEqual(columns & _DELIBERATELY_EXCLUDED_COLUMNS, set())

    def test_selects_exactly_the_columns_the_results_pipeline_reads(self):
        db_utils.query_listings_by_district(["Floreasca"])
        selected = self.table.select.call_args.args[0]
        columns = {c.strip() for c in selected.split(",")}
        self.assertEqual(columns, _EXPECTED_COLUMNS)

    def test_availability_filter_is_a_strict_eq_one(self):
        """Guards against ever widening this to .in_("is_available", [1, -1])
        or an .or_() that would let blocked/transient (-1) or expired (0)
        rows leak into user-facing results."""
        db_utils.query_listings_by_district(["Floreasca"])
        self.table.eq.assert_any_call("is_available", 1)
        for call in self.table.in_.call_args_list:
            if call.args and call.args[0] == "is_available":
                self.fail("is_available must use eq(1), not in_(...)")

    def test_availability_filter_still_strict_when_price_filter_is_also_applied(self):
        with patch.object(db_utils, "get_ron_to_eur_rate", return_value=5.0):
            db_utils.query_listings_by_district(["Floreasca"], max_price_eur=500)
        self.table.eq.assert_any_call("is_available", 1)


if __name__ == "__main__":
    unittest.main()
