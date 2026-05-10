"""
scrapers/imobiliare.py
──────────────────────
Imobiliare.ro scraper implementing PlatformScraper.

Search pages are plain HTML — fetched with get_content().
Listing pages are Nuxt SSR — data lives in JSON-LD + window.dataLayer,
both server-rendered into the initial HTML, so no JS execution needed.
Expired listings redirect to the homepage — detected by final URL mismatch.
"""

import json
import re
import os
import subprocess
from bs4 import BeautifulSoup
from .base import PlatformScraper
from .http import get_content


class ImobiliareRoScraper(PlatformScraper):

    BASE = "https://www.imobiliare.ro"

    BATCH_SIZE = 10   # listing pages rendered in parallel via subprocess

    @property
    def platform_id(self) -> str:
        return "imobiliare"

    @property
    def display_name(self) -> str:
        return "Imobiliare.ro"

    @property
    def base_url(self) -> str:
        return self.BASE

    # ── URL building ──────────────────────────────────────────────────────────

    def build_search_urls(
        self,
        selected_neighbourhoods,
        districts,
        max_price=0,
        per_neighbourhood=False,
        full_sectors=None,
        partial_by_sector=None,
        min_price=0,
        rooms=None,
        keywords=None,
    ) -> list[str]:
        """
        Build Imobiliare.ro search URLs with the format:
          /inchirieri-apartamente/bucuresti[/sector-N][/neighbourhood][/N-camere][?q=...&price=min-max]

        Args:
            rooms:    int or str room count, e.g. 2 → "/2-camere" path segment
            keywords: str passed as ?q=... (e.g. "pet-friendly")
            min_price / max_price: combined into ?price=min-max (0 = omit)
        """
        full_sectors      = set(full_sectors or [])
        partial_by_sector = partial_by_sector or {}

        # Build rooms path segment: e.g. rooms=2 → "/2-camere"
        rooms_segment = f"/{rooms}-camere" if rooms else ""

        # Build query string
        query_parts = []
        if keywords:
            query_parts.append(f"q={keywords}")
        if max_price and max_price > 0:
            query_parts.append(f"price={min_price}-{max_price}")
        query_string = ("?" + "&".join(query_parts)) if query_parts else ""

        base_path = f"{self.BASE}/inchirieri-apartamente/bucuresti"
        urls = set()

        if per_neighbourhood:
            # Proximity additions — one URL per neighbourhood
            for n in selected_neighbourhoods:
                slug = self._to_slug(n)
                urls.add(f"{base_path}/{slug}{rooms_segment}{query_string}")
        else:
            # Build a name→sector map for sector-level lookups
            name_to_sector = {}
            for district_name, neighbourhoods in districts.items():
                for n in neighbourhoods:
                    if n not in name_to_sector:
                        name_to_sector[n] = int(district_name.split(" ")[1])

            for district_name, neighbourhoods in districts.items():
                sector_num = int(district_name.split(" ")[1])

                if district_name in full_sectors:
                    # Whole sector selected → /sector-N[/N-camere]
                    urls.add(
                        f"{base_path}/sector-{sector_num}{rooms_segment}{query_string}"
                    )
                elif district_name in partial_by_sector:
                    # Specific neighbourhoods → /sector-N/neighbourhood[/N-camere]
                    for n in partial_by_sector[district_name]:
                        slug = self._to_slug(n)
                        urls.add(
                            f"{base_path}/sector-{sector_num}/{slug}{rooms_segment}{query_string}"
                        )

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
        """
        Fetch search result pages and return listing URLs.
        Pagination: append ?page=N (or &page=N if query string already present).
        """
        links = []
        for n in range(1, num_pages + 1):
            if n == 1:
                paged = search_url
            elif "?" in search_url:
                paged = f"{search_url}&page={n}"
            else:
                paged = f"{search_url}?page={n}"

            html = get_content(paged)
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", attrs={"data-cy": "listing-information-link"}):
                href = a.get("href", "")
                if not href:
                    continue
                full = href if href.startswith("https") else self.BASE + href
                links.append(full)

        return links

    # ── Individual listing ────────────────────────────────────────────────────

    STATUS_OK      = "success"
    STATUS_EXPIRED = "expired"
    STATUS_BLOCKED = "blocked"

    def scrape_listing(self, url: str) -> dict | None:
        """Convenience wrapper for legacy callers."""
        result = self.scrape_listing_with_status(url)
        if result["status"] == self.STATUS_OK:
            return result["data"]
        return None

    def scrape_batch(self, urls: list[str]) -> list[dict]:
        """
        Render and parse a batch of listing pages via subprocess (same pattern as Storia).
        Returns dicts with is_available set.
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

    def scrape_listing_with_status(self, url: str) -> dict:
        results = self._fetch_batch_raw([url])
        if not results:
            return {"url": url, "status": self.STATUS_BLOCKED}
        r = results[0]
        status = r.get("status", "blocked")
        if status == "expired":
            return {"url": url, "status": self.STATUS_EXPIRED}
        if status == "success":
            p = self._parse_raw(r)
            if p:
                return {"url": url, "status": self.STATUS_OK, "data": p}
        return {"url": url, "status": self.STATUS_BLOCKED}

    def _fetch_batch_raw(self, urls: list[str]) -> list[dict]:
        if not urls:
            return []
        script = os.path.join(
            os.path.dirname(__file__), "..", "scripts", "get_imobiliare_listing.py"
        )
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
                    print(f"  [imobiliare json error] {stdout[:100]}")
            elif stderr:
                print(f"  [imobiliare batch error] {stderr[:200]}")
        except Exception as e:
            print(f"  [imobiliare subprocess error] {e}")
        return []

    def _parse_raw(self, raw: dict) -> dict | None:
        """
        Parse the structured data returned by get_imobiliare_listing.py.

        Sources:
          ld.product  → title, description, images
          ld.offer    → price
          ld.listing  → area_sqm (from summary description via regex)
          dl          → district, location slug, rooms, source_id
        """
        if not isinstance(raw, dict) or raw.get("status") != "success":
            return None

        ld  = raw.get("ld", {})
        dl  = raw.get("dl", {})
        url = raw.get("url", "")

        try:
            product = ld.get("product", {})
            offer   = ld.get("offer", {})
            listing = ld.get("listing", {})

            # ── Title ─────────────────────────────────────────────────────────
            title = (product.get("name") or "").replace(" | Imobiliare.ro", "").strip()

            # ── Description (full text from Product) ──────────────────────────
            description = product.get("description") or ""

            # ── Price ─────────────────────────────────────────────────────────
            price_spec = offer.get("priceSpecification", {})
            price_val  = price_spec.get("price", "")
            currency   = price_spec.get("priceCurrency", "EUR")
            price_str  = f"{price_val} {currency}".strip() if price_val != "" else ""

            # ── Location ──────────────────────────────────────────────────────
            # listing_location_title → neighbourhood name  e.g. "Berceni"
            # listing_location_slug  → full slug           e.g. "bucuresti-sector-4-berceni"
            district      = dl.get("listing_location_title", "Unknown")
            location_full = dl.get("listing_location_slug", "Unknown")

            # ── Rooms ─────────────────────────────────────────────────────────
            # onesignal_listing_bedroom = "2-camere" → extract digit
            bedroom_raw = dl.get("onesignal_listing_bedroom", "")
            rooms = None
            if bedroom_raw:
                m = re.search(r"(\d+)", bedroom_raw)
                rooms = m.group(1) if m else bedroom_raw

            # ── Area (sqm) ────────────────────────────────────────────────────
            # Primary: RealEstateListing.floorSize.value (structured)
            # Fallback: regex on the short summary description
            area_sqm = None
            floor_size = listing.get("floorSize", {})
            if isinstance(floor_size, dict) and floor_size.get("value") not in (None, ""):
                try:
                    area_sqm = str(floor_size["value"])
                except Exception:
                    pass
            if area_sqm is None:
                summary = listing.get("description", "")
                if summary:
                    m = re.search(r"(\d+)\s*mp", summary)
                    if m:
                        area_sqm = m.group(1)

            source_id = str(dl.get("listing_id", ""))
            if not source_id:
                m = re.search(r"-(\d+)$", url.rstrip("/"))
                source_id = m.group(1) if m else ""

            # ── Property type from URL path ────────────────────────────────────
            # Imobiliare encodes the property category in the URL:
            #   /inchirieri-apartamente/ → "Apartament"
            #   /inchirieri-garsoniere/  → "Garsoniera"
            #   /inchirieri-case-vile/   → "Casa/Vila"
            _URL_TYPE_MAP = {
                "inchirieri-apartamente": "Apartament",
                "inchirieri-garsoniere":  "Garsoniera",
                "inchirieri-case-vile":   "Casa/Vila",
            }
            property_type = next(
                (pt for seg, pt in _URL_TYPE_MAP.items() if seg in url),
                None,
            )

            raw_images = product.get("image", [])
            image_urls = []
            for img in raw_images:
                og_url = img.get("@id", "")
                if not og_url:
                    continue
                image_urls.append({
                    "thumbnail": "",
                    "small":     "",
                    "medium":    og_url,
                    "large":     og_url,
                })

            # dl keys already consumed at top level — skip them in extras
            _USED_DL = {
                "listing_id", "listing_location_title",
                "listing_location_slug", "onesignal_listing_bedroom",
            }
            extras: dict = {}

            # RealEstateListing structured fields
            for ld_key in ("floorLevel", "numberOfRooms", "numberOfBathroomsTotal", "yearBuilt"):
                val = listing.get(ld_key)
                if val not in (None, ""):
                    extras[ld_key] = val
            if isinstance(floor_size, dict) and floor_size.get("value") not in (None, ""):
                extras["floorSizeValue"] = floor_size["value"]
                extras["floorSizeUnit"]  = floor_size.get("unitCode", "")

            # additionalProperty arrays on Product and RealEstateListing nodes
            for prop in (
                listing.get("additionalProperty", [])
                + product.get("additionalProperty", [])
            ):
                name = prop.get("name") or prop.get("propertyID", "")
                val  = prop.get("value")
                if name and val not in (None, ""):
                    extras[name] = val

            # Remaining dataLayer fields (all are listing-specific attributes)
            for k, v in dl.items():
                if k not in _USED_DL and v not in (None, "", [], {}):
                    extras[k] = v

            result = {
                "platform_id":        self.platform_id,
                "platform":           self.display_name,
                "source_id":          source_id,
                "url":                url,
                "title":              title,
                "price_eur":          price_str,
                "rent":               price_str,
                "price":              price_str,
                "description":        description,
                "district":           district,
                "location_full_name": location_full,
                "rooms":              rooms,
                "area_sqm":           area_sqm,
                "image_urls":         image_urls,
                "extras":             extras if extras else None,
            }
            if property_type:
                result["property_type"] = property_type
            return result

        except Exception as e:
            print(f"  [imobiliare parse error] {url}: {e}")
            return None
