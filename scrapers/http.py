"""
scrapers/http.py
────────────────
Shared HTTP client used by all platform scrapers.

Proxy support
─────────────
Call set_proxy("http://user:pass@host:port") before a crawl session to route
all curl_cffi requests through that proxy.  set_proxy(None) disables it.
Playwright subprocesses read the PROXY_URL environment variable — the crawler
sets it in sync with set_proxy() so both layers stay consistent.
"""

from curl_cffi import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}

_current_proxy: str | None = None


def set_proxy(proxy_url: str | None) -> None:
    global _current_proxy
    _current_proxy = proxy_url


def get_proxy() -> str | None:
    return _current_proxy


def get_content(url: str) -> str | None:
    proxies = (
        {"https": _current_proxy, "http": _current_proxy} if _current_proxy else None
    )
    try:
        response = requests.get(
            url, headers=HEADERS, impersonate="chrome120", proxies=proxies
        )
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"  [fetch error] {url}: {e}")
        return None
