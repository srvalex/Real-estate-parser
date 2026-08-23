"""
Tests that scrapers.storia.StoriaScraper.build_search_urls always requests
newest-first ordering (by=LATEST&direction=DESC) from Storia.

Bug/gap: crawler.run_incremental_crawl's early-exit relies on new listings
always appearing on page 1 of a search result. For Storia this was only ever
an assumption about the site's default sort order, never requested
explicitly or verified against the live site (confirmed via
https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti
    ?ownerTypeSingleSelect=ALL&by=LATEST&direction=DESC).
Every URL build_search_urls produces must carry these params so the
incremental crawl's assumption actually holds.
"""
import unittest

from scrapers.storia import StoriaScraper


class StoriaSearchUrlSortOrderTests(unittest.TestCase):
    def setUp(self):
        self.scraper = StoriaScraper()
        self.districts = {"Sector 1": ["Aviatorilor", "Herastrau"]}

    def _assert_all_sorted_newest_first(self, urls):
        self.assertTrue(urls)
        for url in urls:
            self.assertIn("by=LATEST", url)
            self.assertIn("direction=DESC", url)

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
        self.assertTrue(any("priceMax=1000" in u for u in urls))


if __name__ == "__main__":
    unittest.main()
