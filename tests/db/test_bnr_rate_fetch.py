"""
Tests for the live BNR (Romanian National Bank) RON/EUR rate fetch, caching,
and fallback logic in db_utils.py.

This logic lives in db_utils.py, not streamlit_interface/pipeline/utils.py,
even though the pipeline module was its original and (for a while) only
caller: db_utils.py is the Streamlit-independent foundational layer, reused
by crawler.py and, per MIGRATION_PLAN.md, the future API — a SQL-level price
filter needs this rate without pulling in a Streamlit dependency to get it.
pipeline/utils.py now imports get_ron_to_eur_rate/price_in_eur from here.

_fetch_bnr_eur_rate() talks to https://curs.bnr.ro/nbrfxrates.xml directly
and is intentionally strict (raises on any problem) — get_ron_to_eur_rate()
centralises all fallback behaviour so a currency comparison never breaks
just because BNR's site is briefly unreachable.
"""
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import db_utils

# Trimmed but structurally real sample -- captured live from
# https://curs.bnr.ro/nbrfxrates.xml on 2026-08-21 (namespace, element
# names, and the no-multiplier-on-EUR shape are all real, not guessed).
SAMPLE_BNR_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<DataSet xmlns="https://www.bnr.ro/xsd" xmlns:xsi="https://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="https://curs.bnr.ro/xsd/nbrfxrates.xsd"><Header><Publisher>National Bank of Romania</Publisher><PublishingDate>2026-08-21</PublishingDate><MessageType>DR</MessageType></Header><Body><Subject>Reference rates</Subject><OrigCurrency>RON</OrigCurrency><Cube date="2026-08-21"><Rate currency="USD">4.4926</Rate><Rate currency="EUR">5.2581</Rate><Rate currency="HUF" multiplier="100">1.4467</Rate></Cube></Body></DataSet>"""


def _fake_response(content: bytes, ok: bool = True) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    if ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = Exception("HTTP error")
    return resp


class FetchBnrEurRateTests(unittest.TestCase):
    def test_parses_eur_rate_from_real_shaped_feed(self):
        with patch("requests.get", return_value=_fake_response(SAMPLE_BNR_XML)):
            rate = db_utils._fetch_bnr_eur_rate()
        self.assertAlmostEqual(rate, 5.2581, places=4)

    def test_raises_if_eur_missing_from_feed(self):
        xml_without_eur = SAMPLE_BNR_XML.replace(b'<Rate currency="EUR">5.2581</Rate>', b"")
        with patch("requests.get", return_value=_fake_response(xml_without_eur)):
            with self.assertRaises(ValueError):
                db_utils._fetch_bnr_eur_rate()

    def test_raises_on_http_error(self):
        with patch("requests.get", return_value=_fake_response(SAMPLE_BNR_XML, ok=False)):
            with self.assertRaises(Exception):
                db_utils._fetch_bnr_eur_rate()

    def test_raises_on_malformed_xml(self):
        with patch("requests.get", return_value=_fake_response(b"not xml at all")):
            with self.assertRaises(Exception):
                db_utils._fetch_bnr_eur_rate()

    def test_applies_multiplier_when_present(self):
        """Not realistic for EUR specifically today, but confirms the
        multiplier attribute (used by e.g. HUF/JPY in the real feed) is
        honoured, in case BNR ever adds one for EUR."""
        xml = SAMPLE_BNR_XML.replace(
            b'<Rate currency="EUR">5.2581</Rate>',
            b'<Rate currency="EUR" multiplier="100">525.81</Rate>',
        )
        with patch("requests.get", return_value=_fake_response(xml)):
            rate = db_utils._fetch_bnr_eur_rate()
        self.assertAlmostEqual(rate, 5.2581, places=4)


