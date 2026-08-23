"""
Tests for the crawl_run_logs wiring in crawler.run_full_crawl /
run_incremental_crawl.

Both functions must: start a log row before doing any work, finish it with
the real listings_new count on success, and — critically — still finish it
(with status='failed' and the error captured) if the crawl itself raises,
rather than leaving a 'running' row stuck forever. The exception must still
propagate afterward; logging must never swallow a real crawl failure.

Per-platform isolation: the whole `for pid in platforms` loop used to sit
inside one try/except, so an unexpected error crawling platform N aborted
every platform queued after it in the same run — not just skipped, never
even attempted. Each platform's crawl is now caught individually: if some
platforms succeed and others don't, the run finishes with
status='partial_failure' and every failed platform named in error_message,
rather than raising and discarding whatever the working platforms found.
If EVERY platform in the run failed, that's still a full failure (raise,
status='failed') — there's nothing partial about it.
"""
import unittest
from unittest.mock import patch, MagicMock

import crawler


class RunFullCrawlLoggingTests(unittest.TestCase):
    def test_success_starts_and_finishes_the_log(self):
        # Empty platforms/districts -> the crawl loop body never executes,
        # exercising only the logging wrapper with zero scraping machinery.
        with patch("db_utils.start_crawl_run_log", return_value=99) as mock_start, \
             patch("db_utils.finish_crawl_run_log") as mock_finish, \
             patch.object(crawler._http, "get_proxy", return_value=None):

            result = crawler.run_full_crawl(
                conn=MagicMock(), platforms=[], districts={}, max_price=1200, max_pages=10,
            )

        self.assertEqual(result, 0)
        mock_start.assert_called_once()
        start_kwargs = mock_start.call_args.kwargs
        self.assertEqual(start_kwargs["mode"], "full")
        self.assertEqual(start_kwargs["platforms"], [])
        self.assertEqual(start_kwargs["max_price"], 1200)
        self.assertEqual(start_kwargs["max_pages"], 10)

        mock_finish.assert_called_once()
        finish_kwargs = mock_finish.call_args.kwargs
        self.assertEqual(mock_finish.call_args.args[0], 99)  # run_id
        self.assertEqual(finish_kwargs["listings_new"], 0)
        self.assertEqual(finish_kwargs["status"], "success")

    def test_max_price_zero_is_logged_as_none_not_zero(self):
        """max_price=0 means 'no filter' in this codebase's convention —
        the log should reflect that as NULL, not a misleading literal 0."""
        with patch("db_utils.start_crawl_run_log", return_value=1) as mock_start, \
             patch("db_utils.finish_crawl_run_log"), \
             patch.object(crawler._http, "get_proxy", return_value=None):

            crawler.run_full_crawl(conn=MagicMock(), platforms=[], districts={}, max_price=0)

        self.assertIsNone(mock_start.call_args.kwargs["max_price"])

    def test_proxy_credentials_are_never_logged(self):
        with patch("db_utils.start_crawl_run_log", return_value=1) as mock_start, \
             patch("db_utils.finish_crawl_run_log"), \
             patch.object(crawler._http, "get_proxy", return_value="http://user:secret@1.2.3.4:8080"):

            crawler.run_full_crawl(conn=MagicMock(), platforms=[], districts={})

        proxy_display = mock_start.call_args.kwargs["proxy_display"]
        self.assertNotIn("secret", proxy_display)
        self.assertNotIn("user", proxy_display)
        self.assertEqual(proxy_display, "1.2.3.4:8080")

    def test_exception_is_logged_as_failed_and_still_reraised(self):
        with patch("db_utils.start_crawl_run_log", return_value=99) as mock_start, \
             patch("db_utils.finish_crawl_run_log") as mock_finish, \
             patch.object(crawler._http, "get_proxy", return_value=None), \
             patch("crawler._collect_page", side_effect=RuntimeError("boom")):

            with self.assertRaises(RuntimeError):
                crawler.run_full_crawl(
                    conn=MagicMock(), platforms=["olx"],
                    districts={"Sector 1": ["Some Neighbourhood"]},
                )

        mock_finish.assert_called_once()
        finish_kwargs = mock_finish.call_args.kwargs
        self.assertEqual(finish_kwargs["status"], "failed")
        self.assertIn("boom", finish_kwargs["error_message"])

    def test_one_platform_failing_does_not_stop_the_others(self):
        """BUGS.md finding: the whole per-platform loop used to sit inside a
        single try/except, so an unexpected error crawling one platform
        aborted every platform queued after it in the same run. olx is
        listed first and always raises here; storia must still be crawled
        and its listings still saved."""
        def fake_collect_page(scraper, search_url, page_num):
            if scraper.platform_id == "olx":
                raise RuntimeError("olx boom")
            # storia: one page of new links, then an empty page to stop paging.
            return ["https://www.storia.ro/a", "https://www.storia.ro/b"] if page_num == 1 else []

        with patch("db_utils.start_crawl_run_log", return_value=1) as mock_start, \
             patch("db_utils.finish_crawl_run_log") as mock_finish, \
             patch.object(crawler._http, "get_proxy", return_value=None), \
             patch("crawler._collect_page", side_effect=fake_collect_page), \
             patch("crawler._known_urls", return_value=set()), \
             patch("crawler._scrape_and_save", return_value=2) as mock_save:

            result = crawler.run_full_crawl(
                conn=MagicMock(), platforms=["olx", "storia"],
                districts={"Sector 1": ["Some Neighbourhood"]},
            )

        # storia's listings still got saved despite olx blowing up first.
        self.assertEqual(result, 2)
        mock_save.assert_called_once()
        saved_by_platform = mock_save.call_args.args[1]
        self.assertIn("storia", saved_by_platform)

        finish_kwargs = mock_finish.call_args.kwargs
        self.assertEqual(finish_kwargs["status"], "partial_failure")
        self.assertIn("olx", finish_kwargs["error_message"])
        self.assertIn("boom", finish_kwargs["error_message"])


