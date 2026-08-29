"""
Regression tests for ImobiliareRoScraper._parse_raw's extras extraction.

Bug: every Imobiliare.ro row in the DB had `extras` populated with GA4/
consent-banner tracking fields (ad_storage, session_hash, visitor_id,
request_id, onesignal_*, ...) instead of property attributes — confirmed
live via scripts/inspect_extras.py against 40 real rows, and reproduced
back to the earliest row in the table (2026-06-16), so it wasn't a recent
regression.

Root cause: _parse_raw used to dump every remaining key of the matched `dl`
(dataLayer) entry into extras, on the assumption (per its old comment) that
"all are listing-specific attributes". In fact that entry is the one GTM
pageview event object with a `listing_id` key (see
scripts/get_imobiliare_listing.py fetch_url) — dominated by generic
consent/tracking fields, with only a couple of listing-shaped keys mixed
in that duplicate data already captured from the JSON-LD nodes anyway.

Fix: stop reading anything from `dl` into extras. extras is now built only
from the JSON-LD RealEstateListing node's own fields (floorLevel,
numberOfRooms/numberOfBedrooms, numberOfBathroomsTotal, yearBuilt,
floorSize). These tests use realistic `dl`/`ld` shapes captured live
2026-08-27 from a real garsoniera listing (Dristor, sector 3).
"""
import unittest

from scrapers.imobiliare import ImobiliareRoScraper


# A real dataLayer pageview entry shape, as returned by
# get_imobiliare_listing.py's `next(e for e in dl_data if "listing_id" in e)`
# — trimmed to the keys actually observed live, GA/consent noise included.
REAL_DL_ENTRY = {
    "listing_id": "275924043",
    "listing_location_title": "Dristor",
    "listing_location_slug": "bucuresti-sector-3-dristor",
    "onesignal_listing_bedroom": "1-camere",
    # everything below is what used to leak into extras
    "env": "production",
    "session_hash": "809e6510ecfbde6b22171930747a4cbe",
    "visitor_id": 5837195988,
    "request_id": "9ea4a2a9c64ad1ab8d5726f32c4c48c7",
    "ad_storage": "denied",
    "analytics_storage": "denied",
    "user_has_enquired": False,
    "user_has_saved_searches": False,
    "listing_price": "390.00",
    "listing_currency": "EUR",
    "search_title": "Garsoniera Dristor, 7 minute de metrou",
    "onesignal_listing_bedroom_tag": "1-camere",
    "onesignal_listing_location": "sector-3",
}

# A real RealEstateListing/Accommodation-style JSON-LD node — this specific
# live listing only had numberOfBedrooms, never numberOfRooms.
REAL_LISTING_LD = {
    "floorLevel": "1",
    "floorSize": {"value": "44", "unitCode": "MTK"},
    "numberOfBathroomsTotal": "1",
    "numberOfBedrooms": 1,
}


def _raw(ld_listing=None, dl=None, url="https://www.imobiliare.ro/oferta/garsoniera-de-inchiriat-sector-3-dristor-44mp-275924043"):
    return {
        "status": "success",
        "url": url,
        "ld": {
            "product": {"name": "Garsoniera Dristor | Imobiliare.ro", "description": "desc", "image": []},
            "offer": {"priceSpecification": {"price": 390, "priceCurrency": "EUR"}},
            "listing": ld_listing if ld_listing is not None else {},
        },
        "dl": dl if dl is not None else {},
    }


class TrackingDataNeverLeaksIntoExtrasTests(unittest.TestCase):
    def setUp(self):
        self.scraper = ImobiliareRoScraper()

    def test_ga_and_consent_fields_are_absent_from_extras(self):
        result = self.scraper._parse_raw(_raw(dl=REAL_DL_ENTRY))
        extras = result["extras"] or {}
        leaked = {"session_hash", "visitor_id", "request_id", "ad_storage",
                  "analytics_storage", "env", "user_has_enquired", "user_has_saved_searches"}
        self.assertFalse(leaked & extras.keys(), f"tracking fields leaked into extras: {leaked & extras.keys()}")

    def test_redundant_listing_dl_fields_are_also_absent(self):
        # Redundant with data already captured from ld/canonical columns —
        # dropped along with the rest of dl, not selectively kept.
        result = self.scraper._parse_raw(_raw(dl=REAL_DL_ENTRY))
        extras = result["extras"] or {}
        self.assertNotIn("listing_price", extras)
        self.assertNotIn("search_title", extras)
        self.assertNotIn("onesignal_listing_location", extras)

    def test_dl_still_drives_district_rooms_and_source_id(self):
        # The fix only stops the *dump into extras* — dl is still the
        # source for these already-canonical fields.
        result = self.scraper._parse_raw(_raw(dl=REAL_DL_ENTRY))
        self.assertEqual(result["district"], "Dristor")
        self.assertEqual(result["location_full_name"], "bucuresti-sector-3-dristor")
        self.assertEqual(result["rooms"], "1")
        self.assertEqual(result["source_id"], "275924043")


class StructuredLdFieldsStillCapturedTests(unittest.TestCase):
    def setUp(self):
        self.scraper = ImobiliareRoScraper()

    def test_number_of_bedrooms_is_captured_when_number_of_rooms_is_absent(self):
        result = self.scraper._parse_raw(_raw(ld_listing=REAL_LISTING_LD))
        self.assertEqual(result["extras"]["numberOfBedrooms"], 1)
        self.assertNotIn("numberOfRooms", result["extras"])

    def test_number_of_rooms_is_still_captured_when_present(self):
        listing = dict(REAL_LISTING_LD, numberOfRooms=3)
        result = self.scraper._parse_raw(_raw(ld_listing=listing))
        self.assertEqual(result["extras"]["numberOfRooms"], 3)

    def test_floor_level_and_bathrooms_are_captured(self):
        result = self.scraper._parse_raw(_raw(ld_listing=REAL_LISTING_LD))
        self.assertEqual(result["extras"]["floorLevel"], "1")
        self.assertEqual(result["extras"]["numberOfBathroomsTotal"], "1")

    def test_floor_size_value_and_unit_are_flattened_out_of_the_nested_dict(self):
        result = self.scraper._parse_raw(_raw(ld_listing=REAL_LISTING_LD))
        self.assertEqual(result["extras"]["floorSizeValue"], "44")
        self.assertEqual(result["extras"]["floorSizeUnit"], "MTK")

    def test_no_structured_fields_and_no_dl_extras_means_extras_is_none(self):
        result = self.scraper._parse_raw(_raw(ld_listing={}, dl=REAL_DL_ENTRY))
        self.assertIsNone(result["extras"])


if __name__ == "__main__":
    unittest.main()
