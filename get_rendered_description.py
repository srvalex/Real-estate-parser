from bs4 import BeautifulSoup
import json
import asyncio
import sys
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

async def get_storia_data(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            # 1. Navigate
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # 2. Extract the JSON from the __NEXT_DATA__ script tag directly from the DOM
            # This is much faster and more reliable than BeautifulSoup
            raw_json = await page.evaluate('() => document.getElementById("__NEXT_DATA__").textContent')
            
            if not raw_json:
                return {"status": "error", "message": "JSON tag not found"}

            full_data = json.loads(raw_json)
            # Drill down to the actual listing data
            offer_data = full_data.get('props', {}).get('pageProps', {}).get('ad', {})
            
            return {"status": "success", "data": offer_data}

        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    
    target_url = sys.argv[1]
    result = asyncio.run(get_storia_data(target_url))
    result['URL'] = target_url
    # We print ONLY the final JSON result to stdout
    print(json.dumps(result, ensure_ascii=False))