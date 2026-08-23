"""
Tests for db_utils._clean_record.

This function had zero test coverage before, despite being the single
highest-risk function in the write path — it already caused one real
production bug (Milestone 19: property_type silently vanished from every
listing for a period because it wasn't yet in _CANONICAL_COLUMNS, and
nobody noticed until analytics looked empty).

Mental model this file locks in: _clean_record does NOT drop rows for
missing columns — every row survives except one missing a url entirely.
What it silently drops is individual FIELDS within a surviving row that
aren't in the canonical column allowlist (step 7) — that's the actual
landmine, now at least logged (see test_dropping_non_canonical_field_is_logged).
"""
import unittest
from unittest.mock import patch

import db_utils


class RowSurvivalTests(unittest.TestCase):
    def test_row_without_url_or_link_is_dropped_entirely(self):
        self.assertIsNone(db_utils._clean_record({"title": "no url here"}))

    def test_link_field_is_accepted_as_url(self):
        result = db_utils._clean_record({"link": "https://example.com/x"})
        self.assertEqual(result["url"], "https://example.com/x")

    def test_none_and_nan_values_are_stripped(self):
        result = db_utils._clean_record({
            "url": "https://example.com/x",
            "district": None,
            "area_sqm": float("nan"),
            "title": "Real value",
        })
        self.assertNotIn("district", result)
        self.assertNotIn("area_sqm", result)
        self.assertEqual(result["title"], "Real value")


class FieldNormalizationTests(unittest.TestCase):
    def test_image_urls_json_string_is_parsed_to_native_list(self):
        result = db_utils._clean_record({
            "url": "https://example.com/x",
            "image_urls": '[{"medium": "https://img/1.jpg"}]',
        })
        self.assertEqual(result["image_urls"], [{"medium": "https://img/1.jpg"}])

    def test_unparseable_image_urls_string_is_dropped_not_kept_broken(self):
        result = db_utils._clean_record({
            "url": "https://example.com/x",
            "image_urls": "not valid json",
        })
        self.assertNotIn("image_urls", result)

    def test_price_parsed_from_price_eur_defaults_to_eur_currency(self):
        result = db_utils._clean_record({
            "url": "https://example.com/x",
            "price_eur": "1 200 EUR/lună",
        })
        self.assertEqual(result["price_numeric"], 1200.0)
        self.assertEqual(result["price_currency"], "EUR")

    def test_price_containing_lei_is_detected_as_ron(self):
        result = db_utils._clean_record({
            "url": "https://example.com/x",
            "price_eur": "5000 lei/lună",
        })
        self.assertEqual(result["price_numeric"], 5000.0)
        self.assertEqual(result["price_currency"], "RON")

    def test_existing_price_numeric_is_never_overwritten(self):
        result = db_utils._clean_record({
            "url": "https://example.com/x",
            "price_numeric": 999.0,
            "price_eur": "1 200 EUR",
        })
        self.assertEqual(result["price_numeric"], 999.0)

    def test_rooms_num_below_five_maps_to_literal_digit(self):
        result = db_utils._clean_record({"url": "https://example.com/x", "rooms_num": "3 camere"})
        self.assertEqual(result["rooms"], "3")

    def test_rooms_num_five_or_above_maps_to_5_plus(self):
        result = db_utils._clean_record({"url": "https://example.com/x", "rooms_num": "7"})
        self.assertEqual(result["rooms"], "5+")

    def test_area_sqm_parsed_from_string_with_unit(self):
        result = db_utils._clean_record({"url": "https://example.com/x", "m": "64 m²"})
        self.assertEqual(result["area_sqm"], 64.0)

    def test_location_floor_year_built_aliases(self):
        result = db_utils._clean_record({
            "url": "https://example.com/x",
            "location_full_name": "Floreasca, Sector 1",
            "floor_no": "3",
            "build_year": "1990",
        })
        self.assertEqual(result["location_full"], "Floreasca, Sector 1")
        self.assertEqual(result["floor"], "3")
        self.assertEqual(result["year_built"], "1990")

    def test_embedding_list_is_formatted_as_pgvector_string(self):
        result = db_utils._clean_record({
            "url": "https://example.com/x",
            "embedding": [0.1, 0.2, 0.3],
        })
        self.assertEqual(result["embedding"], "[0.1,0.2,0.3]")


