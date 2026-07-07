import ast
import unittest

from scrapers.storia import StoriaScraper


class StoriaFeaturesExtractionTests(unittest.TestCase):
    """Regression: Storia's old flat `features` / `featuresByCategory` fields
    are always empty in current API responses -- the real amenity data lives
    in `additionalInformation`, grouped by category. See _parse_raw()."""

    def _parse(self, additional_information):
        scraper = StoriaScraper()
        data = {
            "id": 1,
            "url": "https://www.storia.ro/ro/oferta/test",
            "title": "Test",
            "characteristics": [],
            "location": {},
            "description": "",
            "images": [],
            "additionalInformation": additional_information,
        }
        result = scraper._parse_raw({"data": data})
        result["features"] = ast.literal_eval(result["features"])
        return result

    def test_category_values_use_the_suffix_after_double_colon(self):
        result = self._parse([
            {"label": "extras_types", "values": ["extras_types::balcony", "extras_types::separate_kitchen"]},
        ])
        self.assertEqual(result["features"], ["balcony", "separate_kitchen"])

    def test_positive_boolean_flag_emits_the_label(self):
        result = self._parse([
            {"label": "rent_to_students", "values": ["::y"]},
        ])
        self.assertEqual(result["features"], ["rent_to_students"])

    def test_negative_boolean_flag_is_dropped(self):
        result = self._parse([
            {"label": "lift", "values": ["::n"]},
        ])
        self.assertEqual(result["features"], [])

    def test_mixed_categories_flatten_into_one_list(self):
        result = self._parse([
            {"label": "security_types", "values": ["security_types-102::anti_burglary_door", "security_types-102::entryphone"]},
            {"label": "lift", "values": ["::y"]},
            {"label": "rent_to_students", "values": ["::n"]},
        ])
        self.assertEqual(result["features"], ["anti_burglary_door", "entryphone", "lift"])

    def test_missing_additional_information_yields_empty_list(self):
        result = self._parse(None)
        self.assertEqual(result["features"], [])


if __name__ == "__main__":
    unittest.main()
