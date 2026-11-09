"""
Unit tests for crawler.ProxyRotator.apply_for_session platform gating.

History: proxy selection used to require every requested platform's health
check to pass. Imobiliare (DataDome) never passed, so it was excluded; then
in 2026-11 OLX started returning 403 to the entire Webshare range and the
same AND-gating failed every run: the loop burned its 60s budget, fell back
to NO proxy, and Storia (which genuinely needs one) was blocked on ~98% of
rechecks (380 of 19,189 on 2026-11-09), leaving most "available" Storia
listings unverified for weeks.

Now only Storia uses the session proxy (PROXIED_PLATFORMS) and only Storia
gates selection; OLX and Imobiliare always go direct.
"""
import os
import unittest
from unittest.mock import patch

from crawler import ProxyRotator


def _patched(rotator, **overrides):
    """Common patches: no state file, connectivity OK unless overridden."""
    return (
        patch.object(rotator, "_load_index", return_value=0),
        patch.object(rotator, "_save_index"),
        patch.object(rotator, "_verify", **({"return_value": True} | overrides)),
    )


class ApplyForSessionPlatformGatingTests(unittest.TestCase):
    """apply_for_session() has a real side effect beyond its return value:
    it sets the process-wide os.environ["PROXY_URL"] on success. Every test
    here must restore that (via patch.dict, which snapshots and restores the
    whole environment) — otherwise a fake proxy string leaks into every
    later test in the same process, including live-network tests that read
    PROXY_URL (e.g. tests/scrapers/storia/test_storia_live.py), silently routing them
    through a nonexistent proxy and turning a real HTTP call into a
    connection failure. This bit us once already: discovering the whole
    suite failed a live Storia test that passed in isolation."""

    def test_olx_is_not_a_gate_the_proxy_storia_accepts_is_chosen(self):
        rotator = ProxyRotator(["http://p1", "http://p2"])
        p_idx, p_save, p_verify = _patched(rotator)
        with patch.dict(os.environ, {}, clear=False), p_idx, p_save, p_verify, \
             patch.object(rotator, "_verify_for_storia", side_effect=[False, True]), \
             patch("scrapers.http.set_proxy") as mock_set_proxy:

            chosen = rotator.apply_for_session(check_platforms=["olx", "storia", "imobiliare"])

        self.assertEqual(chosen, "http://p2")
        mock_set_proxy.assert_called_once_with("http://p2")

    def test_there_is_no_olx_proxy_check_left_to_fail(self):
        # The regression: an OLX check that rejects every Webshare proxy.
        self.assertFalse(hasattr(ProxyRotator, "_verify_for_olx"))

    def test_chosen_proxy_is_exported_for_the_storia_subprocess(self):
        rotator = ProxyRotator(["http://p1"])
        p_idx, p_save, p_verify = _patched(rotator)
        with patch.dict(os.environ, {}, clear=False), p_idx, p_save, p_verify, \
             patch.object(rotator, "_verify_for_storia", return_value=True) as mock_storia, \
             patch("scrapers.http.set_proxy"):

            chosen = rotator.apply_for_session(check_platforms=["olx", "storia", "imobiliare"])
            proxy_env = os.environ.get("PROXY_URL")

        self.assertEqual(chosen, "http://p1")
        self.assertEqual(proxy_env, "http://p1")
        mock_storia.assert_called_once()

    def test_olx_only_run_skips_proxy_selection_entirely(self):
        rotator = ProxyRotator(["http://p1"])
        p_idx, p_save, p_verify = _patched(rotator)
        with patch.dict(os.environ, {"PROXY_URL": "http://stale"}, clear=False), \
             p_idx, p_save, p_verify as mock_verify, \
             patch.object(rotator, "_verify_for_storia") as mock_storia, \
             patch("scrapers.http.set_proxy") as mock_set_proxy:

            chosen = rotator.apply_for_session(check_platforms=["olx"])
            proxy_env = os.environ.get("PROXY_URL")

        self.assertIsNone(chosen)
        mock_verify.assert_not_called()      # no network checks wasted
        mock_storia.assert_not_called()
        mock_set_proxy.assert_called_once_with(None)
        self.assertIsNone(proxy_env)         # stale session proxy cleared

    def test_imobiliare_plus_olx_run_also_skips_selection(self):
        rotator = ProxyRotator(["http://p1"])
        p_idx, p_save, p_verify = _patched(rotator)
        with patch.dict(os.environ, {}, clear=False), p_idx, p_save, p_verify as mock_verify, \
             patch("scrapers.http.set_proxy"):
            chosen = rotator.apply_for_session(check_platforms=["olx", "imobiliare"])
        self.assertIsNone(chosen)
        mock_verify.assert_not_called()

    def test_storia_only_run_still_selects_a_proxy(self):
        rotator = ProxyRotator(["http://p1"])
        p_idx, p_save, p_verify = _patched(rotator)
        with patch.dict(os.environ, {}, clear=False), p_idx, p_save, p_verify, \
             patch.object(rotator, "_verify_for_storia", return_value=True), \
             patch("scrapers.http.set_proxy"):
            chosen = rotator.apply_for_session(check_platforms=["storia"])
        self.assertEqual(chosen, "http://p1")

    def test_no_platform_list_means_connectivity_only(self):
        rotator = ProxyRotator(["http://p1"])
        p_idx, p_save, p_verify = _patched(rotator)
        with patch.dict(os.environ, {}, clear=False), p_idx, p_save, p_verify, \
             patch.object(rotator, "_verify_for_storia") as mock_storia, \
             patch("scrapers.http.set_proxy"):
            chosen = rotator.apply_for_session()
        self.assertEqual(chosen, "http://p1")
        mock_storia.assert_not_called()

    def test_storia_blocked_on_every_proxy_falls_back_to_none(self):
        rotator = ProxyRotator(["http://p1", "http://p2"])
        p_idx, p_save, p_verify = _patched(rotator)
        with patch.dict(os.environ, {}, clear=False), p_idx, p_save, p_verify, \
             patch.object(rotator, "_verify_for_storia", return_value=False), \
             patch("scrapers.http.set_proxy") as mock_set_proxy:
            chosen = rotator.apply_for_session(check_platforms=["storia"])
        self.assertIsNone(chosen)
        mock_set_proxy.assert_called_once_with(None)

    def test_gives_up_after_the_time_budget_instead_of_checking_every_proxy(self):
        """BUGS.md #9a follow-up: each proxy check already has its own
        per-request timeout, but nothing bounded the whole loop -- a
        100-proxy pool that's mostly dead could in principle burn minutes
        checking every single one before giving up. This caps the total
        time spent regardless of how many proxies are left to try."""
        rotator = ProxyRotator([f"http://p{i}" for i in range(5)])
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(rotator, "_load_index", return_value=0), \
             patch.object(rotator, "_save_index"), \
             patch.object(rotator, "_verify", return_value=False) as mock_verify, \
             patch("crawler.time.time", side_effect=[0, 1, 2, 100]), \
             patch("scrapers.http.set_proxy") as mock_set_proxy:

            chosen = rotator.apply_for_session()

        self.assertIsNone(chosen)
        mock_set_proxy.assert_called_once_with(None)
        # Only 2 of the 5 proxies were actually checked before the time
        # budget kicked in -- not all 5, exhausted the normal way.
        self.assertEqual(mock_verify.call_count, 2)

    def test_empty_pool_returns_none_without_touching_anything(self):
        rotator = ProxyRotator([])
        with patch("scrapers.http.set_proxy") as mock_set_proxy:
            self.assertIsNone(rotator.apply_for_session(check_platforms=["storia"]))
        mock_set_proxy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
