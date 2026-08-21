"""
Unit tests for OLXScraper.scrape_listing_with_status.

Before this file, OLX had zero test coverage of any kind — despite being
one of three scraped platforms and having the exact same expired/blocked
ambiguity class of bug already found and fixed on Storia. These tests were
written against real ground truth (2026-08-22): three live OLX URLs with
known real-world states.

Live findings (curl_cffi, no proxy, from this environment):
  - Expired listing (user-confirmed)              -> HTTP 410, no body needed
  - Available listing (user-confirmed)             -> HTTP 200, fully parseable
  - Expired listing user observed as "blocked"     -> HTTP 410 (from here)

The third case returned a clean 410 in this environment and is already
handled correctly by the very first check in scrape_listing_with_status
(status_code == 410 -> expired, unconditionally, no body parsing at all).
The "blocked" outcome the user saw was most likely produced by their
proxy/network path (OLX has no proxy health-check today — see
crawler.py's ProxyRotator, which verifies Storia and Imobiliare but not
OLX), not a classification bug in this function. These tests lock in the
status-code-first behavior with synthetic fixtures so it can never
regress, and cover the body-parsing fallback paths (soft-delete banner,
live listing, unparseable-but-200) that had no coverage at all before.
"""
import unittest
from unittest.mock import patch, MagicMock

from scrapers.olx import OLXScraper

LIVE_LISTING_HTML = """
<html><body>
<div data-cy="offer_title"><h4>Apartament 2 camere</h4></div>
<div data-testid="ad-price-container"><h3>1200 EUR</h3></div>
<div data-cy="ad_description">Frumos si spatios.</div>
<div data-cy="ad-footer-bar-section"><span>ID<i></i>123456</span></div>
</body></html>
"""

SOFT_DELETED_HTML = """
<html><body>
<div data-testid="ad-inactive-msg">Acest anunt nu mai este activ</div>
</body></html>
"""

UNPARSEABLE_200_HTML = "<html><body><h1>Something unexpected — page structure changed</h1></body></html>"


def _fake_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


class OlxDetectionTests(unittest.TestCase):
    def test_http_410_is_expired_regardless_of_body_content(self):
        """HTTP 410 Gone is OLX's canonical removed-listing response and must
        be trusted immediately — no body parsing needed or attempted."""
        with patch("curl_cffi.requests.get", return_value=_fake_response(410, text="")):
            result = OLXScraper().scrape_listing_with_status("https://www.olx.ro/d/oferta/test-ID1.html")
        self.assertEqual(result["status"], "expired")

    def test_soft_deleted_banner_with_200_status_is_expired(self):
        with patch("curl_cffi.requests.get", return_value=_fake_response(200, text=SOFT_DELETED_HTML)):
            result = OLXScraper().scrape_listing_with_status("https://www.olx.ro/d/oferta/test-ID2.html")
        self.assertEqual(result["status"], "expired")

    def test_live_listing_is_parsed_successfully(self):
        with patch("curl_cffi.requests.get", return_value=_fake_response(200, text=LIVE_LISTING_HTML)):
            result = OLXScraper().scrape_listing_with_status("https://www.olx.ro/d/oferta/test-ID3.html")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["title"], "Apartament 2 camere")
        self.assertEqual(result["data"]["price_eur"], "1200 EUR")

    def test_unparseable_200_page_defaults_to_blocked_not_expired(self):
        """A 200 page that isn't the known soft-delete banner and can't be
        parsed as a live listing must default to blocked — the same safe
        default already fixed on Storia. Never silently assume expired
        without positive evidence."""
        with patch("curl_cffi.requests.get", return_value=_fake_response(200, text=UNPARSEABLE_200_HTML)):
            result = OLXScraper().scrape_listing_with_status("https://www.olx.ro/d/oferta/test-ID4.html")
        self.assertEqual(result["status"], "blocked")

    def test_non_200_non_410_status_is_blocked(self):
        with patch("curl_cffi.requests.get", return_value=_fake_response(403, text="Forbidden")):
            result = OLXScraper().scrape_listing_with_status("https://www.olx.ro/d/oferta/test-ID5.html")
        self.assertEqual(result["status"], "blocked")

    def test_network_exception_is_blocked(self):
        with patch("curl_cffi.requests.get", side_effect=ConnectionError("boom")):
            result = OLXScraper().scrape_listing_with_status("https://www.olx.ro/d/oferta/test-ID6.html")
        self.assertEqual(result["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