class PropertyTypeInferenceTests(unittest.TestCase):
    def test_garsoniera_keyword_in_title(self):
        result = db_utils._clean_record({"url": "https://x", "title": "Garsonieră modernă"})
        self.assertEqual(result["property_type"], "Garsoniera")

    def test_studio_keyword_in_title(self):
        result = db_utils._clean_record({"url": "https://x", "title": "Studio de închiriat"})
        self.assertEqual(result["property_type"], "Studio")

    def test_casa_vila_keywords_in_title(self):
        result = db_utils._clean_record({"url": "https://x", "title": "Vilă cu grădină"})
        self.assertEqual(result["property_type"], "Casa/Vila")

    def test_generic_title_defaults_to_apartament(self):
        result = db_utils._clean_record({"url": "https://x", "title": "Apartament 2 camere"})
        self.assertEqual(result["property_type"], "Apartament")

    def test_no_title_leaves_property_type_unset(self):
        result = db_utils._clean_record({"url": "https://x"})
        self.assertNotIn("property_type", result)

    def test_explicit_property_type_is_never_overwritten(self):
        result = db_utils._clean_record({
            "url": "https://x", "title": "Studio de închiriat", "property_type": "Apartament",
        })
        self.assertEqual(result["property_type"], "Apartament")


class NonCanonicalColumnStrippingTests(unittest.TestCase):
    """The actual landmine this function has: fields not in
    _CANONICAL_COLUMNS used to be silently dropped from an otherwise-
    surviving row. Fixed twice: first by logging the drop (so a genuine
    gap like the property_type incident surfaces immediately), then by
    folding the field into `extras` instead of discarding it outright
    (found live 2026-08-23: Storia's `characteristics` array flattens onto
    the raw item as top-level fields like building_floors_num,
    building_material, deposit — none canonical, all being silently lost
    on every single Storia listing — see BUGS.md #3c). These tests lock in
    that the row still survives, the unknown field is gone from the
    top-level output, it ends up inside `extras` instead of vanishing, and
    it's still logged for visibility."""

    def test_unknown_field_is_removed_from_the_top_level_output(self):
        result = db_utils._clean_record({
            "url": "https://x", "title": "Real title", "totally_made_up_field": "should vanish",
        })
        self.assertNotIn("totally_made_up_field", result)
        self.assertEqual(result["title"], "Real title")

    def test_unknown_field_is_folded_into_extras_instead_of_lost(self):
        result = db_utils._clean_record({
            "url": "https://x", "building_floors_num": "8", "deposit": "1 lună",
        })
        self.assertEqual(result["extras"]["building_floors_num"], "8")
        self.assertEqual(result["extras"]["deposit"], "1 lună")

    def test_folding_preserves_an_existing_extras_dict(self):
        result = db_utils._clean_record({
            "url": "https://x",
            "extras": {"original_key": "original_value"},
            "windows_type": "PVC",
        })
        self.assertEqual(result["extras"]["original_key"], "original_value")
        self.assertEqual(result["extras"]["windows_type"], "PVC")

    def test_existing_extras_value_wins_on_a_key_collision(self):
        """If extras already has a value for a name that also appears as a
        dropped top-level field, keep the existing extras value rather than
        silently overwrite it with the flattened duplicate."""
        result = db_utils._clean_record({
            "url": "https://x",
            "extras": {"deposit": "already set"},
            "deposit": "flattened duplicate",
        })
        self.assertEqual(result["extras"]["deposit"], "already set")

    def test_folding_non_canonical_field_is_logged(self):
        with patch("builtins.print") as mock_print:
            db_utils._clean_record({"url": "https://x", "made_up_field": "x"})

        logged = " ".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("made_up_field", logged)

    def test_no_print_when_nothing_is_dropped(self):
        with patch("builtins.print") as mock_print:
            db_utils._clean_record({"url": "https://x", "title": "Fine"})

        mock_print.assert_not_called()

    def test_known_raw_aliases_are_not_logged_as_dropped(self):
        """rooms_num, location_full_name, floor_no, build_year, m, link,
        rent, price are ALWAYS dropped once mapped to their canonical
        equivalent — on every single real listing. Logging those would
        flood production output and bury the genuinely novel case this
        exists to catch."""
        with patch("builtins.print") as mock_print:
            db_utils._clean_record({
                "url": "https://x",
                "rooms_num": "3",
                "location_full_name": "Floreasca",
                "floor_no": "2",
                "build_year": "1990",
                "m": "50 m²",
            })

        mock_print.assert_not_called()

    def test_unknown_field_alongside_known_aliases_is_still_logged(self):
        with patch("builtins.print") as mock_print:
            db_utils._clean_record({
                "url": "https://x", "rooms_num": "3", "genuinely_new_field": "x",
            })

        logged = " ".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("genuinely_new_field", logged)
        self.assertNotIn("rooms_num", logged)


if __name__ == "__main__":
    unittest.main()
