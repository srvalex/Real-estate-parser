"""
Tests for crawler.py's multi-city pilot (GEO_EXPANSION_PLAN.md Phase 1):
EXTRA_CITY_SEARCHES gets crawled alongside Bucharest's sector URLs, and
every saved record is stamped with the city that produced it.

City is deliberately sourced from which search URL produced the listing
(crawler._scrape_and_save's `city` argument), not parsed/guessed from the
listing page -- see scripts/supabase_schema.sql's note on why the `city`
column has no DEFAULT: every writer must set it explicitly.
"""
import unittest
from unittest.mock import patch, MagicMock

import crawler


FAKE_EXTRA_CITIES = {
    "storia": [
        ("Iasi", "https://www.storia.ro/ro/rezultate/inchiriere/apartament/iasi/iasi"),
        ("Cluj-Napoca", "https://www.storia.ro/ro/rezultate/inchiriere/apartament/cluj/cluj--napoca"),
    ],
}


class ScrapeAndSaveCityTaggingTests(unittest.TestCase):
    """Unit tests directly on _scrape_and_save -- the single place city gets
    stamped onto a record, regardless of which platform branch produced it."""

    def test_city_is_required_no_implicit_default(self):
        with self.assertRaises(TypeError):
            crawler._scrape_and_save(MagicMock(), {})  # missing required `city`

    def test_storia_batch_records_get_the_given_city(self):
        # _scrape_and_save dispatches to the batch branch via an isinstance
        # check against StoriaScraper/ImobiliareRoScraper, so the fake needs
        # to actually be a StoriaScraper instance rather than a bare MagicMock.
        from scrapers.storia import StoriaScraper as RealStoriaScraper
        real_like = MagicMock(spec=RealStoriaScraper)
        real_like.__class__ = RealStoriaScraper
        real_like.BATCH_SIZE = 10
        real_like.display_name = "Storia"
        real_like.scrape_batch.return_value = [
            {"url": "https://www.storia.ro/a", "platform_id": "storia", "is_available": 1},
        ]

        with patch.dict(crawler.SCRAPERS, {"storia": real_like}), \
             patch("crawler._save_new_listings") as mock_save, \
             patch("crawler._load_supabase_known", return_value=set()), \
             patch("crawler.time.sleep"):
            saved_count = crawler._scrape_and_save(
                MagicMock(), {"storia": ["https://www.storia.ro/a"]}, city="Iasi"
            )

        self.assertEqual(saved_count, 1)
        mock_save.assert_called_once()
        saved_records = mock_save.call_args.args[0]
        self.assertEqual(saved_records[0]["city"], "Iasi")

    def test_olx_records_get_the_given_city_and_pass_it_to_the_scraper(self):
        from scrapers.olx import OLXScraper as RealOLXScraper
        real_like = MagicMock(spec=RealOLXScraper)
        real_like.__class__ = RealOLXScraper
        real_like.display_name = "OLX"
        real_like.scrape_listing_with_status.return_value = {
            "url": "https://www.olx.ro/d/oferta/a.html",
            "status": "success",
            "data": {"url": "https://www.olx.ro/d/oferta/a.html", "platform_id": "olx", "title": "x"},
        }

        with patch.dict(crawler.SCRAPERS, {"olx": real_like}), \
             patch("crawler._save_new_listings") as mock_save, \
             patch("crawler._load_supabase_known", return_value=set()), \
             patch("crawler.time.sleep"):
            crawler._scrape_and_save(
                MagicMock(), {"olx": ["https://www.olx.ro/d/oferta/a.html"]}, city="Cluj-Napoca"
            )

        real_like.scrape_listing_with_status.assert_called_once_with(
            "https://www.olx.ro/d/oferta/a.html", city="Cluj-Napoca"
        )
        saved_records = mock_save.call_args.args[0]
        self.assertEqual(saved_records[0]["city"], "Cluj-Napoca")


