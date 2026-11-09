"""
--recheck-after-hours plumbing: CLI flag -> run_availability_check ->
db_utils.get_listings_for_availability_check(skip_seen_within_hours=...).

Default is 12h so an automatic Cloud Run retry (or a manual re-run shortly
after) resumes instead of redoing listings the previous attempt just
confirmed. 0 disables the skip entirely.
"""
import sys
import unittest
from unittest.mock import patch, MagicMock

import crawler


class RunAvailabilityCheckPassesWindowTests(unittest.TestCase):
    def _run(self, **kwargs):
        with patch("db_utils.start_availability_check_log", return_value=1), \
             patch("db_utils.get_listings_for_availability_check", return_value=[]) as mock_get, \
             patch("db_utils.finish_availability_check_log"):
            crawler.run_availability_check(**kwargs)
        return mock_get

    def test_window_is_forwarded_to_the_query(self):
        mock_get = self._run(skip_seen_within_hours=12)
        mock_get.assert_called_once_with(limit=None, skip_seen_within_hours=12)

    def test_default_is_no_window(self):
        mock_get = self._run()
        mock_get.assert_called_once_with(limit=None, skip_seen_within_hours=None)

    def test_limit_and_window_are_both_forwarded(self):
        mock_get = self._run(limit=50, skip_seen_within_hours=6)
        mock_get.assert_called_once_with(limit=50, skip_seen_within_hours=6)


class MainCliFlagTests(unittest.TestCase):
    def _main(self, extra_args):
        argv = ["crawler.py", "--mode", "availability-check"] + extra_args
        rotator = MagicMock()
        with patch.object(sys, "argv", argv), \
             patch.object(crawler.ProxyRotator, "from_config", return_value=rotator), \
             patch.object(crawler, "run_availability_check") as mock_run:
            with self.assertRaises(SystemExit):
                crawler.main()
        return mock_run

    def test_default_window_is_12_hours(self):
        mock_run = self._main([])
        self.assertEqual(mock_run.call_args.kwargs["skip_seen_within_hours"], 12.0)

    def test_custom_window(self):
        mock_run = self._main(["--recheck-after-hours", "3"])
        self.assertEqual(mock_run.call_args.kwargs["skip_seen_within_hours"], 3.0)

    def test_zero_disables_the_skip(self):
        mock_run = self._main(["--recheck-after-hours", "0"])
        self.assertIsNone(mock_run.call_args.kwargs["skip_seen_within_hours"])


if __name__ == "__main__":
    unittest.main()
