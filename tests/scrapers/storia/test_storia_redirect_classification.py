"""
Regression tests for _fetch_batch_raw's redirect handling in scrapers/storia.py.

Bug: the old code trusted the *shape of the final URL* as a standalone
expiry signal — "redirected away from /ro/oferta/ → expired" — before ever
looking at the page content. Storia's bot-protection can also redirect off
that path when it blocks a request (not just when a listing is genuinely
gone), so a bot-challenge page was silently stamped "expired" instead of
"blocked". Confirmed against live Storia listings on 2026-08-22 (see
tests/scrapers/storia/test_storia_live.py's now-stale CHECKED_URL, which expired for real
between when that test was written and when it was run — a separate,
inherent flakiness of asserting fixed outcomes against mutable real
listings, which is exactly why this fix is covered here with synthetic
fixtures instead).

Fix: classification is now made purely from response content via
classify_storia_page, regardless of what URL the request landed on.
classify_storia_page already correctly distinguishes:
  - genuine redirect to home/search (NEXT_DATA present, no `ad` key) → expired
  - bot-challenge page (no NEXT_DATA, no expired marker)             → blocked
  - the live ad itself                                               → success
These tests exercise that behavior through the public scrape_batch() entry
point, with curl_cffi mocked out — no live network, no dependency on any
real listing's current state.
"""

import unittest
from unittest.mock import patch, MagicMock

from scrapers.storia import StoriaScraper

BOT_CHALLENGE_HTML = "<html><body>Just checking your browser before continuing...</body></html>"

REDIRECTED_TO_HOME_HTML = """
<html><body>
<script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {}}}</script>
</body></html>
"""

LIVE_AD_HTML = """
<html><body>
<script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {"ad": {"id": 123, "title": "Nice flat"}}}}</script>
</body></html>
"""


def _fake_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    return resp


class StoriaRedirectClassificationTests(unittest.TestCase):
    def test_bot_challenge_page_is_blocked_not_expired(self):
        """A redirect that lands on a page with no NEXT_DATA and no expired
        marker is a bot block, not a removed listing — must NOT be
        classified as expired (is_available=0)."""
        with patch("scrapers.storia.cffi_requests.get", return_value=_fake_response(BOT_CHALLENGE_HTML)):
            results = StoriaScraper().scrape_batch(["https://www.storia.ro/ro/oferta/some-listing-ID123"])

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["is_available"], "bot-blocked page must not be falsely marked expired")

    def test_redirect_to_home_or_search_page_is_still_expired(self):
        """A redirect landing on a real Storia page (NEXT_DATA present) with
        no `ad` key is a genuine removed-listing signal and must still be
        classified as expired — this behavior must survive the fix."""
        with patch("scrapers.storia.cffi_requests.get", return_value=_fake_response(REDIRECTED_TO_HOME_HTML)):
            results = StoriaScraper().scrape_batch(["https://www.storia.ro/ro/oferta/some-listing-ID456"])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["is_available"], 0)

    def test_live_ad_is_parsed_successfully_based_on_content_alone(self):
        """Classification must depend only on page content — the response's
        final URL is no longer inspected at all."""
        with patch("scrapers.storia.cffi_requests.get", return_value=_fake_response(LIVE_AD_HTML)):
            results = StoriaScraper().scrape_batch(["https://www.storia.ro/ro/oferta/some-listing-ID789"])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["is_available"], 1)
        self.assertEqual(results[0]["title"], "Nice flat")


if __name__ == "__main__":
    unittest.main()
