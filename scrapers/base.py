"""
scrapers/base.py
────────────────
Abstract base class every platform scraper must implement.

Adding a new data source = subclass PlatformScraper, implement the four
abstract methods, then register the instance in scrapers/__init__.py.
No other file needs to change.
"""

from abc import ABC, abstractmethod


class PlatformScraper(ABC):


    @property
    @abstractmethod
    def platform_id(self) -> str:
        """Short machine-readable key: 'olx', 'storia', 'imobiliare', …"""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in the UI."""

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Root domain, e.g. 'https://www.olx.ro'"""

    @abstractmethod
    def build_search_urls(
        self,
        selected_neighbourhoods: list[str],
        districts: dict,
        max_price: int = 0,
        per_neighbourhood: bool = False,
        full_sectors: list[str] | None = None,
        partial_by_sector: dict | None = None,
    ) -> list[str]:
        raise NotImplementedError


    @abstractmethod
    def collect_links(self, search_url: str, num_pages: int) -> list[str]:
        """
        Fetch one or more search-result pages and return all listing URLs
        found on them, fully qualified and normalised.
        """
        raise NotImplementedError

    def owns_url(self, url: str) -> bool:
        """Return True if `url` belongs to this platform."""
        return self.base_url.split("//")[-1].split("www.")[-1] in url


    @abstractmethod
    def scrape_listing(self, url: str) -> dict | None:
        """
        Fetch and parse a single listing page.

        Must return a dict with at least these canonical fields:
            platform_id  str   ← self.platform_id
            source_id    str   ← platform's own listing ID
            url          str
            title        str
            price_eur    str   ← raw price string; normalised later
            description  str
            district     str
            rooms        str | None
            area_sqm     str | None
            image_urls   list[dict] | None  ← per-photo objects with keys:
                         thumbnail, small, medium, large (CDN URLs)

        Return None on any parse failure — the pipeline will skip silently.
        """
        raise NotImplementedError
