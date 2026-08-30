"""
Tests that scrapers.olx.OLXScraper.build_search_urls always requests
newest-first ordering (search[order]=created_at:desc) from OLX.

Same reasoning as tests/scrapers/storia/test_storia_search_url_sort_order.py:
crawler.run_incremental_crawl's early-exit relies on new listings always
appearing on page 1 of a search result. OLX's default order was never
requested explicitly before this change.
"""
import unittest

from scrapers.olx import OLXScraper


class OlxSearchUrlSortOrderTests(unittest.TestCase):
    def setUp(self):
        self.scraper = OLXScraper()
        self.districts = {"Sector 1": ["Aviatorilor", "Herastrau"]}

    def _assert_all_sorted_newest_first(self, urls):
        self.assertTrue(urls)
        for url in urls:
            self.assertIn("search%5Border%5D=created_at:desc", url)

    def test_full_sector_urls_are_sorted_newest_first(self):
        urls = self.scraper.build_search_urls(
            selected_neighbourhoods=[],
            districts=self.districts,
            full_sectors=["Sector 1"],
        )
        self._assert_all_sorted_newest_first(urls)

    def test_partial_sector_urls_are_sorted_newest_first(self):
        urls = self.scraper.build_search_urls(
            selected_neighbourhoods=[],
            districts=self.districts,
            partial_by_sector={"Sector 1": ["Aviatorilor"]},
        )
        self._assert_all_sorted_newest_first(urls)

    def test_per_neighbourhood_urls_are_sorted_newest_first(self):
        urls = self.scraper.build_search_urls(
            selected_neighbourhoods=["Aviatorilor"],
            districts=self.districts,
            per_neighbourhood=True,
        )
        self._assert_all_sorted_newest_first(urls)

    def test_sort_params_survive_max_price_being_appended(self):
        urls = self.scraper.build_search_urls(
            selected_neighbourhoods=[],
            districts=self.districts,
            full_sectors=["Sector 1"],
            max_price=1000,
        )
        self._assert_all_sorted_newest_first(urls)
        self.assertTrue(any("search%5Bfilter_float_price:to%5D=1000" in u for u in urls))


if __name__ == "__main__":
    unittest.main()