class GetRonToEurRateCachingTests(unittest.TestCase):
    """BNR publishes exactly once per Bucharest calendar day (13:00) -- the
    cache is keyed on that day, not a rolling TTL, so a fetch happens at
    most once per day regardless of how many times get_ron_to_eur_rate()
    is called."""

    def setUp(self):
        # Module-level cache is shared mutable state -- reset it before
        # every test so they can't leak into each other.
        db_utils._rate_cache["rate"] = None
        db_utils._rate_cache["fetched_date"] = None
        db_utils._rate_cache["last_attempt"] = 0.0

    def test_successful_fetch_is_cached_and_not_refetched_same_day(self):
        with patch.object(db_utils, "_fetch_bnr_eur_rate", return_value=5.25) as mock_fetch:
            first = db_utils.get_ron_to_eur_rate()
            second = db_utils.get_ron_to_eur_rate()
        self.assertEqual(first, 5.25)
        self.assertEqual(second, 5.25)
        mock_fetch.assert_called_once()

    def test_refetches_on_a_new_bucharest_day(self):
        with patch.object(db_utils, "_fetch_bnr_eur_rate", return_value=5.25):
            db_utils.get_ron_to_eur_rate()
        # Simulate "yesterday" regardless of what day it actually is today.
        db_utils._rate_cache["fetched_date"] = date(2000, 1, 1)
        db_utils._rate_cache["last_attempt"] -= db_utils._RATE_RETRY_BACKOFF_SECONDS + 1

        with patch.object(db_utils, "_fetch_bnr_eur_rate", return_value=5.30) as mock_fetch2:
            result = db_utils.get_ron_to_eur_rate()

        self.assertEqual(result, 5.30)
        mock_fetch2.assert_called_once()

    def test_falls_back_to_fixed_constant_when_never_fetched_and_fetch_fails(self):
        with patch.object(db_utils, "_fetch_bnr_eur_rate", side_effect=Exception("network down")):
            result = db_utils.get_ron_to_eur_rate()
        self.assertEqual(result, db_utils._FALLBACK_RON_TO_EUR_RATE)

    def test_falls_back_to_last_known_rate_when_todays_fetch_fails(self):
        with patch.object(db_utils, "_fetch_bnr_eur_rate", return_value=5.25):
            db_utils.get_ron_to_eur_rate()
        db_utils._rate_cache["fetched_date"] = date(2000, 1, 1)
        db_utils._rate_cache["last_attempt"] -= db_utils._RATE_RETRY_BACKOFF_SECONDS + 1

        with patch.object(db_utils, "_fetch_bnr_eur_rate", side_effect=Exception("network down")):
            result = db_utils.get_ron_to_eur_rate()

        self.assertEqual(result, 5.25, "must serve yesterday's real rate, not the hardcoded fallback")

    def test_does_not_hammer_the_network_during_a_sustained_outage_from_the_start(self):
        """Regression: the backoff check originally only applied when a
        rate had already been cached at least once -- meaning if BNR
        failed on the very first call ever, every subsequent call kept
        retrying the network with no backoff at all."""
        with patch.object(db_utils, "_fetch_bnr_eur_rate", side_effect=Exception("down")) as mock_fetch:
            db_utils.get_ron_to_eur_rate()
            db_utils.get_ron_to_eur_rate()
            db_utils.get_ron_to_eur_rate()
        self.assertEqual(mock_fetch.call_count, 1, "must back off, not retry the network on every call")

    def test_does_not_hammer_the_network_during_a_sustained_outage_on_a_new_day(self):
        with patch.object(db_utils, "_fetch_bnr_eur_rate", return_value=5.25):
            db_utils.get_ron_to_eur_rate()
        db_utils._rate_cache["fetched_date"] = date(2000, 1, 1)
        db_utils._rate_cache["last_attempt"] -= db_utils._RATE_RETRY_BACKOFF_SECONDS + 1

        with patch.object(db_utils, "_fetch_bnr_eur_rate", side_effect=Exception("down")) as mock_fetch:
            db_utils.get_ron_to_eur_rate()
            db_utils.get_ron_to_eur_rate()
        self.assertEqual(mock_fetch.call_count, 1, "must back off after the first failed retry too")


class PriceInEurTests(unittest.TestCase):
    def setUp(self):
        self._patch = patch.object(db_utils, "get_ron_to_eur_rate", return_value=5.0)
        self.mock_rate = self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_eur_price_passes_through_unchanged(self):
        self.assertEqual(db_utils.price_in_eur(500.0, "EUR"), 500.0)

    def test_ron_price_is_converted_using_the_current_rate(self):
        result = db_utils.price_in_eur(2000.0, "RON")
        self.assertAlmostEqual(result, 2000.0 / 5.0, places=4)

    def test_missing_currency_defaults_to_eur(self):
        self.assertEqual(db_utils.price_in_eur(500.0, None), 500.0)

    def test_currency_is_case_insensitive(self):
        result = db_utils.price_in_eur(2000.0, "ron")
        self.assertAlmostEqual(result, 2000.0 / 5.0, places=4)

    def test_none_price_returns_none(self):
        self.assertIsNone(db_utils.price_in_eur(None, "EUR"))

    def test_nan_price_returns_none(self):
        self.assertIsNone(db_utils.price_in_eur(float("nan"), "EUR"))

    def test_unparseable_price_returns_none(self):
        self.assertIsNone(db_utils.price_in_eur("not a number", "EUR"))

    def test_eur_price_never_triggers_a_rate_lookup(self):
        """A EUR price needs no conversion at all -- must not pay for a
        BNR fetch (or even a cache read) it doesn't need."""
        db_utils.price_in_eur(500.0, "EUR")
        self.mock_rate.assert_not_called()


class LiveBnrFeedSmokeTest(unittest.TestCase):
    """Narrow, real-network check that the actual BNR endpoint is reachable
    and returns a plausible EUR rate. Kept separate from the deterministic
    suite above for the same reason as tests/scrapers/storia/test_storia_live.py:
    a live external dependency belongs in its own narrow, clearly-labelled
    check, not mixed into tests that must stay fast and network-free."""

    def test_real_bnr_feed_returns_a_plausible_eur_rate(self):
        rate = db_utils._fetch_bnr_eur_rate()
        self.assertTrue(3.0 < rate < 8.0, f"RON/EUR rate {rate} is outside a sane historical range")


if __name__ == "__main__":
    unittest.main()
