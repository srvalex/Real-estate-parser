"""
scrapers/storia.py
──────────────────
Storia Romania scraper implementing PlatformScraper.
Uses a subprocess to render JavaScript-heavy listing pages.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from .base import PlatformScraper
from .http import get_content
from scripts.get_rendered_description import classify_storia_page


class StoriaScraper(PlatformScraper):

    # How many listing pages to render in parallel per subprocess call
    BATCH_SIZE = 10

    @property
    def platform_id(self) -> str:
        return "storia"

    @property
    def display_name(self) -> str:
        return "Storia"

    @property
    def base_url(self) -> str:
        return "https://www.storia.ro"

    # ── URL building ──────────────────────────────────────────────────────────

    def build_search_urls(self, selected_neighbourhoods, districts, max_price=0, per_neighbourhood=False, full_sectors=None, partial_by_sector=None):
        urls = set()
        full_sectors = set(full_sectors or [])
        partial_by_sector = partial_by_sector or {}

        if per_neighbourhood:
            # Proximity additions: flat list, generate one URL per neighbourhood.
            # Map each name back to its first matching sector.
            name_to_sector = {}
            for district_name, neighbourhoods in districts.items():
                for n in neighbourhoods:
                    if n not in name_to_sector:
                        name_to_sector[n] = int(district_name.split(" ")[1])
            for n in selected_neighbourhoods:
                sector_num = name_to_sector.get(n)
                if sector_num is None:
                    continue
                slug = self._to_slug(n)
                urls.add(
                    f"https://www.storia.ro/ro/rezultate/inchiriere/apartament"
                    f"/bucuresti/sectorul-{sector_num}/{slug}"
                    f"?ownerTypeSingleSelect=ALL&limit=48"
                )
        else:
            for district_name, neighbourhoods in districts.items():
                sector_num = int(district_name.split(" ")[1])

                if district_name in full_sectors:
                    urls.add(
                        f"https://www.storia.ro/ro/rezultate/inchiriere/apartament"
                        f"/bucuresti/sectorul-{sector_num}"
                        f"?ownerTypeSingleSelect=ALL&limit=48"
                    )
                elif district_name in partial_by_sector:
                    for n in partial_by_sector[district_name]:
                        slug = self._to_slug(n)
                        urls.add(
                            f"https://www.storia.ro/ro/rezultate/inchiriere/apartament"
                            f"/bucuresti/sectorul-{sector_num}/{slug}"
                            f"?ownerTypeSingleSelect=ALL&limit=48"
                        )

        if max_price > 0:
            urls = {u + f"&priceMax={max_price}" for u in urls}

        return list(urls)

    @staticmethod
    def _to_slug(text: str) -> str:
        return (
            text.lower()
            .replace(" ", "-")
            .replace("ă", "a").replace("î", "i").replace("â", "a")
            .replace("ș", "s").replace("ț", "t")
        )

    # ── Link collection ───────────────────────────────────────────────────────

    def collect_links(self, search_url: str, num_pages: int) -> list[str]:
        links = []
        for n in range(1, num_pages + 1):
            paged = search_url if n == 1 else f"{search_url}&page={n}"
            html = get_content(paged)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for card in soup.find_all("div", attrs={"data-sentry-element": "ContentContainer"}):
                anchor = card.find("a", href=True)
                if not anchor:
                    continue
                href = anchor["href"]
                full = href if href.startswith("https") else self.base_url + href
                # Normalise: strip .html suffix
                links.append(full.split(".html")[0])
        return links

    # ── Individual listing (batch subprocess) ────────────────────────────────

    def scrape_listing(self, url: str) -> dict | None:
        """Single-URL convenience wrapper around the batch method."""
        results = self._scrape_batch([url])
        return results[0] if results else None

    def scrape_batch(self, urls: list[str]) -> list[dict]:
        """
        Render and parse a batch of Storia listing pages via subprocess.
        Returns a list of dicts — each has an 'is_available' field:
          1  = live listing, fully parsed
          0  = confirmed expired (ExpiredAdContentLayout detected)
        Blocked/error entries are silently dropped (retried next scrape).
        """
        raw_results = self._fetch_batch_raw(urls)
        parsed = []
        for r in raw_results:
            status = r.get("status", "blocked")
            if status == "expired":
                parsed.append({
                    "url":          r.get("url", ""),
                    "platform_id":  self.platform_id,
                    "is_available": 0,
                })
            elif status == "success":
                p = self._parse_raw(r)
                if p:
                    p["is_available"] = 1
                    parsed.append(p)
            else:
                parsed.append({
                    "url":          r.get("url", ""),
                    "platform_id":  self.platform_id,
                    "is_available": None,
                    "status":       status,
                })
        return parsed

    def _fetch_batch_raw(self, urls: list[str]) -> list[dict]:
        if not urls:
            return []
        proxy_url = os.environ.get("PROXY_URL", "").strip() or None
        proxies = {"https": proxy_url, "http": proxy_url} if proxy_url else None

        def _fetch_one(url: str) -> dict:
            try:
                r = cffi_requests.get(
                    url,
                    proxies=proxies,
                    impersonate="chrome120",
                    timeout=20,
                    allow_redirects=True,
                )
                final_url = str(r.url)
                if "/ro/oferta/" not in final_url:
                    return {"url": url, "status": "expired", "data": {}}
                return classify_storia_page(r.text, url)
            except Exception as e:
                return {"url": url, "status": "blocked", "message": str(e)}

        with ThreadPoolExecutor(max_workers=min(len(urls), 10)) as executor:
            return list(executor.map(_fetch_one, urls))

    def _parse_raw(self, raw: dict) -> dict | None:
        data = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
        if not data or not isinstance(data, dict):
            return None
        try:
            # Feature/amenity tags. The old flat `features` / `featuresByCategory`
            # fields are always empty in current Storia API responses -- the real
            # data now lives in `additionalInformation`, grouped by category, e.g.
            # {"label": "extras_types", "values": ["extras_types::balcony", ...]}.
            # Flatten it into a plain tag list: positive boolean flags (suffix "y",
            # e.g. "rent_to_students::y") emit the label itself, negative ones
            # (suffix "n") are dropped, everything else emits the value's suffix.
            feature_tags = []
            for entry in data.get("additionalInformation", []) or []:
                label = entry.get("label", "")
                for value in entry.get("values", []) or []:
                    suffix = str(value).rsplit("::", 1)[-1]
                    if suffix == "n":
                        continue
                    feature_tags.append(label if suffix == "y" else suffix)

            result = {
                "platform_id": self.platform_id,
                "platform":    self.display_name,
                "source_id":   str(data.get("id", "")),
                # Prefer the URL we actually requested over Storia's own
                # self-reported `data["url"]` -- their internal slug can drift
                # after the ad was first scraped (e.g. "centrala-parcare" ->
                # "centralaparcare"), and save_to_db() upserts on this field.
                # Trusting the drifted value creates a duplicate row instead
                # of updating the existing one on every re-check.
                "url":         raw.get("url") or data.get("url", ""),
                "title":       data.get("title", ""),
                "features":    str(feature_tags),
            }

            # Characteristics (rooms, area, etc.)
            for el in data.get("characteristics", []):
                result[el["key"]] = el.get("localizedValue")

            # Location
            locs = data.get("location", {}).get("reverseGeocoding", {}).get("locations", [])
            result["district"] = locs[-1].get("name", "Unknown") if locs else "Unknown"
            result["location_full_name"] = locs[-1].get("fullName", "Unknown") if locs else "Unknown"

            # Description
            desc_raw = data.get("description", "")
            if desc_raw:
                soup = BeautifulSoup(desc_raw, "html.parser")
                result["description"] = "\n".join(
                    line.strip()
                    for line in soup.get_text(separator="\n").splitlines()
                    if line.strip()
                )
            else:
                result["description"] = ""

            # Images — nested JSON with thumbnail/small/medium/large per photo
            raw_images = data.get("images", [])
            result["image_urls"] = [
                {k: v for k, v in img.items() if k in ("thumbnail", "small", "medium", "large")}
                for img in raw_images
                if isinstance(img, dict)
            ]

            # Canonical price field
            result["price_eur"] = result.get("price", "")
            result["rent"] = result.get("price", "")   # backward compat

            # Property type from top-level estate field in __NEXT_DATA__ ad object.
            # OLX-group platforms (Storia is OLX Group) expose estate as e.g.
            # "FLAT", "STUDIO", "HOUSE" at the ad level, not in characteristics.
            _ESTATE_MAP = {
                "flat":        "Apartament",
                "apartment":   "Apartament",
                "apartament":  "Apartament",
                "studio":      "Studio",
                "garsoniera":  "Garsoniera",
                "garsonieră":  "Garsoniera",
                "house":       "Casa/Vila",
                "houses":      "Casa/Vila",
                "casa":        "Casa/Vila",
                "vila":        "Casa/Vila",
            }
            estate_raw = data.get("estate", "")
            if estate_raw:
                result["property_type"] = _ESTATE_MAP.get(
                    str(estate_raw).lower(), str(estate_raw)
                )

            # Preserve the entire raw ad object verbatim. When Storia changes
            # their internal data model again (as happened with `features` /
            # `additionalInformation` -- see StoriaFeaturesExtractionTests),
            # the original payload is still here to re-derive fields from
            # without needing to re-scrape an ad that may have expired since.
            result["extras"] = data

            return result
        except Exception as e:
            print(f"  [storia parse error] {e}")
            return None
