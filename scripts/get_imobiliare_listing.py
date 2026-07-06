"""
get_imobiliare_listing.py
─────────────────────────
Playwright subprocess for rendering Imobiliare.ro listing pages.
Called by ImobiliareRoScraper._fetch_batch_raw() — reads a JSON list of URLs
from stdin, writes a JSON list of result dicts to stdout.

Each result dict has:
  url     str
  status  "success" | "expired" | "blocked"
  ld      dict  (merged JSON-LD nodes: product, offer, listing)   — success only
  dl      dict  (dataLayer listing entry)                          — success only

Expired detection: imobiliare.ro redirects removed listings to the homepage.
We compare the final page URL against the requested URL — mismatch = expired.
"""

import asyncio
import json
import os
import sys
import io
from urllib.parse import urlparse

def classify_imobiliare_page(content: str, requested_url: str, final_url: str) -> dict:
    """Classify an Imobiliare listing page as live, expired, or blocked."""
    lowered = content.lower()
    unavailable_markers = (
        "nu se primesc cereri pentru această proprietate",
        "nu se primesc cereri pentru aceasta proprietate",
        "anunțul nu mai este disponibil",
        "anuntul nu mai este disponibil",
        "nu mai este disponibil",
        "nu mai este activ",
        "anunț arhivat",
        "anunt arhivat",
        "deja închiriat",
        "deja inchiriat",
        # NOTE: "rezervat" and "vândut"/"vindut" were removed — every page's
        # footer reads "Toate drepturile rezervate" (all rights reserved),
        # which matched "rezervat" and false-flagged 100% of live listings
        # as expired.
    )

    if any(marker in lowered for marker in unavailable_markers):
        return {"url": requested_url, "status": "expired"}

    # Redirect-based detection removed: a blocked proxy redirects to the same
    # homepage as a genuine expired listing, making them indistinguishable.
    # Expiry is instead inferred from absent JSON-LD in fetch_url below.
    return {"url": requested_url, "status": "blocked", "message": "no explicit expiry marker found"}


def _playwright_proxy() -> dict | None:
    """Parse PROXY_URL env var into the dict Playwright's new_context() expects."""
    raw = os.environ.get("PROXY_URL", "").strip()
    if not raw:
        return None
    p = urlparse(raw)
    proxy = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        proxy["username"] = p.username
    if p.password:
        proxy["password"] = p.password
    return proxy


async def fetch_url(context, url: str) -> dict:
    page = await context.new_page()
    # Block images/media/fonts to save bandwidth — we only need HTML + JS state
    await page.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in ("image", "media", "font", "stylesheet")
        else route.continue_(),
    )

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        content = await page.content()
        result = classify_imobiliare_page(content, url, page.url)
        if result["status"] == "expired":
            return result

        # ── Extract JSON-LD ───────────────────────────────────────────────────
        ld_blocks = await page.evaluate(
            '''() => [...document.querySelectorAll('script[type="application/ld+json"]')]
                     .map(s => s.textContent)'''
        )

        product = offer = listing = {}
        for block in ld_blocks:
            try:
                parsed = json.loads(block)
                graph = parsed.get("@graph", [])
                for node in graph:
                    t = node.get("@type", "")
                    if t == "Product":
                        product = node
                    elif t == "Offer":
                        offer = node
                    elif t == "RealEstateListing":
                        listing = node
            except Exception:
                pass

        if not product and not offer:
            # Page loaded but no structured data — treat as blocked
            return {"url": url, "status": "blocked", "message": "no JSON-LD found"}

        # ── Extract dataLayer listing entry ───────────────────────────────────
        dl_raw = await page.evaluate("() => JSON.stringify(window.dataLayer || [])")
        dl_data = json.loads(dl_raw)
        dl_entry = next((e for e in dl_data if "listing_id" in e), {})

        return {
            "url":    url,
            "status": "success",
            "ld": {
                "product": product,
                "offer":   offer,
                "listing": listing,
            },
            "dl": dl_entry,
        }

    except Exception as e:
        return {"url": url, "status": "blocked", "message": str(e)}
    finally:
        await page.close()


async def scrape_batch(urls: list[str]) -> list[dict]:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            proxy=_playwright_proxy(),
        )
        tasks = [fetch_url(context, url) for url in urls]
        results = await asyncio.gather(*tasks)
        await browser.close()
        return list(results)


def safe_serialize(obj):
    if isinstance(obj, dict):
        return {k: safe_serialize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [safe_serialize(i) for i in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    input_data = sys.stdin.read().strip()
    if not input_data:
        sys.exit(0)

    try:
        urls = json.loads(input_data)
    except Exception:
        urls = sys.argv[1:]

    if not urls:
        sys.exit(0)

    results = asyncio.run(scrape_batch(urls))

    try:
        print(json.dumps(safe_serialize(results), ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"SERIALIZATION ERROR: {e}\n")
        sys.exit(1)
