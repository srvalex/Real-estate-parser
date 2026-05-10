"""
scrapers/storia.py
──────────────────
Storia Romania scraper implementing PlatformScraper.
Uses a subprocess to render JavaScript-heavy listing pages.
"""

import json
import os
import subprocess
from bs4 import BeautifulSoup
from .base import PlatformScraper
from .http import get_content


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
            # blocked → drop silently
        return parsed

    def _fetch_batch_raw(self, urls: list[str]) -> list[dict]:
        if not urls:
            return []
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "get_rendered_description.py")
        try:
            proc = subprocess.Popen(
                ["python", script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            stdout, stderr = proc.communicate(input=json.dumps(urls))
            if stdout.strip():
                try:
                    return json.loads(stdout.strip())
                except json.JSONDecodeError:
                    print(f"  [storia json error] {stdout[:100]}")
            elif stderr:
                print(f"  [storia batch error] {stderr[:200]}")
        except Exception as e:
            print(f"  [storia subprocess error] {e}")
        return []

    def _parse_raw(self, raw: dict) -> dict | None:
        data = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
        if not data or not isinstance(data, dict):
            return None
        try:
            result = {
                "platform_id": self.platform_id,
                "platform":    self.display_name,
                "source_id":   str(data.get("id", "")),
                "url":         data.get("url", raw.get("url", "")),
                "title":       data.get("title", ""),
                "features":    str(data.get("features", [])),
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

            return result
        except Exception as e:
            print(f"  [storia parse error] {e}")
            return None
