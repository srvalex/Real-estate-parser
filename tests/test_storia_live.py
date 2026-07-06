"""
Integration tests against Storia listing URLs.
Requires network access.

Tests verify correctness of the detection pipeline:
  - Expired listings  → is_available=0  (redirect away from /ro/oferta/)
  - Bot-blocked pages → is_available=None (unchanged, not falsely expired)
  - Live listings     → is_available=1
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.storia import StoriaScraper


# IDGERe is a confirmed-expired listing (redirects to search page).
# IDGMen may be live or bot-blocked depending on network conditions.
EXPIRED_URL  = "https://www.storia.ro/ro/oferta/apartament-2-camere-dristor-metrou-IDGERe"
CHECKED_URL  = "https://www.storia.ro/ro/oferta/2-camere-dristor-semidecomandat-lux-balcon-metrou-IDGMen"

ALL_URLS = [EXPIRED_URL, CHECKED_URL]


class StoriaDetectionIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.scraper = StoriaScraper()
        results = self.scraper.scrape_batch(ALL_URLS)
        self.result_map = {r["url"]: r for r in results if r.get("url")}

    def test_confirmed_expired_listing_is_marked_expired(self):
        """IDGERe redirects away from /ro/oferta/ — must be classified as expired (0)."""
        self.assertIn(EXPIRED_URL, self.result_map)
        avail = self.result_map[EXPIRED_URL].get("is_available")
        self.assertEqual(avail, 0, f"Expected expired listing to have is_available=0, got {avail}")

    def test_blocked_page_is_not_falsely_expired(self):
        """IDGMen: if Cloudflare blocks the request, must return None (blocked), NOT 0 (expired)."""
        self.assertIn(CHECKED_URL, self.result_map)
        avail = self.result_map[CHECKED_URL].get("is_available")
        self.assertNotEqual(
            avail, 0,
            "Bot-blocked page was falsely classified as expired — redirect detection is misfiring"
        )
        # Acceptable outcomes: 1 (live, parsed successfully) or None (blocked, unchanged)
        self.assertIn(avail, (1, None), f"Unexpected is_available value: {avail}")

    def test_all_urls_return_a_result(self):
        """Every URL in the batch must produce a result entry (no silent drops)."""
        for url in ALL_URLS:
            with self.subTest(url=url):
                self.assertIn(url, self.result_map, f"No result returned for {url}")

    def test_successfully_parsed_listings_have_required_fields(self):
        """Any listing with is_available=1 must have title, url and platform_id."""
        for entry in self.result_map.values():
            if entry.get("is_available") == 1:
                with self.subTest(url=entry.get("url")):
                    self.assertTrue(entry.get("title"), "Missing title")
                    self.assertTrue(entry.get("url"), "Missing url")
                    self.assertEqual(entry.get("platform_id"), "storia")


if __name__ == "__main__":
    unittest.main()
