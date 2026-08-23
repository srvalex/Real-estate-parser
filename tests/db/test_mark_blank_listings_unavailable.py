"""
Tests for scripts/mark_blank_listings_unavailable.py's is_blank_listing()
classification — the safety check that decides which is_available=1 rows
get flipped to 0 in the one-off cleanup for the blank-Imobiliare-row bug
found 2026-08-23 (title/description/price/district all empty, no embedding
possible — see the script's module docstring for the full root cause).

Deliberately conservative: a row must be blank on ALL four signals to
qualify, so anything with even partial real content is left alone.
"""
import importlib.util
import unittest
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "mark_blank_listings_unavailable.py"
_spec = importlib.util.spec_from_file_location("mark_blank_listings_unavailable", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
is_blank_listing = _mod.is_blank_listing


class IsBlankListingTests(unittest.TestCase):
    def test_fully_blank_row_is_blank(self):
        row = {"url": "https://x", "title": None, "description": None,
               "price_numeric": None, "district": None}
        self.assertTrue(is_blank_listing(row))

    def test_empty_string_fields_count_as_blank(self):
        row = {"url": "https://x", "title": "", "description": "  ",
               "price_numeric": None, "district": ""}
        self.assertTrue(is_blank_listing(row))

    def test_missing_keys_count_as_blank(self):
        self.assertTrue(is_blank_listing({"url": "https://x"}))

    def test_real_title_is_not_blank(self):
        row = {"url": "https://x", "title": "Apartament 2 camere", "description": None,
               "price_numeric": None, "district": None}
        self.assertFalse(is_blank_listing(row))

    def test_real_description_is_not_blank(self):
        row = {"url": "https://x", "title": None, "description": "Frumos si spatios",
               "price_numeric": None, "district": None}
        self.assertFalse(is_blank_listing(row))

    def test_real_price_is_not_blank(self):
        row = {"url": "https://x", "title": None, "description": None,
               "price_numeric": 500.0, "district": None}
        self.assertFalse(is_blank_listing(row))

    def test_zero_price_is_not_blank(self):
        """0 is a real (if unusual) price value, not a missing one -- must
        not be treated the same as None."""
        row = {"url": "https://x", "title": None, "description": None,
               "price_numeric": 0, "district": None}
        self.assertFalse(is_blank_listing(row))

    def test_real_district_is_not_blank(self):
        row = {"url": "https://x", "title": None, "description": None,
               "price_numeric": None, "district": "Floreasca"}
        self.assertFalse(is_blank_listing(row))


if __name__ == "__main__":
    unittest.main()
