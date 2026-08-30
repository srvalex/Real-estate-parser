"""
Tests for db_utils.query_listings_by_district's `city` parameter
(GEO_EXPANSION_PLAN.md Phase 0).

Bug: neighbourhood names are not globally unique once more than one city's
listings exist — confirmed live 2026-08-30 that "Centru" exists in both
Cluj-Napoca and Iași, and "Dacia"/"Aviatiei"/"Cantemir"/"Tudor Vladimirescu"
exist in both București and Iași. The query previously filtered only
`.in_("district", chunk)` with no city scoping, so selecting one city's
"Centru" would silently also return another city's "Centru" rows.

Fix: an optional `city` param adds `.eq("city", city)` alongside the
district filter. Optional (not required) only so
streamlit_interface/components/home.py's pre-existing call site (which
predates multi-city data and never passes a city) keeps working unchanged.
"""
import unittest
from unittest.mock import MagicMock, patch

import db_utils


class QueryListingsByDistrictCityScopingTests(unittest.TestCase):
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

    def test_city_given_adds_an_eq_filter(self):
        db_utils.query_listings_by_district(["Centru"], city="Cluj-Napoca")
        self.table.eq.assert_any_call("city", "Cluj-Napoca")

    def test_no_city_given_never_calls_eq_with_city(self):
        """The pre-existing Streamlit call site never passes city — must
        keep behaving exactly as before (no city filter at all), not
        default to some sentinel that would break it."""
        db_utils.query_listings_by_district(["Centru"])
        for call in self.table.eq.call_args_list:
            self.assertNotEqual(call.args[0] if call.args else None, "city")

    def test_city_filter_still_applied_alongside_price_filter(self):
        with patch.object(db_utils, "get_ron_to_eur_rate", return_value=5.0):
            db_utils.query_listings_by_district(["Centru"], city="Iasi", max_price_eur=500)
        self.table.eq.assert_any_call("city", "Iasi")
        self.table.eq.assert_any_call("is_available", 1)

    def test_city_filter_reapplied_for_every_chunk_batch(self):
        many_names = [f"District{i}" for i in range(150)]  # forces 2 chunks (batch size 100)
        db_utils.query_listings_by_district(many_names, city="Bucuresti")
        city_calls = [c for c in self.table.eq.call_args_list if c.args and c.args[0] == "city"]
        self.assertEqual(len(city_calls), 2)


if __name__ == "__main__":
    unittest.main()