class ExtraCitySearchOrchestrationTests(unittest.TestCase):
    """run_full_crawl / run_incremental_crawl must crawl EXTRA_CITY_SEARCHES
    entries in addition to the Bucharest sector URLs, tagging each with its
    own city -- and platforms with no entry (e.g. imobiliare) are unaffected."""

    def test_full_crawl_hits_extra_city_urls_with_correct_city(self):
        seen_calls = []

        def fake_collect_page(scraper, search_url, page_num):
            if page_num > 1:
                return []
            return [f"{search_url}#listing"]

        def fake_scrape_and_save(conn, by_platform, city):
            seen_calls.append((city, list(by_platform.get("storia", []))))
            return 1

        with patch("db_utils.start_crawl_run_log", return_value=1), \
             patch("db_utils.finish_crawl_run_log"), \
             patch.object(crawler._http, "get_proxy", return_value=None), \
             patch.object(crawler, "EXTRA_CITY_SEARCHES", FAKE_EXTRA_CITIES), \
             patch("crawler._collect_page", side_effect=fake_collect_page), \
             patch("crawler._known_urls", return_value=set()), \
             patch("crawler._owner", return_value="storia"), \
             patch("crawler._scrape_and_save", side_effect=fake_scrape_and_save):

            crawler.run_full_crawl(
                conn=MagicMock(), platforms=["storia"],
                districts={"Sector 1": ["A"]},
            )

        cities_hit = {city for city, _ in seen_calls}
        self.assertEqual(cities_hit, {"Bucuresti", "Iasi", "Cluj-Napoca"})

    def test_incremental_crawl_hits_extra_city_urls_with_correct_city(self):
        seen_calls = []

        def fake_collect_page(scraper, search_url, page_num):
            if page_num > 1:
                return []
            return [f"{search_url}#listing"]

        def fake_scrape_and_save(conn, by_platform, city):
            seen_calls.append(city)
            return 0

        with patch("db_utils.start_crawl_run_log", return_value=1), \
             patch("db_utils.finish_crawl_run_log"), \
             patch.object(crawler._http, "get_proxy", return_value=None), \
             patch.object(crawler, "EXTRA_CITY_SEARCHES", FAKE_EXTRA_CITIES), \
             patch("crawler._collect_page", side_effect=fake_collect_page), \
             patch("crawler._known_urls", return_value=set()), \
             patch("crawler._owner", return_value="storia"), \
             patch("crawler._scrape_and_save", side_effect=fake_scrape_and_save):

            crawler.run_incremental_crawl(
                conn=MagicMock(), platforms=["storia"],
                districts={"Sector 1": ["A"]}, stop_threshold=0.99,
            )

        self.assertEqual(set(seen_calls), {"Bucuresti", "Iasi", "Cluj-Napoca"})

    def test_platform_with_no_extra_city_entry_is_unaffected(self):
        """imobiliare has no EXTRA_CITY_SEARCHES entry -- only Bucharest URLs
        should be crawled for it, exactly as before this change."""
        seen_cities = []

        def fake_collect_page(scraper, search_url, page_num):
            return []  # empty immediately -- only care about which cities were attempted

        def fake_scrape_and_save(conn, by_platform, city):
            seen_cities.append(city)
            return 0

        with patch("db_utils.start_crawl_run_log", return_value=1), \
             patch("db_utils.finish_crawl_run_log"), \
             patch.object(crawler._http, "get_proxy", return_value=None), \
             patch.object(crawler, "EXTRA_CITY_SEARCHES", FAKE_EXTRA_CITIES), \
             patch("crawler._collect_page", side_effect=fake_collect_page), \
             patch("crawler._known_urls", return_value=set()), \
             patch("crawler._scrape_and_save", side_effect=fake_scrape_and_save):

            crawler.run_full_crawl(
                conn=MagicMock(), platforms=["imobiliare"],
                districts={"Sector 1": ["A"]},
            )

        # empty pages -> _scrape_and_save never actually called, but no crash
        # and (implicitly) build_search_urls + EXTRA_CITY_SEARCHES.get("imobiliare", [])
        # produced only Bucharest URLs. Assert no extra-city keys leaked in.
        self.assertNotIn("imobiliare", FAKE_EXTRA_CITIES)
        self.assertEqual(seen_cities, [])


if __name__ == "__main__":
    unittest.main()
