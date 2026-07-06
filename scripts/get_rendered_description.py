from bs4 import BeautifulSoup
import json
import asyncio
import sys
import io
import os
import re
from playwright.async_api import async_playwright

async def get_storia_manual(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            selector = 'div[data-sentry-element="DescriptionWrapper"]'
            await page.wait_for_selector(selector, timeout=10000)
            
            content = await page.content()
            
            soup = BeautifulSoup(content, 'html.parser')
            results = {}
            results['title'] = soup.find_all('h1',attrs={'data-cy':'adPageAdTitle'})[0].contents[0]
            
            price_section = soup.find_all('div',attrs={'data-sentry-element':'MainPriceWrapper'})[0].stripped_strings
            price = " ".join(price_section)
            results['price']  = price

            grid_items = soup.find_all('div',attrs={'data-sentry-element':'ItemGridContainer'})
            structured_data = {}
            for item in grid_items:
                details = item.find_all('div', recursive=False)
                if len(details) == 2:
                    label = details[0].get_text(strip=True).replace(':', '') 
                    value = details[1].get_text(strip=True)
                    structured_data[label] = value
            results['structured_data'] = structured_data

            desc_div = soup.find('div', attrs={'data-sentry-element': 'DescriptionWrapper'})
            
            if desc_div:
                results['description'] = desc_div.get_text(separator="\n", strip=True)

            return results

        except Exception as e:
            return f"Error during scrape: {e}"
        finally:
            await browser.close()

import asyncio
import sys
import json
from playwright.async_api import async_playwright


def classify_storia_page(content: str, url: str) -> dict:
    """Classify a Storia listing page using its explicit archive marker first."""
    lowered = content.lower()
    expired_markers = (
        'data-sentry-element="ExpiredAdContentLayout"',
        'data-cy="expired-ad-alert"',
        'arhiveaza:',
        'anunț arhivat',
        'anunt arhivat',
        'anunțul nu mai este disponibil',
        'anuntul nu mai este disponibil',
    )
    if any(marker.lower() in lowered for marker in expired_markers):
        return {"url": url, "status": "expired", "data": {}}

    try:
        raw_json = re.findall(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', content, flags=re.S)
        if raw_json:
            full_data = json.loads(raw_json[0])
            offer_data = full_data.get('props', {}).get('pageProps', {}).get('ad', {})
            # A live listing always has an `id` field in the ad object.
            # If __NEXT_DATA__ is present but the ad is empty (redirected to a search
            # or home page that has its own __NEXT_DATA__), the listing was removed.
            if not offer_data or not offer_data.get('id'):
                return {"url": url, "status": "expired", "data": {}}
            return {"url": url, "status": "success", "data": offer_data}
    except Exception:
        pass

    return {"url": url, "status": "blocked", "message": "no __NEXT_DATA__ and no expired marker"}


async def fetch_url(context, url):
    page = await context.new_page()
    # OPTIMIZATION: Block images and css to save 70% bandwidth/time
    await page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font", "stylesheet"] else route.continue_())

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # If the browser was redirected away from the listing URL, the ad was removed.
        # Storia listing URLs always contain /ro/oferta/; a redirect to a search or
        # home page is a definitive expiry signal even without any expiry marker.
        final_url = page.url
        if "/ro/oferta/" not in final_url:
            return {"url": url, "status": "expired", "data": {}}

        content = await page.content()
        return classify_storia_page(content, url)

    except Exception as e:
        # Playwright-level failure (timeout, navigation error) → blocked / transient
        return {"url": url, "status": "blocked", "message": str(e)}
    finally:
        await page.close()

def _playwright_proxy() -> dict | None:
    """Parse PROXY_URL env var into the dict Playwright's new_context() expects."""
    from urllib.parse import urlparse
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


async def scrape_batch(urls):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            proxy=_playwright_proxy(),
        )

        # Run all URLs in this batch simultaneously
        tasks = [fetch_url(context, url) for url in urls]
        results = await asyncio.gather(*tasks)

        await browser.close()
        return results

def safe_serialize(obj):
    """Recursively converts non-serializable objects to strings."""
    if isinstance(obj, dict):
        return {k: safe_serialize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [safe_serialize(i) for i in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        return str(obj)

if __name__ == "__main__":
    # Force UTF-8 for Windows stdout to avoid encoding crashes in the subprocess
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    # Read from stdin
    input_data = sys.stdin.read().strip()
    if not input_data:
        sys.exit(0)

    try:
        # Expecting a JSON list of URLs
        input_urls = json.loads(input_data)
    except Exception as e:
        # Fallback for manual testing via command line
        input_urls = sys.argv[1:]

    if not input_urls:
        sys.exit(0)

    # Run the scraper
    results = asyncio.run(scrape_batch(input_urls))

    try:
        # 1. Clean the data to ensure it's all JSON-safe
        clean_results = safe_serialize(results)
        
        # 2. Dump to string first
        output_string = json.dumps(clean_results, ensure_ascii=False)
        
        # 3. Print the final result
        print(output_string)
        
    except Exception as e:
        # If it STILL fails, we need to know why in the main pipeline's stderr
        sys.stderr.write(f"CRITICAL SERIALIZATION ERROR: {str(e)}\n")
        sys.exit(1)