"""
scrapers/__init__.py
────────────────────
Platform scraper registry.

To add a new data source:
  1. Create scrapers/mysite.py implementing PlatformScraper
  2. Add one line here: from .mysite import MySiteScraper
  3. Add one entry to SCRAPERS

No other file needs to change.
"""

from .olx import OLXScraper
from .storia import StoriaScraper

SCRAPERS: dict = {
    "olx":    OLXScraper(),
    "storia": StoriaScraper(),
}