class RunIncrementalCrawlLoggingTests(unittest.TestCase):
    def test_success_starts_and_finishes_the_log_with_stop_threshold(self):
        with patch("db_utils.start_crawl_run_log", return_value=5) as mock_start, \
             patch("db_utils.finish_crawl_run_log") as mock_finish, \
             patch.object(crawler._http, "get_proxy", return_value=None):

            result = crawler.run_incremental_crawl(
                conn=MagicMock(), platforms=[], districts={}, stop_threshold=0.9,
            )

        self.assertEqual(result, 0)
        start_kwargs = mock_start.call_args.kwargs
        self.assertEqual(start_kwargs["mode"], "incremental")
        self.assertEqual(start_kwargs["stop_threshold"], 0.9)
        mock_finish.assert_called_once_with(
            5, listings_new=0, status="success", error_message=None,
        )

    def test_exception_is_logged_as_failed_and_still_reraised(self):
        with patch("db_utils.start_crawl_run_log", return_value=5) as mock_start, \
             patch("db_utils.finish_crawl_run_log") as mock_finish, \
             patch.object(crawler._http, "get_proxy", return_value=None), \
             patch("crawler._collect_page", side_effect=RuntimeError("kaboom")):

            with self.assertRaises(RuntimeError):
                crawler.run_incremental_crawl(
                    conn=MagicMock(), platforms=["olx"],
                    districts={"Sector 1": ["Some Neighbourhood"]},
                )

        finish_kwargs = mock_finish.call_args.kwargs
        self.assertEqual(finish_kwargs["status"], "failed")
        self.assertIn("kaboom", finish_kwargs["error_message"])

    def test_one_platform_failing_does_not_stop_the_others(self):
        def fake_collect_page(scraper, search_url, page_num):
            if scraper.platform_id == "olx":
                raise RuntimeError("olx boom")
            return ["https://www.storia.ro/a", "https://www.storia.ro/b"] if page_num == 1 else []

        with patch("db_utils.start_crawl_run_log", return_value=1) as mock_start, \
             patch("db_utils.finish_crawl_run_log") as mock_finish, \
             patch.object(crawler._http, "get_proxy", return_value=None), \
             patch("crawler._collect_page", side_effect=fake_collect_page), \
             patch("crawler._known_urls", return_value=set()), \
             patch("crawler._scrape_and_save", return_value=2) as mock_save:

            result = crawler.run_incremental_crawl(
                conn=MagicMock(), platforms=["olx", "storia"],
                districts={"Sector 1": ["Some Neighbourhood"]},
            )

        self.assertEqual(result, 2)
        mock_save.assert_called_once()
        saved_by_platform = mock_save.call_args.args[1]
        self.assertIn("storia", saved_by_platform)

        finish_kwargs = mock_finish.call_args.kwargs
        self.assertEqual(finish_kwargs["status"], "partial_failure")
        self.assertIn("olx", finish_kwargs["error_message"])
        self.assertIn("boom", finish_kwargs["error_message"])


if __name__ == "__main__":
    unittest.main()
