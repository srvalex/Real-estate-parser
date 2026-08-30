"""
Tests for the core orchestration logic in crawler.run_full_crawl /
run_incremental_crawl / run_availability_check -- dedup, pagination,
early-exit, and per-platform dispatch.

BUGS.md #9a follow-up: before this file, only the start/finish logging
wrapper (tests/crawler/test_crawl_run_logging.py) and per-platform
exception isolation had direct coverage. The actual crawl mechanics that
run on every scheduled production execution -- skipping already-known
URLs, stopping at max_pages, the incremental early-exit threshold, and
respecting a --platform filter -- had none.
"""
import unittest
from unittest.mock import patch, MagicMock

import crawler


def _search_url_count(pid: str, districts: dict) -> int:
    """Real search-URL count for a given scraper/districts combo, computed
    the same way crawler.run_full_crawl/run_incremental_crawl do -- avoids
    hardcoding an assumption about how many URLs a real scraper builds."""
    scraper = crawler.SCRAPERS[pid]
    return len(scraper.build_search_urls(
        selected_neighbourhoods=[], districts=districts,
        max_price=0, full_sectors=list(districts.keys()),
    ))


class RunFullCrawlDedupTests(unittest.TestCase):
    def test_already_known_urls_are_not_scraped_again(self):
        def fake_collect_page(scraper, search_url, page_num):
            return ["https://www.storia.ro/known", "https://www.storia.ro/new"] if page_num == 1 else []

        # Isolated from the real EXTRA_CITY_SEARCHES config -- this test only
        # cares about Bucharest sector dedup, not the Cluj/Iași URLs.
        with patch("db_utils.start_crawl_run_log", return_value=1), \
             patch("db_utils.finish_crawl_run_log"), \
             patch.object(crawler._http, "get_proxy", return_value=None), \
             patch.object(crawler, "EXTRA_CITY_SEARCHES", {}), \
             patch("crawler._collect_page", side_effect=fake_collect_page), \
             patch("crawler._known_urls", return_value={"https://www.storia.ro/known"}), \
             patch("crawler._scrape_and_save", return_value=1) as mock_save:

            result = crawler.run_full_crawl(
                conn=MagicMock(), platforms=["storia"],
                districts={"Sector 1": ["A"]},
            )

        self.assertEqual(result, 1)
        mock_save.assert_called_once()
        scraped_urls = mock_save.call_args.args[1]["storia"]
        self.assertEqual(scraped_urls, ["https://www.storia.ro/new"])
        self.assertNotIn("https://www.storia.ro/known", scraped_urls)
        self.assertEqual(mock_save.call_args.kwargs.get("city"), "Bucuresti")


class RunFullCrawlPaginationTests(unittest.TestCase):
    def test_stops_at_max_pages_even_if_every_page_has_links(self):
        call_count = {"n": 0}

        def fake_collect_page(scraper, search_url, page_num):
            call_count["n"] += 1
            return [f"https://www.storia.ro/p{page_num}"]

        with patch("db_utils.start_crawl_run_log", return_value=1), \
             patch("db_utils.finish_crawl_run_log"), \
             patch.object(crawler._http, "get_proxy", return_value=None), \
             patch.object(crawler, "EXTRA_CITY_SEARCHES", {}), \
             patch("crawler._collect_page", side_effect=fake_collect_page), \
             patch("crawler._known_urls", return_value=set()), \
             patch("crawler._scrape_and_save", return_value=1):

            crawler.run_full_crawl(
                conn=MagicMock(), platforms=["storia"],
                districts={"Sector 1": ["A"]}, max_pages=3,
            )

        # Every page returns fresh links, so without a boundary this would
        # paginate forever -- must stop at exactly max_pages per search URL.
        expected = 3 * _search_url_count("storia", {"Sector 1": ["A"]})
        self.assertEqual(call_count["n"], expected)


