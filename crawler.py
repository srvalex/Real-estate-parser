"""
crawler.py
──────────
Standalone crawl driver for automated background scraping.

Usage:
  python crawler.py --mode full
  python crawler.py --mode incremental
  python crawler.py --mode incremental --platform olx,storia --max-pages 3
  python crawler.py --mode full --platform imobiliare --max-pages 30
  python crawler.py --mode incremental --proxy-file proxies.txt
  python crawler.py --mode availability-check
  python crawler.py --mode availability-check --platform olx

proxies.txt format (one proxy per line, lines starting with # are ignored):
  http://user:pass@gate.smartproxy.com:10000
  http://user:pass@gate.smartproxy.com:10001

Windows Task Scheduler (incremental every 2h):
  Program: python
  Arguments: D:\\My weekend project\\crawler.py --mode incremental --proxy-file proxies.txt
"""

import argparse
import json
import os
import random
import sqlite3
import sys
import time
from datetime import datetime

import scrapers.http as _http
from scrapers import SCRAPERS
from scrapers.storia import StoriaScraper
from scrapers.imobiliare import ImobiliareRoScraper
from extractor import init_db, _save_new_listings

DISTRICTS_FILE = os.path.join(
    os.path.dirname(__file__), "Streamlit Interface", "districts.json"
)


