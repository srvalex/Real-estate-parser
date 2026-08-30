"""
Tests for api/locations.py's city-scoped sector_for() lookup
(GEO_EXPANSION_PLAN.md Phase 0).

Bug it guards against: "Dacia" is a real neighbourhood in both București
(with a sector) and Iași (no sector layer at all) — a city-blind lookup
would resolve Iași's "Dacia" to București's sector, mislabeling it.
"""
import unittest

from api.locations import sector_for


class SectorForCityScopingTests(unittest.TestCase):
    def test_known_bucuresti_neighbourhood_resolves_its_real_sector(self):
        self.assertEqual(sector_for("Bucuresti", "Dristor"), "Sector 3")

    def test_same_name_in_a_flat_city_does_not_borrow_bucuresti_sector(self):
        # "Dacia" exists in both cities' real data; Iasi has no sector layer.
        self.assertEqual(sector_for("Iasi", "Dacia"), "")

    def test_flat_city_never_resolves_a_sector(self):
        self.assertEqual(sector_for("Cluj-Napoca", "Centru"), "")

    def test_unknown_neighbourhood_returns_empty_string_not_an_error(self):
        self.assertEqual(sector_for("Bucuresti", "Nonexistent Place"), "")

    def test_unknown_city_returns_empty_string_not_an_error(self):
        self.assertEqual(sector_for("Atlantis", "Dristor"), "")


if __name__ == "__main__":
    unittest.main()