class RunIncrementalCrawlEarlyExitTests(unittest.TestCase):
    def test_stops_before_max_pages_once_known_ratio_crosses_threshold(self):
        call_count = {"n": 0}

        def fake_collect_page(scraper, search_url, page_num):
            call_count["n"] += 1
            return ["https://www.storia.ro/a", "https://www.storia.ro/b"]

        with patch("db_utils.start_crawl_run_log", return_value=1), \
             patch("db_utils.finish_crawl_run_log"), \
             patch.object(crawler._http, "get_proxy", return_value=None), \
             patch.object(crawler, "EXTRA_CITY_SEARCHES", {}), \
             patch("crawler._collect_page", side_effect=fake_collect_page), \
             patch("crawler._known_urls",
                   return_value={"https://www.storia.ro/a", "https://www.storia.ro/b"}), \
             patch("crawler._scrape_and_save", return_value=0):

            crawler.run_incremental_crawl(
                conn=MagicMock(), platforms=["storia"],
                districts={"Sector 1": ["A"]}, stop_threshold=0.5, max_pages=10,
            )

        # 100% known >= 50% threshold -> must exit after page 1 for every
        # search URL, never reaching page 2, let alone max_pages=10.
        expected = _search_url_count("storia", {"Sector 1": ["A"]})
        self.assertEqual(call_count["n"], expected)


class RunAvailabilityCheckPlatformDispatchTests(unittest.TestCase):
    def test_platform_not_in_the_filter_is_skipped_entirely(self):
        olx_scraper = MagicMock()
        storia_scraper = MagicMock()
        fake_listings = [
            {"platform_id": "olx", "url": "https://olx.example/a", "city": "Bucuresti"},
            {"platform_id": "storia", "url": "https://storia.example/a", "city": "Bucuresti"},
        ]

        with patch("db_utils.start_availability_check_log", return_value=1), \
             patch("db_utils.get_listings_for_availability_check", return_value=fake_listings), \
             patch("db_utils.batch_update_availability"), \
             patch("db_utils.save_to_db"), \
             patch("db_utils.finish_availability_check_log"), \
             patch.object(crawler, "SCRAPERS", {"olx": olx_scraper, "storia": storia_scraper}), \
             patch("crawler.time.sleep"):

            crawler.run_availability_check(platforms=["olx"])

        olx_scraper.scrape_listing_with_status.assert_called_once_with(
            "https://olx.example/a", city="Bucuresti"
        )
        storia_scraper.scrape_batch.assert_not_called()

    def test_non_bucharest_row_city_is_passed_through_to_olx_recheck(self):
        """A Cluj/Iași row being rechecked must not silently default to
        "Bucuresti" -- that would make scrape_listing_with_status run
        Bucharest-only title district matching against a non-Bucharest
        listing (see scrapers/olx.py's city-gated _extract_district_from_title)."""
        olx_scraper = MagicMock()
        fake_listings = [
            {"platform_id": "olx", "url": "https://olx.example/cluj-a", "city": "Cluj-Napoca"},
        ]

        with patch("db_utils.start_availability_check_log", return_value=1), \
             patch("db_utils.get_listings_for_availability_check", return_value=fake_listings), \
             patch("db_utils.batch_update_availability"), \
             patch("db_utils.save_to_db"), \
             patch("db_utils.finish_availability_check_log"), \
             patch.object(crawler, "SCRAPERS", {"olx": olx_scraper}), \
             patch("crawler.time.sleep"):

            crawler.run_availability_check(platforms=["olx"])

        olx_scraper.scrape_listing_with_status.assert_called_once_with(
            "https://olx.example/cluj-a", city="Cluj-Napoca"
        )

    def test_row_missing_city_falls_back_to_bucuresti(self):
        """Rows predating the city backfill (or any gap in it) must not crash
        the recheck -- fall back to the same "Bucuresti" default scrape_listing_with_status
        already uses, rather than passing None through."""
        olx_scraper = MagicMock()
        fake_listings = [
            {"platform_id": "olx", "url": "https://olx.example/legacy"},
        ]

        with patch("db_utils.start_availability_check_log", return_value=1), \
             patch("db_utils.get_listings_for_availability_check", return_value=fake_listings), \
             patch("db_utils.batch_update_availability"), \
             patch("db_utils.save_to_db"), \
             patch("db_utils.finish_availability_check_log"), \
             patch.object(crawler, "SCRAPERS", {"olx": olx_scraper}), \
             patch("crawler.time.sleep"):

            crawler.run_availability_check(platforms=["olx"])

        olx_scraper.scrape_listing_with_status.assert_called_once_with(
            "https://olx.example/legacy", city="Bucuresti"
        )


if __name__ == "__main__":
    unittest.main()
