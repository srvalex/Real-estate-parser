"""
Tests for the availability_check_logs wiring in crawler.run_availability_check.

Same contract as crawl_run_logs: start before doing anything, finish with
real counters on success (including the "nothing to check" early-return
path, which must still log a completed run with zero counts rather than
leaving nothing behind), and finish as 'failed' with the exception's
message if the check itself raises — while still letting that exception
propagate.
"""
import unittest
from unittest.mock import patch, MagicMock

import crawler


class RunAvailabilityCheckLoggingTests(unittest.TestCase):
    def test_nothing_to_check_still_logs_a_completed_run(self):
        with patch("db_utils.start_availability_check_log", return_value=11) as mock_start, \
             patch("db_utils.get_listings_for_availability_check", return_value=[]), \
             patch("db_utils.finish_availability_check_log") as mock_finish:

            crawler.run_availability_check(platforms=["olx"])

        mock_start.assert_called_once_with(platforms=["olx"])
        mock_finish.assert_called_once_with(
            11, listings_checked=0, listings_expired=0, listings_blocked=0,
            status="success", error_message=None,
        )

    def test_successful_run_logs_real_counters(self):
        fake_listings = [{"platform_id": "olx", "url": "https://a"}]
        fake_scraper = MagicMock()
        fake_scraper.scrape_listing_with_status.return_value = {"status": "expired"}

        with patch("db_utils.start_availability_check_log", return_value=22) as mock_start, \
             patch("db_utils.get_listings_for_availability_check", return_value=fake_listings), \
             patch("db_utils.batch_update_availability"), \
             patch("db_utils.save_to_db"), \
             patch("db_utils.finish_availability_check_log") as mock_finish, \
             patch.object(crawler, "SCRAPERS", {"olx": fake_scraper}), \
             patch("crawler.time.sleep"):

            crawler.run_availability_check()

        mock_start.assert_called_once_with(platforms=None)
        finish_kwargs = mock_finish.call_args.kwargs
        self.assertEqual(mock_finish.call_args.args[0], 22)
        self.assertEqual(finish_kwargs["listings_checked"], 1)
        self.assertEqual(finish_kwargs["listings_expired"], 1)
        self.assertEqual(finish_kwargs["status"], "success")

    def test_exception_is_logged_as_failed_and_still_reraised(self):
        with patch("db_utils.start_availability_check_log", return_value=33) as mock_start, \
             patch("db_utils.get_listings_for_availability_check", side_effect=RuntimeError("db down")), \
             patch("db_utils.finish_availability_check_log") as mock_finish:

            with self.assertRaises(RuntimeError):
                crawler.run_availability_check()

        mock_finish.assert_called_once()
        finish_kwargs = mock_finish.call_args.kwargs
        self.assertEqual(finish_kwargs["status"], "failed")
        self.assertIn("db down", finish_kwargs["error_message"])


if __name__ == "__main__":
    unittest.main()