class ProxyRotator:
    """
    One proxy per crawl session, round-robin across sessions.

    The chosen index is persisted in .crawler_proxy_state.json so each new
    invocation of crawler.py advances to the next proxy automatically.
    A health check is run at startup; if the selected proxy is dead, the next
    one is tried until one works (or the list is exhausted).
    """

    _STATE_FILE = os.path.join(os.path.dirname(__file__), ".crawler_proxy_state.json")

    # Wall-clock budget for the whole apply_for_session() health-check loop.
    # Each individual request already has its own timeout (10-15s), which
    # bounds a single check but not the loop overall: with a 100-proxy pool
    # that's ~1000s (16+ min) worst case if every one fails only the basic
    # connectivity check, or far more if many get further before failing a
    # platform check. Confirmed live (2026-08-23) that a fully-dead pool
    # actually fails fast in practice (most proxies refuse the connection
    # immediately rather than timing out), but a pool that hangs instead of
    # refusing outright has no such luck — this budget caps the damage
    # either way instead of relying on that being true every time.
    _MAX_HEALTH_CHECK_SECONDS = 60

    def __init__(self, proxies: list[str]):
        self._proxies = proxies

    @staticmethod
    def _parse_line(line: str) -> str:
        """
        Normalise proxy lines to http://user:pass@host:port.
        Accepts two formats:
          host:port:user:pass       (Webshare default export)
          http://user:pass@host:port  (standard URL)
        """
        line = line.strip()
        if line.startswith("http://") or line.startswith("https://"):
            return line
        parts = line.split(":")
        if len(parts) == 4:
            host, port, user, password = parts
            return f"http://{user}:{password}@{host}:{port}"
        return line  # unknown format — pass through as-is

    @classmethod
    def from_file(cls, path: str) -> "ProxyRotator":
        if not path or not os.path.exists(path):
            return cls([])
        with open(path, encoding="utf-8") as f:
            proxies = [
                cls._parse_line(l)
                for l in f
                if l.strip() and not l.strip().startswith("#")
            ]
        print(f"  [proxies] loaded {len(proxies)} proxy(s) from {path}")
        return cls(proxies)

    @classmethod
    def from_env(cls) -> "ProxyRotator":
        """Load proxies from the PROXY_LIST env var (newline or comma separated).

        Use this in Docker / Cloud Run where a local proxy file is not available.
        Set the env var in Cloud Run as a comma-separated list of proxy lines
        in Webshare format:  host:port:user:pass,host:port:user:pass,...
        """
        raw = os.environ.get("PROXY_LIST", "").strip()
        if not raw:
            return cls([])
        proxies = [
            cls._parse_line(line.strip())
            for line in raw.replace(",", "\n").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        print(f"  [proxies] loaded {len(proxies)} proxy(s) from PROXY_LIST env var")
        return cls(proxies)

    def _load_index(self) -> int:
        try:
            with open(self._STATE_FILE, encoding="utf-8") as f:
                return int(json.load(f).get("proxy_index", 0))
        except Exception:
            return 0

    def _save_index(self, idx: int) -> None:
        try:
            with open(self._STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"proxy_index": idx}, f)
        except Exception:
            pass

    def _verify(self, proxy_url: str) -> bool:
        """Return True if the proxy can reach the public internet."""
        from curl_cffi import requests as cffi_requests
        try:
            r = cffi_requests.get(
                "https://api.ipify.org?format=json",
                proxies={"https": proxy_url, "http": proxy_url},
                impersonate="chrome120",
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    def _verify_for_olx(self, proxy_url: str) -> bool:
        """Return True if the proxy is NOT blocked by OLX's anti-bot layer.

        Fetches a stable search page and checks for the l-card listing-card
        marker — present on every real OLX search results page (the same
        marker collect_links() itself relies on), absent on a rate-limited
        or bot-challenge response. Added after a real listing that returned
        a clean HTTP 410 (expired) via a direct connection was separately
        observed coming back "blocked" through the crawler's proxy path —
        OLX was the only platform with no proxy health check at all.
        """
        from curl_cffi import requests as cffi_requests
        try:
            r = cffi_requests.get(
                "https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/",
                proxies={"https": proxy_url, "http": proxy_url},
                impersonate="chrome120",
                timeout=15,
            )
            return r.status_code == 200 and 'data-cy="l-card"' in r.text
        except Exception:
            return False

    def _verify_for_storia(self, proxy_url: str) -> bool:
        """Return True if the proxy is NOT blocked by Storia's Cloudflare.

        Fetches a search page (stable URL, never expires) and checks for
        __NEXT_DATA__ — present on every real Storia page, absent on CF challenges.
        """
        from curl_cffi import requests as cffi_requests
        try:
            r = cffi_requests.get(
                "https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti/",
                proxies={"https": proxy_url, "http": proxy_url},
                impersonate="chrome120",
                timeout=15,
            )
            return r.status_code == 200 and "__NEXT_DATA__" in r.text
        except Exception:
            return False

    def _verify_for_imobiliare(self, proxy_url: str) -> bool:
        """Return True if the proxy is NOT blocked by Imobiliare.ro.

        Fetches the Bucharest rentals search page and checks for
        application/ld+json — present on every real Imobiliare page,
        absent when the proxy is blocked or served a bot-challenge page.
        """
        from curl_cffi import requests as cffi_requests
        try:
            r = cffi_requests.get(
                "https://www.imobiliare.ro/inchirieri-apartamente/bucuresti",
                proxies={"https": proxy_url, "http": proxy_url},
                impersonate="chrome120",
                timeout=15,
            )
            return r.status_code == 200 and "application/ld+json" in r.text
        except Exception:
            return False

    def apply_for_session(self, check_platforms: list[str] | None = None) -> str | None:
        """
        Pick one proxy for this crawl run (round-robin across runs).
        Tries proxies in order until one passes:
          1. Basic connectivity (api.ipify.org)
          2. Platform checks — verifies the proxy can reach a real page
             (not a CF challenge) for each platform in check_platforms.
        Returns the chosen proxy URL, or None if unavailable / all dead.

        Imobiliare is deliberately excluded here: its DataDome protection
        blocks the entire Webshare datacenter IP range (confirmed 0/100 pass
        rate), while direct/unproxied requests succeed fine. Gating proxy
        selection on an imobiliare check that can never pass meant the AND
        across platforms always failed, so every combined-platform crawl
        silently fell back to no proxy at all — including for Storia, which
        actually needs one. Imobiliare's own scraper always bypasses the
        session proxy (see ImobiliareRoScraper), so it's unaffected either way.
        """
        if not self._proxies:
            print("  [proxies] no proxy file supplied — crawling without proxy")
            return None

        start_idx = self._load_index()
        n = len(self._proxies)
        check_olx    = bool(check_platforms and "olx" in check_platforms)
        check_storia = bool(check_platforms and "storia" in check_platforms)
        deadline = time.time() + self._MAX_HEALTH_CHECK_SECONDS

        timed_out = False
        for offset in range(n):
            if time.time() >= deadline:
                timed_out = True
                break
            idx = (start_idx + offset) % n
            proxy = self._proxies[idx]
            display = proxy.split("@")[-1]  # hide credentials in logs
            print(f"  [proxies] checking {idx + 1}/{n}: {display} … ", end="", flush=True)
            if not self._verify(proxy):
                print("dead — trying next")
                continue
            if check_olx:
                print("connectivity OK … olx … ", end="", flush=True)
                if not self._verify_for_olx(proxy):
                    print("blocked by OLX — trying next")
                    continue
            if check_storia:
                print("connectivity OK … storia … ", end="", flush=True)
                if not self._verify_for_storia(proxy):
                    print("blocked by Cloudflare — trying next")
                    continue
            print("OK")
            self._save_index((idx + 1) % n)  # next session starts on idx+1
            _http.set_proxy(proxy)
            os.environ["PROXY_URL"] = proxy
            print(f"  [proxies] session proxy set to {display}")
            return proxy

        if timed_out:
            print(
                f"  [proxies] gave up after {self._MAX_HEALTH_CHECK_SECONDS}s "
                f"({offset}/{n} checked) — crawling without proxy"
            )
        else:
            print("  [proxies] WARNING: all proxies failed health check — crawling without proxy")
        _http.set_proxy(None)
        os.environ.pop("PROXY_URL", None)
        return None


def _load_districts() -> dict:
    with open(DISTRICTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _build_page_url(search_url: str, page_num: int) -> str:
    """Append ?page=N or &page=N to a search URL."""
    if page_num == 1:
        return search_url
    sep = "&" if "?" in search_url else "?"
    return f"{search_url}{sep}page={page_num}"


def _collect_page(scraper, search_url: str, page_num: int) -> list[str]:
    """Collect listing links from a single search result page."""
    page_url = _build_page_url(search_url, page_num)
    # Pass the pre-built paged URL and num_pages=1 so collect_links
    # uses it as-is without adding its own page parameter.
    links = scraper.collect_links(page_url, 1)
    seen: set[str] = set()
    unique = []
    for l in links:
        if l not in seen:
            seen.add(l)
            unique.append(l)
    return unique


_supabase_known: set[str] | None = None


def _load_supabase_known() -> set[str]:
    """Load all known URLs from Supabase once per process (cached in module state).

    This is the primary deduplication source in Docker/Cloud Run where SQLite
    starts empty on every container invocation.
    """
    global _supabase_known
    if _supabase_known is None:
        print("  [dedup] Loading known URLs from Supabase…", end="", flush=True)
        try:
            from db_utils import get_all_db_urls
            _supabase_known = get_all_db_urls()
            print(f" {len(_supabase_known):,} loaded")
        except Exception as e:
            print(f" failed ({e}) — SQLite-only deduplication this run")
            _supabase_known = set()
    return _supabase_known


def _known_urls(conn: sqlite3.Connection, urls: list[str]) -> set[str]:
    if not urls:
        return set()
    # Primary: check against the in-memory Supabase URL set (works in containers)
    known = {u for u in urls if u in _load_supabase_known()}
    # Secondary: also check SQLite (catches within-run saves before Supabase syncs)
    if conn:
        placeholders = ", ".join(["?"] * len(urls))
        rows = conn.execute(
            f"SELECT url FROM listings WHERE url IN ({placeholders})", urls
        ).fetchall()
        known |= {row[0] for row in rows}
    return known


def _owner(url: str) -> str:
    for sid, s in SCRAPERS.items():
        if s.owns_url(url):
            return sid
    return "unknown"


def _scrape_and_save(
    conn: sqlite3.Connection, urls_by_platform: dict[str, list[str]]
) -> int:
    """Scrape new URLs (grouped by platform) and persist them. Returns saved count."""
    all_new = []

    for pid, urls in urls_by_platform.items():
        if not urls:
            continue
        scraper = SCRAPERS[pid]
        print(f"    ↳ scraping {len(urls)} {scraper.display_name} listing(s)…")

        if isinstance(scraper, (StoriaScraper, ImobiliareRoScraper)):
            for i in range(0, len(urls), scraper.BATCH_SIZE):
                chunk = urls[i : i + scraper.BATCH_SIZE]
                batch = scraper.scrape_batch(chunk)
                # blocked → is_available is None; skip them (retried next crawl)
                all_new.extend(r for r in batch if r.get("is_available") is not None)
                time.sleep(random.uniform(0.8, 2.5))
        else:
            for url in urls:
                result = scraper.scrape_listing_with_status(url)
                status = result.get("status")
                if status == "success":
                    data = result["data"]
                    data["is_available"] = 1
                    all_new.append(data)
                elif status == "expired":
                    all_new.append(
                        {
                            "url": url,
                            "platform_id": pid,
                            "is_available": 0,
                            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )
                time.sleep(random.uniform(0.8, 2.5))

    if all_new:
        _save_new_listings(all_new, conn)
        # Keep in-memory Supabase set current so subsequent pages/URLs
        # of this run correctly see these URLs as already known.
        known = _load_supabase_known()
        for item in all_new:
            if item.get("url"):
                known.add(item["url"])
    return len(all_new)


def run_full_crawl(
    conn: sqlite3.Connection,
    platforms: list[str],
    districts: dict,
    max_price: int = 0,
    max_pages: int = 50,
) -> int:
    """
    Crawl every sector URL for each platform, paginating until the page is
    empty or max_pages is reached. Skips URLs already in SQLite.
    Proxy is applied once before this function is called (session-level).
    """
    import db_utils

    proxy_display = None
    _current_proxy = _http.get_proxy()
    if _current_proxy:
        proxy_display = _current_proxy.split("@")[-1]  # hide credentials
    run_id = db_utils.start_crawl_run_log(
        mode="full", platforms=platforms, max_price=(max_price or None),
        max_pages=max_pages, proxy_display=proxy_display,
    )

    full_sectors = list(districts.keys())
    total_new = 0
    scraped_this_run: set[str] = set()
    log_status = "success"
    error_message = None
    # (platform_id, exception) for every platform whose crawl raised. Caught
    # per-platform below instead of one try/except around the whole loop:
    # an unexpected error scraping one platform (e.g. a malformed record
    # crashing JSON serialization) used to abort every platform queued
    # after it in the same run, not just the one that failed.
    platform_errors: list[tuple[str, Exception]] = []
    # Platforms where EVERY search URL came back completely empty on its
    # very first page. Zero *new* listings on a non-empty page is routine;
    # a totally empty page 1 across every search URL for a platform is not
    # -- these are broad sector-wide Bucharest searches that should always
    # have real listings. This exact pattern (get_content() returning None
    # on a 403, silently treated the same as "no results") was how
    # Imobiliare being fully blocked went unnoticed in crawl_run_logs for
    # ~7 weeks (BUGS.md #9c) -- status stayed 'success' the entire time.
    platforms_with_no_data: list[str] = []

    try:
        for pid in platforms:
            try:
                scraper = SCRAPERS[pid]
                search_urls = scraper.build_search_urls(
                    selected_neighbourhoods=[],
                    districts=districts,
                    max_price=max_price,
                    full_sectors=full_sectors,
                )

                print(f"\n{'='*60}")
                print(
                    f"[{scraper.display_name}] full crawl — "
                    f"{len(search_urls)} search URLs, up to {max_pages} pages each"
                )

                empty_first_page_count = 0

                for search_url in search_urls:
                    url_new = 0
                    for page_num in range(1, max_pages + 1):
                        links = _collect_page(scraper, search_url, page_num)
                        if not links:
                            if page_num == 1:
                                empty_first_page_count += 1
                            print(f"  page {page_num}: empty → done with this URL")
                            break

                        known = _known_urls(conn, links)
                        new_links = [
                            l for l in links if l not in known and l not in scraped_this_run
                        ]
                        print(
                            f"  page {page_num}: {len(links)} links, "
                            f"{len(new_links)} new, {len(known)} cached"
                        )

                        if new_links:
                            by_platform: dict[str, list[str]] = {}
                            for url in new_links:
                                opid = _owner(url)
                                if opid != "unknown":
                                    by_platform.setdefault(opid, []).append(url)
                                else:
                                    print(f"    [skip] no scraper owns: {url}")
                            saved = _scrape_and_save(conn, by_platform)
                            scraped_this_run.update(new_links)
                            url_new += saved

                        time.sleep(random.uniform(1.5, 3.0))

                    print(f"  → {url_new} new listings from this search URL")
                    total_new += url_new

                if search_urls and empty_first_page_count == len(search_urls):
                    print(
                        f"  [warning] {scraper.display_name}: every search URL "
                        f"returned empty on page 1 — likely blocked or the "
                        f"platform is down, not genuinely zero listings"
                    )
                    platforms_with_no_data.append(pid)
            except Exception as e:
                print(f"  [platform-error] {pid} crawl aborted, moving to next platform: {e}")
                platform_errors.append((pid, e))
                continue

        print(f"\n✅ Full crawl done — {total_new} new listings saved.")
        notes = []
        if platforms_with_no_data:
            notes.append(
                "possible outage (empty page 1 on every search URL): "
                + ", ".join(platforms_with_no_data)
            )
        if platform_errors:
            if len(platform_errors) == len(platforms):
                # Every platform failed -- nothing succeeded this run, so
                # this really is a full failure: re-raise so the caller
                # (and the outer except below) treat it as one.
                raise platform_errors[-1][1]
            notes.append("; ".join(f"{pid}: {e}" for pid, e in platform_errors))
            log_status = "partial_failure"
        elif notes:
            log_status = "success_with_warnings"
        if notes:
            error_message = "; ".join(notes)
        return total_new
    except Exception as e:
        log_status = "failed"
        error_message = str(e)
        raise
    finally:
        db_utils.finish_crawl_run_log(
            run_id, listings_new=total_new, status=log_status, error_message=error_message,
        )


def run_incremental_crawl(
    conn: sqlite3.Connection,
    platforms: list[str],
    districts: dict,
    max_price: int = 0,
    stop_threshold: float = 0.8,
    max_pages: int = 5,
) -> int:
    """
    Incremental crawl: for each search URL, stop early once ≥stop_threshold
    fraction of the page's links are already in the DB. New listings always
    appear on page 1, so most runs finish in 1-3 pages per search URL.
    Proxy is applied once before this function is called (session-level).
    """
    import db_utils

    proxy_display = None
    _current_proxy = _http.get_proxy()
    if _current_proxy:
        proxy_display = _current_proxy.split("@")[-1]  # hide credentials
    run_id = db_utils.start_crawl_run_log(
        mode="incremental", platforms=platforms, max_price=(max_price or None),
        max_pages=max_pages, stop_threshold=stop_threshold, proxy_display=proxy_display,
    )

    full_sectors = list(districts.keys())
    total_new = 0
    scraped_this_run: set[str] = set()
    log_status = "success"
    error_message = None
    # See run_full_crawl's identical comment: catching per-platform instead
    # of once around the whole loop means one platform's unexpected failure
    # no longer aborts every platform queued after it in the same run.
    platform_errors: list[tuple[str, Exception]] = []
    # See run_full_crawl's identical comment: a totally empty page 1 across
    # every search URL for a platform (not just "0 new" on a real page) is
    # the signature of a platform-wide outage/block, not genuinely zero
    # listings -- this is how Imobiliare being fully blocked went unnoticed
    # in crawl_run_logs for ~7 weeks (BUGS.md #9c).
    platforms_with_no_data: list[str] = []

    try:
        for pid in platforms:
            try:
                scraper = SCRAPERS[pid]
                search_urls = scraper.build_search_urls(
                    selected_neighbourhoods=[],
                    districts=districts,
                    max_price=max_price,
                    full_sectors=full_sectors,
                )

                print(f"\n{'='*60}")
                print(
                    f"[{scraper.display_name}] incremental — "
                    f"{len(search_urls)} search URLs, "
                    f"max {max_pages} pages, stop at {stop_threshold:.0%} known"
                )

                empty_first_page_count = 0

                for search_url in search_urls:
                    url_new = 0
                    for page_num in range(1, max_pages + 1):
                        links = _collect_page(scraper, search_url, page_num)
                        if not links:
                            if page_num == 1:
                                empty_first_page_count += 1
                            break

                        known = _known_urls(conn, links)
                        new_links = [
                            l for l in links if l not in known and l not in scraped_this_run
                        ]
                        known_ratio = len(known) / len(links)
                        print(
                            f"  page {page_num}: {len(links)} links, "
                            f"{len(new_links)} new ({known_ratio:.0%} known)"
                        )

                        if new_links:
                            by_platform: dict[str, list[str]] = {}
                            for url in new_links:
                                opid = _owner(url)
                                if opid != "unknown":
                                    by_platform.setdefault(opid, []).append(url)
                                else:
                                    print(f"    [skip] no scraper owns: {url}")
                            saved = _scrape_and_save(conn, by_platform)
                            scraped_this_run.update(new_links)
                            url_new += saved

                        if known_ratio >= stop_threshold:
                            print(f"  → early exit ({known_ratio:.0%} ≥ {stop_threshold:.0%})")
                            break

                        time.sleep(random.uniform(1.0, 2.5))

                    total_new += url_new

                if search_urls and empty_first_page_count == len(search_urls):
                    print(
                        f"  [warning] {scraper.display_name}: every search URL "
                        f"returned empty on page 1 — likely blocked or the "
                        f"platform is down, not genuinely zero listings"
                    )
                    platforms_with_no_data.append(pid)
            except Exception as e:
                print(f"  [platform-error] {pid} crawl aborted, moving to next platform: {e}")
                platform_errors.append((pid, e))
                continue

        print(f"\n✅ Incremental crawl done — {total_new} new listings saved.")
        notes = []
        if platforms_with_no_data:
            notes.append(
                "possible outage (empty page 1 on every search URL): "
                + ", ".join(platforms_with_no_data)
            )
        if platform_errors:
            if len(platform_errors) == len(platforms):
                raise platform_errors[-1][1]
            notes.append("; ".join(f"{pid}: {e}" for pid, e in platform_errors))
            log_status = "partial_failure"
        elif notes:
            log_status = "success_with_warnings"
        if notes:
            error_message = "; ".join(notes)
        return total_new
    except Exception as e:
        log_status = "failed"
        error_message = str(e)
        raise
    finally:
        db_utils.finish_crawl_run_log(
            run_id, listings_new=total_new, status=log_status, error_message=error_message,
        )


def run_text_backfill() -> None:
    """Inline post-crawl text embedding using the ST model baked into this image."""
    from db_utils import get_listings_missing_text_embedding, get_client
    print("\n[backfill] text: checking for NULL embeddings…", flush=True)
    try:
        from sentence_transformers import SentenceTransformer as _ST
        _st     = _ST("paraphrase-multilingual-MiniLM-L12-v2")
        client  = get_client()
        total   = 0
        while True:
            rows = get_listings_missing_text_embedding(limit=64)
            if not rows:
                break
            texts = [f"{r.get('title', '')} {r.get('description', '')}".strip() for r in rows]
            urls  = [r["url"] for r in rows]
            embs  = _st.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            for url, emb in zip(urls, embs):
                vec = "[" + ",".join(str(float(v)) for v in emb.tolist()) + "]"
                try:
                    client.table("listings").update({"embedding": vec}).eq("url", url).execute()
                    total += 1
                except Exception as e:
                    print(f"  [backfill-text] skip {url}: {e}")
        print(f"[backfill] text: {total} embedding(s) filled.", flush=True)
    except Exception as e:
        print(f"[backfill] text backfill error: {e}", flush=True)


def _trigger_embedder_job() -> None:
    """Fire-and-forget trigger for the embedder-job Cloud Run Job.

    Uses google.auth default credentials (metadata server in Cloud Run,
    GOOGLE_APPLICATION_CREDENTIALS key file locally).
    Fails silently — the job will be retried on the next crawl run anyway.
    """
    region = "europe-west1"
    job    = "embedder-job"
    try:
        import google.auth
        import google.auth.transport.requests as ga_req
        import requests as _req
        creds, detected_project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "") or detected_project or ""
        if not project:
            print("[embed-trigger] no project ID — set GOOGLE_CLOUD_PROJECT env var", flush=True)
            return
        url = (
            f"https://run.googleapis.com/v2/projects/{project}"
            f"/locations/{region}/jobs/{job}:run"
        )
        creds.refresh(ga_req.Request())
        resp = _req.post(
            url,
            headers={"Authorization": f"Bearer {creds.token}"},
            json={},
            timeout=30,
        )
        if resp.status_code in (200, 202):
            print("[embed-trigger] embedder-job triggered.", flush=True)
        else:
            print(f"[embed-trigger] trigger failed ({resp.status_code}): {resp.text[:200]}", flush=True)
    except Exception as e:
        print(f"[embed-trigger] could not trigger embedder-job: {e}", flush=True)


def run_availability_check(
    platforms: list[str] | None = None,
    limit: int | None = None,
) -> None:
    """Check every non-expired listing and mark unavailable ones is_available=0.

    Skips listings already at is_available=0 (confirmed expired).
    Skips blocked/network errors — they'll be retried on the next weekly run.
    Flushes DB updates in chunks of 100 so progress is not lost if the job dies.

    A "tombstone" row (created when a listing was found expired on its very
    first scrape) only ever has url/platform_id/is_available/scraped_at set.
    If a later recheck finds it's actually live, a full scrape result is
    available right here — so it's saved via save_to_db() (upserts every
    field) instead of just flipping the flag, otherwise the row stays
    permanently blank even though is_available=1.
    """
    import db_utils

    run_id = db_utils.start_availability_check_log(platforms=platforms)
    total_checked = 0
    total_expired = 0
    total_blocked = 0
    log_status = "success"
    error_message = None

    try:
        print("\n[avail-check] Fetching listings to check…", flush=True)
        all_listings = db_utils.get_listings_for_availability_check(limit=limit)
        if not all_listings:
            print("[avail-check] Nothing to check.", flush=True)
            return

        by_platform: dict[str, list[str]] = {}
        for row in all_listings:
            pid = row.get("platform_id", "")
            url = row.get("url", "")
            if pid and url:
                by_platform.setdefault(pid, []).append(url)

        print(
            f"[avail-check] {len(all_listings)} listings across "
            f"{list(by_platform.keys())}",
            flush=True,
        )

        pending: list[dict] = []
        pending_rich: list[dict] = []

        def _flush(force: bool = False):
            nonlocal pending, pending_rich
            if pending and (force or len(pending) >= 100):
                db_utils.batch_update_availability(pending)
                pending = []
            if pending_rich and (force or len(pending_rich) >= 100):
                db_utils.save_to_db(pending_rich)
                pending_rich = []

        for pid, urls in by_platform.items():
            if platforms and pid not in platforms:
                continue
            scraper = SCRAPERS.get(pid)
            if not scraper:
                print(f"[avail-check] no scraper for '{pid}', skipping.", flush=True)
                continue

            print(f"[avail-check] {pid}: {len(urls)} listings…", flush=True)

            if pid == "olx":
                for idx, url in enumerate(urls, 1):
                    result = scraper.scrape_listing_with_status(url)
                    status = result.get("status")
                    if status == "expired":
                        pending.append({"url": url, "is_available": 0})
                        total_expired += 1
                        total_checked += 1
                    elif status == "success":
                        data = result["data"]
                        data["is_available"] = 1
                        pending_rich.append(data)
                        total_checked += 1
                    else:
                        # blocked → leave is_available unchanged, retried next run
                        total_blocked += 1
                    _flush()
                    if idx % 100 == 0:
                        print(
                            f"  [avail-check] olx {idx}/{len(urls)} — "
                            f"{total_expired} expired so far",
                            flush=True,
                        )
                    time.sleep(0.5)  # avoid hammering OLX
            else:
                # Storia / Imobiliare: scrape_batch already returns is_available per URL
                BATCH = 5
                for i in range(0, len(urls), BATCH):
                    chunk = urls[i : i + BATCH]
                    results = scraper.scrape_batch(chunk)
                    result_map = {r.get("url"): r for r in results if r.get("url")}
                    for url in chunk:
                        entry = result_map.get(url)
                        if entry is None:
                            continue
                        avail = entry.get("is_available")
                        if avail is None:
                            total_blocked += 1
                            continue
                        total_checked += 1
                        if avail == 1 and entry.get("platform"):
                            # Full scrape result (has title/price/etc, not just a
                            # bare tombstone flip) -- persist all of it.
                            pending_rich.append(entry)
                        else:
                            pending.append({"url": url, "is_available": avail})
                        if avail == 0:
                            total_expired += 1
                    _flush()
                    time.sleep(1.5)

            _flush(force=True)
            print(
                f"[avail-check] {pid}: done. "
                f"{total_checked} definitive checks, {total_blocked} blocked, "
                f"{total_expired} expired total.",
                flush=True,
            )

        _flush(force=True)
        print(
            f"\n[avail-check] Finished: {total_checked} definitive checks, "
            f"{total_blocked} blocked, {total_expired} newly marked expired.",
            flush=True,
        )
    except Exception as e:
        log_status = "failed"
        error_message = str(e)
        raise
    finally:
        db_utils.finish_availability_check_log(
            run_id,
            listings_checked=total_checked,
            listings_expired=total_expired,
            listings_blocked=total_blocked,
            status=log_status,
            error_message=error_message,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Automated real estate crawler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["full", "incremental", "availability-check"],
        default="incremental",
        help="full = all pages; incremental = early-exit; availability-check = mark expired listings",
    )
    parser.add_argument(
        "--platform",
        default="all",
        help="Comma-separated list: olx,storia,imobiliare  (default: all)",
    )
    parser.add_argument(
        "--max-price",
        type=int,
        default=0,
        help="Max rent price in EUR; 0 = no filter (default: 0)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Max search-result pages per URL (default: 5 for incremental, 50 for full)",
    )
    parser.add_argument(
        "--stop-threshold",
        type=float,
        default=0.8,
        help="Incremental early-exit: stop when this fraction of a page is already known (default: 0.8)",
    )
    parser.add_argument(
        "--proxy-file",
        default=None,
        help="Path to a text file with one proxy URL per line (http://user:pass@host:port)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="For availability-check: process only the first N listings and stop.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously, sleeping a random interval between crawls (use with Task Scheduler at boot)",
    )
    parser.add_argument(
        "--min-interval",
        type=int,
        default=110,
        help="Minimum minutes between crawls in --loop mode (default: 110 = 1h50m)",
    )
    parser.add_argument(
        "--max-interval",
        type=int,
        default=180,
        help="Maximum minutes between crawls in --loop mode (default: 180 = 3h)",
    )
    args = parser.parse_args()

    # Resolve platforms
    if args.platform == "all":
        platforms = list(SCRAPERS.keys())
    else:
        platforms = [p.strip() for p in args.platform.split(",")]
        unknown = [p for p in platforms if p not in SCRAPERS]
        if unknown:
            print(f"❌ Unknown platform(s): {', '.join(unknown)}")
            sys.exit(1)

    # Default max_pages per mode
    if args.max_pages is None:
        args.max_pages = 5 if args.mode == "incremental" else 50

    if args.proxy_file:
        rotator = ProxyRotator.from_file(args.proxy_file)
    elif os.environ.get("PROXY_LIST"):
        rotator = ProxyRotator.from_env()
    else:
        rotator = ProxyRotator([])

    if args.mode == "availability-check":
        rotator.apply_for_session(check_platforms=platforms)
        run_availability_check(
            platforms=None if args.platform == "all"
            else [p.strip() for p in args.platform.split(",")],
            limit=args.limit,
        )
        sys.exit(0)

    districts = _load_districts()

    run_count = 0
    while True:
        run_count += 1
        conn = init_db()

        print(
            f"\n{'#'*60}\n"
            f"🕷️  Crawl session #{run_count}\n"
            f"   mode={args.mode}  platforms={platforms}  "
            f"max_pages={args.max_pages}  max_price={args.max_price or 'none'}  "
            f"proxies={len(rotator._proxies)}\n"
            f"   started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        rotator.apply_for_session(check_platforms=platforms)

        if args.mode == "full":
            run_full_crawl(
                conn,
                platforms,
                districts,
                max_price=args.max_price,
                max_pages=args.max_pages,
            )
        else:
            run_incremental_crawl(
                conn,
                platforms,
                districts,
                max_price=args.max_price,
                stop_threshold=args.stop_threshold,
                max_pages=args.max_pages,
            )

        conn.close()
        print(f"   finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Post-crawl: text embeddings inline (ST model in this image),
        # then trigger the separate embedder-job for image embeddings.
        run_text_backfill()
        _trigger_embedder_job()

        if not args.loop:
            break

        delay_minutes = random.uniform(args.min_interval, args.max_interval)
        delay_seconds = delay_minutes * 60
        wake_at = datetime.fromtimestamp(time.time() + delay_seconds)
        print(
            f"   next crawl in {delay_minutes:.0f} min "
            f"(~{wake_at.strftime('%H:%M')})"
        )
        time.sleep(delay_seconds)


if __name__ == "__main__":
    main()
