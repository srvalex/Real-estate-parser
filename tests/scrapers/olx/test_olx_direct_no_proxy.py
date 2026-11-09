"""
OLX must never go through the session proxy.

2026-11-09: OLX returns 403 to the entire Webshare datacenter range (12/12
proxies tested from outside GCP, 89/100 in the crawler job) but serves Cloud
Run's own egress IP fine (3,120 of 3,121 rechecks unproxied). Routing OLX
through the session proxy -- which the crawler sets for Storia -- would turn
every OLX request into a 403/"blocked".
"""
import unittest
from unittest.mock import patch, MagicMock

import scrapers.http as _http
from scrapers.olx import OLXScraper

PROXY = "http://user:secret@1.2.3.4:8080"


def _resp(status=200, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


class OlxIgnoresSessionProxyTests(unittest.TestCase):
    def setUp(self):
        _http.set_proxy(PROXY)
        self.addCleanup(_http.set_proxy, None)

    def test_listing_recheck_sends_no_proxy(self):
        with patch("curl_cffi.requests.get", return_value=_resp(410)) as mock_get:
            OLXScraper().scrape_listing_with_status("https://www.olx.ro/d/oferta/x-ID1.html")

        kwargs = mock_get.call_args.kwargs
        self.assertFalse(kwargs.get("proxies"), f"OLX request used a proxy: {kwargs.get('proxies')}")

    def test_search_page_fetch_bypasses_the_session_proxy(self):
        with patch("scrapers.olx.get_content", return_value=None) as mock_content:
            OLXScraper().collect_links("https://www.olx.ro/imobiliare/", 2)

        self.assertEqual(mock_content.call_count, 2)
        for call in mock_content.call_args_list:
            self.assertIs(call.kwargs.get("use_proxy"), False)

    def test_get_content_with_use_proxy_false_really_sends_no_proxy(self):
        with patch("scrapers.http.requests.get", return_value=_resp(200, "<html/>")) as mock_get:
            _http.get_content("https://www.olx.ro/x", use_proxy=False)

        self.assertIsNone(mock_get.call_args.kwargs.get("proxies"))


class StoriaStillUsesTheSessionProxyTests(unittest.TestCase):
    """The flip side: only OLX/Imobiliare were taken off the proxy."""

    def setUp(self):
        _http.set_proxy(PROXY)
        self.addCleanup(_http.set_proxy, None)

    def test_default_get_content_still_uses_the_session_proxy(self):
        with patch("scrapers.http.requests.get", return_value=_resp(200, "<html/>")) as mock_get:
            _http.get_content("https://www.storia.ro/x")

        self.assertEqual(mock_get.call_args.kwargs["proxies"], {"https": PROXY, "http": PROXY})


if __name__ == "__main__":
    unittest.main()
