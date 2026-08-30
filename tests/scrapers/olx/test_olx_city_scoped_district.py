"""
Tests that OLXScraper.scrape_listing_with_status matches title-based
district (_extract_district_from_title) against the RIGHT city's
neighbourhood list, not just Bucharest's.

GEO_EXPANSION_PLAN.md Phase 1: Streamlit Interface/districts.json is
Bucharest-only, so a Cluj-Napoca/Iași title needs its own neighbourhood
list (scrapers/olx.py's _NON_BUCHAREST_NEIGHBOURHOODS, sourced live from
Storia's own location-filter facet) rather than either matching against
Bucharest's list (false-positive risk) or being skipped entirely (which
was this repo's first pass, before real per-city lists existed).
"""
import unittest
from unittest.mock import patch, MagicMock

from scrapers.olx import OLXScraper

# "Titan" is a real Bucharest neighbourhood (Sector 3) but not a Cluj-Napoca
# one -- used as the false-positive bait for a non-Bucharest title.
TITAN_HTML = """
<html><body>
<div data-cy="offer_title"><h4>Apartament 2 camere zona Titan, Cluj-Napoca</h4></div>
<div data-testid="ad-price-container"><h3>500 EUR</h3></div>
<div data-cy="ad_description">Descriere.</div>
<div data-cy="ad-footer-bar-section"><span>ID<i></i>999999</span></div>
</body></html>
"""

# "Grigorescu" is a real Cluj-Napoca cartier (per Storia's facet).
GRIGORESCU_HTML = """
<html><body>
<div data-cy="offer_title"><h4>Apartament 2 camere Grigorescu, Cluj-Napoca</h4></div>
<div data-testid="ad-price-container"><h3>500 EUR</h3></div>
<div data-cy="ad_description">Descriere.</div>
<div data-cy="ad-footer-bar-section"><span>ID<i></i>999998</span></div>
</body></html>
"""

# "Pacurari" is a real Iași cartier (per Storia's facet).
PACURARI_HTML = """
<html><body>
<div data-cy="offer_title"><h4>Garsoniera Pacurari, Iasi</h4></div>
<div data-testid="ad-price-container"><h3>300 EUR</h3></div>
<div data-cy="ad_description">Descriere.</div>
<div data-cy="ad-footer-bar-section"><span>ID<i></i>999997</span></div>
</body></html>
"""


def _fake_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


class OlxCityScopedDistrictTests(unittest.TestCase):
    def test_default_city_still_runs_bucharest_district_matching(self):
        """Regression guard: no city argument at all (existing callers,
        existing tests) must behave exactly as before this change."""
        with patch("curl_cffi.requests.get", return_value=_fake_response(200, text=TITAN_HTML)):
            result = OLXScraper().scrape_listing_with_status(
                "https://www.olx.ro/d/oferta/test.html"
            )
        self.assertEqual(result["data"]["district"], "Titan")

    def test_explicit_bucuresti_city_runs_district_matching(self):
        with patch("curl_cffi.requests.get", return_value=_fake_response(200, text=TITAN_HTML)):
            result = OLXScraper().scrape_listing_with_status(
                "https://www.olx.ro/d/oferta/test.html", city="Bucuresti"
            )
        self.assertEqual(result["data"]["district"], "Titan")

    def test_bucharest_only_word_does_not_leak_into_cluj_matching(self):
        """Same title (containing "Titan") but tagged as a Cluj-Napoca search
        result -- "Titan" isn't a Cluj-Napoca cartier, so this must not be
        mislabeled as the Bucharest neighbourhood."""
        with patch("curl_cffi.requests.get", return_value=_fake_response(200, text=TITAN_HTML)):
            result = OLXScraper().scrape_listing_with_status(
                "https://www.olx.ro/d/oferta/test.html", city="Cluj-Napoca"
            )
        self.assertIsNone(result["data"]["district"])

    def test_cluj_title_matches_a_real_cluj_neighbourhood(self):
        with patch("curl_cffi.requests.get", return_value=_fake_response(200, text=GRIGORESCU_HTML)):
            result = OLXScraper().scrape_listing_with_status(
                "https://www.olx.ro/d/oferta/test2.html", city="Cluj-Napoca"
            )
        self.assertEqual(result["data"]["district"], "Grigorescu")

    def test_iasi_title_matches_a_real_iasi_neighbourhood(self):
        with patch("curl_cffi.requests.get", return_value=_fake_response(200, text=PACURARI_HTML)):
            result = OLXScraper().scrape_listing_with_status(
                "https://www.olx.ro/d/oferta/test3.html", city="Iasi"
            )
        self.assertEqual(result["data"]["district"], "Pacurari")

    def test_unknown_city_returns_none_rather_than_falling_back_to_bucharest(self):
        with patch("curl_cffi.requests.get", return_value=_fake_response(200, text=TITAN_HTML)):
            result = OLXScraper().scrape_listing_with_status(
                "https://www.olx.ro/d/oferta/test4.html", city="Timisoara"
            )
        self.assertIsNone(result["data"]["district"])


if __name__ == "__main__":
    unittest.main()
