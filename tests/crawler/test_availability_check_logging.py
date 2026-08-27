"""
Tests for the availability_check_logs wiring in crawler.run_availability_check.

Same contract as crawl_run_logs: start before doing anything, finish with
real counters on success (including the "nothing to check" early-return
path, which must still log a completed run with zero counts rather than
leaving nothing behind), and finish as 'failed' with the exception's
message if the check itself raises — while still letting that exception
propagate.

Blocked listings: a listing whose recheck comes back "blocked" (transient
failure, bot challenge, rate limit — not a definitive answer) must never be
written to the DB at all, so it keeps its current is_available value and
stays eligible for get_listings_for_availability_check's next run — that's
the entire retry mechanism, there's no separate queue or backoff state.
Found (2026-08-27) that the OLX branch counted a blocked result toward
listings_checked and never toward listings_blocked at all — inconsistent
with the Storia/Imobiliare branch, which already got this right — making
the logged counts inaccurate even though the retry itself worked correctly
either way. Fixed to match: total_checked only increments on a definitive
(expired/success) result.
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

    def test_olx_blocked_listing_is_counted_as_blocked_not_checked_and_left_untouched(self):
        fake_listings = [{"platform_id": "olx", "url": "https://blocked-1"}]
        fake_scraper = MagicMock()
        fake_scraper.scrape_listing_with_status.return_value = {"status": "blocked"}

        with patch("db_utils.start_availability_check_log", return_value=44), \
             patch("db_utils.get_listings_for_availability_check", return_value=fake_listings), \
             patch("db_utils.batch_update_availability") as mock_batch_update, \
             patch("db_utils.save_to_db") as mock_save, \
             patch("db_utils.finish_availability_check_log") as mock_finish, \
             patch.object(crawler, "SCRAPERS", {"olx": fake_scraper}), \
             patch("crawler.time.sleep"):

            crawler.run_availability_check(platforms=["olx"])

        mock_batch_update.assert_not_called()
        mock_save.assert_not_called()

        finish_kwargs = mock_finish.call_args.kwargs
        self.assertEqual(finish_kwargs["listings_checked"], 0)
        self.assertEqual(finish_kwargs["listings_blocked"], 1)
        self.assertEqual(finish_kwargs["listings_expired"], 0)

    def test_storia_blocked_listing_is_counted_as_blocked_not_checked_and_left_untouched(self):
        fake_listings = [{"platform_id": "storia", "url": "https://blocked-2"}]
        fake_scraper = MagicMock()
        fake_scraper.scrape_batch.return_value = [
            {"url": "https://blocked-2", "is_available": None, "status": "blocked"},
        ]

        with patch("db_utils.start_availability_check_log", return_value=55), \
             patch("db_utils.get_listings_for_availability_check", return_value=fake_listings), \
             patch("db_utils.batch_update_availability") as mock_batch_update, \
             patch("db_utils.save_to_db") as mock_save, \
             patch("db_utils.finish_availability_check_log") as mock_finish, \
             patch.object(crawler, "SCRAPERS", {"storia": fake_scraper}), \
             patch("crawler.time.sleep"):

            crawler.run_availability_check(platforms=["storia"])

        mock_batch_update.assert_not_called()
        mock_save.assert_not_called()

        finish_kwargs = mock_finish.call_args.kwargs
        self.assertEqual(finish_kwargs["listings_checked"], 0)
        self.assertEqual(finish_kwargs["listings_blocked"], 1)

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
