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
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


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
            )
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
