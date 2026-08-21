"""
Unit tests for crawler.ProxyRotator's OLX health check.

OLX was the only scraped platform with no proxy-specific verification —
Storia and Imobiliare both had one. A proxy that passes generic
connectivity (api.ipify.org) but is already rate-limited or challenged by
OLX would silently produce "blocked" results for every listing routed
through it, indistinguishable from a real classification bug. These tests
cover the new _verify_for_olx check and its wiring into apply_for_session.
"""
import os
import unittest
from unittest.mock import patch, MagicMock

from crawler import ProxyRotator


def _fake_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


class VerifyForOlxTests(unittest.TestCase):
    def test_returns_true_when_search_page_has_listing_cards(self):
        rotator = ProxyRotator(["http://user:pass@proxy:1"])
        with patch("curl_cffi.requests.get", return_value=_fake_response(200, text='<div data-cy="l-card">x</div>')):
            self.assertTrue(rotator._verify_for_olx("http://user:pass@proxy:1"))

    def test_returns_false_when_challenge_page_has_no_listing_cards(self):
        rotator = ProxyRotator(["http://user:pass@proxy:1"])
        with patch("curl_cffi.requests.get", return_value=_fake_response(200, text="<html>captcha</html>")):
            self.assertFalse(rotator._verify_for_olx("http://user:pass@proxy:1"))

    def test_returns_false_on_non_200_status(self):
        rotator = ProxyRotator(["http://user:pass@proxy:1"])
        with patch("curl_cffi.requests.get", return_value=_fake_response(403, text='<div data-cy="l-card">x</div>')):
            self.assertFalse(rotator._verify_for_olx("http://user:pass@proxy:1"))

    def test_returns_false_on_request_exception(self):
        rotator = ProxyRotator(["http://user:pass@proxy:1"])
        with patch("curl_cffi.requests.get", side_effect=ConnectionError("boom")):
            self.assertFalse(rotator._verify_for_olx("http://user:pass@proxy:1"))


class ApplyForSessionOlxGatingTests(unittest.TestCase):
    """apply_for_session() has a real side effect beyond its return value:
    it sets the process-wide os.environ["PROXY_URL"] on success. Every test
    here must restore that (via patch.dict, which snapshots and restores the
    whole environment) — otherwise a fake proxy string leaks into every
    later test in the same process, including live-network tests that read
    PROXY_URL (e.g. tests/test_storia_live.py), silently routing them
    through a nonexistent proxy and turning a real HTTP call into a
    connection failure. This bit us once already: discovering the whole
    suite failed a live Storia test that passed in isolation."""

    def test_proxy_blocked_by_olx_is_skipped_in_favour_of_the_next_one(self):
        rotator = ProxyRotator(["http://p1", "http://p2"])
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(rotator, "_load_index", return_value=0), \
             patch.object(rotator, "_save_index"), \
             patch.object(rotator, "_verify", return_value=True), \
             patch.object(rotator, "_verify_for_olx", side_effect=[False, True]), \
             patch("scrapers.http.set_proxy") as mock_set_proxy:

            chosen = rotator.apply_for_session(check_platforms=["olx"])

        self.assertEqual(chosen, "http://p2")
        mock_set_proxy.assert_called_once_with("http://p2")

    def test_olx_check_is_skipped_when_olx_not_in_check_platforms(self):
        rotator = ProxyRotator(["http://p1"])
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(rotator, "_load_index", return_value=0), \
             patch.object(rotator, "_save_index"), \
             patch.object(rotator, "_verify", return_value=True), \
             patch.object(rotator, "_verify_for_olx") as mock_verify_olx, \
             patch.object(rotator, "_verify_for_storia", return_value=True), \
             patch("scrapers.http.set_proxy"):

            chosen = rotator.apply_for_session(check_platforms=["storia"])

        mock_verify_olx.assert_not_called()
        self.assertEqual(chosen, "http://p1")


if __name__ == "__main__":
    unittest.main()
