"""
Tests for api/locations.py's city-scoped sector_for() lookup
(GEO_EXPANSION_PLAN.md Phase 0).

Bug it guards against: "Dacia" is a real neighbourhood in both București
(with a sector) and Iași (no sector layer at all) — a city-blind lookup
would resolve Iași's "Dacia" to București's sector, mislabeling it.
"""
import unittest

from api.locations import city_has_sectors, sector_for


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


class SelfDeclaredSectorTests(unittest.TestCase):
    """Some listings put the sector itself in `district` ("Sectorul 3")
    rather than a neighbourhood name. Confirmed live 2026-09-08: 167
    available Bucharest listings did, and every one was dropped from the
    sector charts before sector_for learned to read them."""

    def test_sectorul_n_resolves_to_that_sector(self):
        for raw in ("Sectorul 1", "Sectorul 6"):
            with self.subTest(raw=raw):
                self.assertEqual(sector_for("Bucuresti", raw), f"Sector {raw[-1]}")

    def test_alternate_spellings_and_casing_resolve(self):
        for raw in ("Sector 3", "sectorul 3", "SECTORUL 3", "  Sectorul 3  ", "sector 3"):
            with self.subTest(raw=raw):
                self.assertEqual(sector_for("Bucuresti", raw), "Sector 3")

    def test_out_of_range_sector_numbers_are_not_invented(self):
        for raw in ("Sectorul 0", "Sectorul 7", "Sectorul 12"):
            with self.subTest(raw=raw):
                self.assertEqual(sector_for("Bucuresti", raw), "")

    def test_a_neighbourhood_merely_containing_the_word_is_not_matched(self):
        self.assertEqual(sector_for("Bucuresti", "Sectorul 3 Titan"), "")

    def test_self_declared_sector_is_ignored_for_a_city_without_sectors(self):
        self.assertEqual(sector_for("Cluj-Napoca", "Sectorul 3"), "")

    def test_real_neighbourhood_lookup_still_works(self):
        self.assertEqual(sector_for("Bucuresti", "Aviatiei"), "Sector 1")


class CityHasSectorsTests(unittest.TestCase):
    def test_bucharest_has_sectors(self):
        self.assertTrue(city_has_sectors("Bucuresti"))

    def test_flat_cities_do_not(self):
        self.assertFalse(city_has_sectors("Cluj-Napoca"))
        self.assertFalse(city_has_sectors("Iasi"))

    def test_unknown_city_does_not(self):
        self.assertFalse(city_has_sectors("Atlantis"))
        self.assertFalse(city_has_sectors(""))
