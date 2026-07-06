"""
demo/scrape_listing.py
───────────────────────
Presentation CLI — scrape a single listing URL live and dump the raw,
platform-native scrape result (before canonical-column normalisation) to a
markdown file, for showing on screen next to the original web page.

Usage:
    python demo/scrape_listing.py <listing_url>

The platform (OLX / Storia / Imobiliare) is auto-detected from the URL.
Output: demo/output/raw/<platform>_raw.md
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers import SCRAPERS

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "raw")


def _detect_platform(url: str) -> str | None:
    for pid, scraper in SCRAPERS.items():
        if scraper.owns_url(url):
            return pid
    return None


def _scrape_raw(pid: str, url: str) -> dict:
    """Return the platform-native parsed dict (pre-canonicalisation)."""
    scraper = SCRAPERS[pid]

    if pid == "olx":
        result = scraper.scrape_listing_with_status(url)
        status = result.get("status")
        if status != "success":
            raise RuntimeError(
                f"OLX scrape returned status={status!r} -- pick a live listing URL and try again"
            )
        return result["data"]

    # Storia / Imobiliare: batch scrapers
    results = scraper.scrape_batch([url])
    if not results:
        raise RuntimeError("No result returned from scraper")
    entry = results[0]
    if entry.get("is_available") is None:
        raise RuntimeError(
            f"Blocked / could not fetch (status={entry.get('status')!r}) -- try again in a moment"
        )
    if entry.get("is_available") == 0:
        raise RuntimeError("Listing is expired / no longer available -- pick a live listing URL")
    return entry


def main():
    if len(sys.argv) != 2:
        print("Usage: python demo/scrape_listing.py <listing_url>")
        sys.exit(1)

    url = sys.argv[1].strip()
    pid = _detect_platform(url)
    if pid is None:
        print(f"Could not determine platform for URL: {url}")
        sys.exit(1)

    scraper = SCRAPERS[pid]
    print(f"Detected platform: {scraper.display_name}")
    print(f"Scraping {url} ...")

    raw = _scrape_raw(pid, url)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"{pid}_raw.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Raw scrape result -- {scraper.display_name}\n\n")
        f.write(f"- **Source URL:** {url}\n")
        f.write(f"- **Scraped at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("- Platform-native fields, exactly as the scraper parsed them from the page --\n")
        f.write("  before canonical-column normalisation.\n\n")
        f.write("```json\n")
        f.write(json.dumps(raw, ensure_ascii=False, indent=2))
        f.write("\n```\n")

    print(f"Raw data written to {out_path}")


if __name__ == "__main__":
    main()
