"""
scrapers/olx.py
───────────────
OLX Romania scraper implementing PlatformScraper.
"""

from bs4 import BeautifulSoup
from .base import PlatformScraper
from .http import get_content


class OLXScraper(PlatformScraper):

    @property
    def platform_id(self) -> str:
        return "olx"

    @property
    def display_name(self) -> str:
        return "OLX"

    @property
    def base_url(self) -> str:
        return "https://www.olx.ro"

    # ── URL building ──────────────────────────────────────────────────────────

    def build_search_urls(self, selected_neighbourhoods, districts, max_price=0, per_neighbourhood=False, full_sectors=None, partial_by_sector=None):
        urls = set()
        full_sectors = set(full_sectors or [])
        partial_by_sector = partial_by_sector or {}

        if per_neighbourhood:
            name_to_sector = {}
            for district_name, neighbourhoods in districts.items():
                for n in neighbourhoods:
                    if n not in name_to_sector:
                        name_to_sector[n] = int(district_name.split(" ")[1])
            for n in selected_neighbourhoods:
                sector_num = name_to_sector.get(n)
                if sector_num is None:
                    continue
                olx_id = (sector_num * 2) - 1
                slug = self._to_slug(n)
                urls.add(
                    f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat"
                    f"/bucuresti/{slug}/?currency=EUR&search%5Bdistrict_id%5D={olx_id}"
                )
        else:
            for district_name, neighbourhoods in districts.items():
                sector_num = int(district_name.split(" ")[1])
                olx_id = (sector_num * 2) - 1

                if district_name in full_sectors:
                    urls.add(
                        f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat"
                        f"/bucuresti/?currency=EUR&search%5Bdistrict_id%5D={olx_id}"
                    )
                elif district_name in partial_by_sector:
                    for n in partial_by_sector[district_name]:
                        slug = self._to_slug(n)
                        urls.add(
                            f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat"
                            f"/bucuresti/{slug}/?currency=EUR&search%5Bdistrict_id%5D={olx_id}"
                        )

        if max_price > 0:
            urls = {u + f"&search%5Bfilter_float_price:to%5D={max_price}" for u in urls}

        return list(urls)

    @staticmethod
    def _to_slug(text: str) -> str:
        return (
            "q-" + text.lower()
            .replace(" ", "-")
            .replace("ă", "a").replace("î", "i").replace("â", "a")
            .replace("ș", "s").replace("ț", "t")
        )

    # ── Link collection ───────────────────────────────────────────────────────

    def collect_links(self, search_url: str, num_pages: int) -> list[str]:
        links = []
        for n in range(1, num_pages + 1):
            paged = search_url if n == 1 else f"{search_url}?page={n}"
            html = get_content(paged)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for card in soup.find_all("div", attrs={"data-cy": "l-card"}):
                anchor = card.find("a", href=True)
                if not anchor:
                    continue
                href = anchor["href"]
                if href.startswith("https"):
                    links.append(href)
                elif href.startswith("/d/o"):
                    links.append(self.base_url + href)
        return links

    # ── Individual listing ────────────────────────────────────────────────────

    # Status constants — same convention as the Storia scraper
    STATUS_OK      = "success"
    STATUS_EXPIRED = "expired"
    STATUS_BLOCKED = "blocked"

    def scrape_listing(self, url: str) -> dict | None:
        """Convenience wrapper — returns parsed dict or None (legacy callers)."""
        result = self.scrape_listing_with_status(url)
        if result["status"] == self.STATUS_OK:
            return result["data"]
        return None

    def scrape_listing_with_status(self, url: str) -> dict:
        """
        Fetch and parse a single OLX listing.
        Returns a dict with:
          status: "success" | "expired" | "blocked"
          data:   parsed listing dict (only present when status == "success")

        Expired detection (two signals):
          1. HTTP 410 Gone — OLX's canonical response for removed listings.
          2. data-testid="ad-inactive-msg" in the HTML — shown when OLX serves
             a soft-deleted page with a 200 instead of 410.
        """
        from curl_cffi import requests as cffi_requests
        from scrapers.http import HEADERS
        try:
            response = cffi_requests.get(url, headers=HEADERS, impersonate="chrome120")
            if response.status_code == 410:
                return {"url": url, "status": self.STATUS_EXPIRED}
            if response.status_code != 200:
                return {"url": url, "status": self.STATUS_BLOCKED}
            html = response.text
        except Exception:
            return {"url": url, "status": self.STATUS_BLOCKED}

        soup = BeautifulSoup(html, "html.parser")

        # Soft-deleted: page loads with 200 but shows inactive banner
        if soup.find(attrs={"data-testid": "ad-inactive-msg"}):
            return {"url": url, "status": self.STATUS_EXPIRED}

        try:
            title = soup.find("div", attrs={"data-cy": "offer_title"}).find("h4").get_text(strip=True)
            price = soup.find("div", attrs={"data-testid": "ad-price-container"}).find("h3").get_text(strip=True)

            desc_container = soup.find("div", attrs={"data-cy": "ad_description"})
            for tag in desc_container.find_all(["style", "h3"]):
                tag.decompose()
            description = desc_container.get_text(separator="\n", strip=True)

            source_id = str(
                soup.find("div", attrs={"data-cy": "ad-footer-bar-section"})
                .find("span").contents[2]
            ).strip()

            image_urls = self._extract_images(soup)

            return {
                "url":    url,
                "status": self.STATUS_OK,
                "data": {
                    "platform_id": self.platform_id,
                    "platform":    self.display_name,
                    "source_id":   source_id,
                    "url":         url,
                    "title":       title,
                    "price_eur":   price,
                    "rent":        price,
                    "price":       price,
                    "description": description,
                    "image_urls":  image_urls,
                },
            }
        except Exception as e:
            print(f"  [olx parse error] {url}: {e}")
            # Page loaded but parsing failed — treat as blocked (structure changed)
            return {"url": url, "status": self.STATUS_BLOCKED}

    @staticmethod
    def _extract_images(soup: BeautifulSoup) -> list[dict]:
        """Extract image data from the OLX photo swiper gallery.

        Returns a list of dicts with keys: thumbnail, small, medium, large
        (matching the Storia image schema for a uniform format).
        """
        images = []
        slides = soup.find_all("div", attrs={"data-cy": "adPhotos-swiperSlide"})
        for slide in slides:
            img = slide.find("img")
            if not img:
                continue

            full_src = img.get("src", "")
            if not full_src:
                continue

            srcset_map = {}
            srcset_raw = img.get("srcset", "")
            if srcset_raw:
                for entry in srcset_raw.split(","):
                    entry = entry.strip()
                    parts = entry.rsplit(" ", 1)
                    if len(parts) == 2:
                        srcset_map[parts[1]] = parts[0]

            images.append({
                "thumbnail": srcset_map.get("420w", ""),
                "small":     srcset_map.get("780w", ""),
                "medium":    srcset_map.get("992w", ""),
                "large":     full_src,
            })

        return images
