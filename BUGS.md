# Known Bugs / Open Findings

Living list of everything identified so far that is **not yet fixed**. Fixed items are
noted only where relevant for context; see git history / MIGRATION_PLAN.md for what's
already landed (CLIP-gating fix, observability tables, BNR currency conversion,
`_clean_record` drop logging, `autofill_rooms` trigger fix in the SQL file, the
`max_price_eur` filter primitive in `db_utils.query_listings_by_district` and
its wiring into `home.py`, `query_listings_by_district`'s column scoping, the
168 blank-Imobiliare-row cleanup via `scripts/mark_blank_listings_unavailable.py`,
the `-1`-row availability-recheck fix, chunked+retried candidate-scoped
semantic search, the anon/service-role key hard split, per-platform
crawl exception isolation, the OLX blocked-listing miscount fix, the proxy
health-check time budget, and the Imobiliare-outage visibility fix).

Every fix must ship with a real, executed unit test (see `[[feedback-unit-testing-required]]`
in memory) — fail pre-fix, pass post-fix, full suite green after.

---

## Data correctness

### 1. ~~`query_listings_by_district` times out on large districts~~ — FIXED
Was: `query_listings_by_district(['Militari'])` threw Postgres `57014
canceling statement due to statement timeout`, reproducing even with no price
filter applied. Root cause confirmed: `SELECT *` was pulling all 27 columns
— including the `embedding` (384-dim) and `image_embedding` (512-dim) vector
columns and the `extras` JSONB blob — for every row, none of which the
Streamlit results pipeline actually reads off this query (semantic-search
similarity is joined back in by url via the RPCs separately). Fixed in two
passes: first scoped the `SELECT` down to 24 columns (dropping just the two
vectors + `extras`), then trimmed further to the 13 columns
`results.py`/`pipeline/utils.py` actually read (`url, title, description,
price_eur, price_numeric, price_currency, district, location_full, rooms,
area_sqm, property_type, platform, image_urls`) — the other 11 columns
(`is_available`, plus fields only used by the separately-scoped Analytics
tab query) were dead weight on this path. Live-verified: `Militari` went
from an outright timeout → 3.7s (24-column pass) → 2.4s (13-column pass).
Tests: `tests/db/test_query_listings_by_district_columns.py`.

**New finding surfaced by this fix, not yet addressed:** `Militari` returns
exactly 1000 rows — PostgREST's default max page size — so it's unclear
whether that's the true count or a silent truncation. `query_listings_by_district`
has no pagination; if a district genuinely has >1000 available listings,
results are being silently cut off with no indication to the caller. Needs
either explicit pagination (`.range()` looping) or a `count="exact"` check
against the real row count to confirm this isn't already happening.

### 2. ~~`max_price_eur` not wired into the live Streamlit call site~~ — FIXED
Was: `streamlit_interface/components/home.py` called
`query_listings_by_district(all_districts)` with no `max_price_eur` argument
— the currency-aware SQL filter existed and was tested, but the app never
actually used it, so every search fetched every row for the selected
districts and filtered client-side only, after the fact.
Fixed: `home.py` now passes `max_price_eur=max_price` (the user's price cap,
already resolved including NLP autofill by that point in the function).
Tests: `tests/pipeline/test_home_max_price_wiring.py` — drives `render_home()`
through a full mocked-Streamlit "fill form, click search" pass and asserts
the price cap reaches `query_listings_by_district`, including the `0` = "no
limit" case.

### 3. Studio listing stuck with `rooms = '5'` (false positive)
One row (a Studio unit, `rooms` false-set from a window spec — "geam tripan cu
5 camere de izolare fonica" — not an actual room count) cannot be cleared to
NULL because the **old** `autofill_rooms` trigger is still live in the
Supabase project and re-fires on `UPDATE ... SET rooms = NULL`, immediately
resetting it back to `'5'`. The corrected trigger SQL is already in
`scripts/supabase_schema.sql` (Section 6) but has not been applied to the live
database yet.
**Blocked on user action:** run the updated Section 6 SQL against the live
Supabase project. Once applied, the Studio row's `rooms` can be corrected to
NULL (Claude can do this part once unblocked).

### 3b. ~~168 blank "phantom" Imobiliare listings shown as live~~ — FIXED
Found while investigating a live "AI ranking unavailable: No pgvector
matches" report: 249 available listings had no embedding, and 168 of those
had **no content at all** — no title, description, price, or district.
Root-caused to the old Imobiliare scraper (pre-`classify_imobiliare_ld_graph`
fix) misclassifying bot-challenge/blocked pages as a successful scrape.
Confirmed via `first_seen_at` that every affected row was created between
2026-06-16 and 2026-07-05 — before that fix — and none since, so this was a
one-time backlog, not an active leak. These rows were doubly harmful: they
could never get an embedding (nothing to embed, hence the AI-ranking error),
and they rendered as blank/broken cards in normal search results since
`is_available=1` told the app to treat them as real listings.
Fixed by flipping all 168 to `is_available=0` via the new
`scripts/mark_blank_listings_unavailable.py` (dry-run by default, `--execute`
to apply — used here with explicit user sign-off on this exact disposition).
Tests: `tests/db/test_mark_blank_listings_unavailable.py`. Live-verified:
249 → 81 remaining available-but-unembedded rows, and all 81 have real
content — legitimate candidates for `scripts/backfill_embeddings.py`, not
more corruption.

### 3c. ~~Storia listings systematically dropped 3-8 real scraped fields, every time~~ — FIXED
Found via the `_clean_record` drop-logging added earlier this session,
observed live on essentially every Storia listing in the 2026-08-23 test
crawl: `building_floors_num`, `building_material`, `building_type`,
`construction_status`, `deposit`, `free_from`, `windows_type`, and
`remote_services` get scraped successfully but were being silently
discarded because none of them are in `_CANONICAL_COLUMNS`. Unlike the
earlier `_clean_record` finding (which was about *catching* silent drops),
this was the drop-logging doing its job and immediately surfacing a real,
systematic data-completeness gap: real building metadata Storia provides
for nearly every listing was being thrown away on ingestion, not a one-off.
Fixed by folding non-canonical fields into `extras` (already JSONB, already
used for platform-specific data) instead of discarding them —
`_clean_record` step 7 now merges them in (existing `extras` keys win on a
name collision) rather than dropping. Intended for later use (per-listing
building details in the UI), not surfaced anywhere yet. Tests:
`tests/db/test_clean_record.py::NonCanonicalColumnStrippingTests` (3 new
cases: folded into extras, existing extras dict preserved, collision
handling). Live-verified against a realistic Storia-shaped record (extras
already holding the full raw ad payload) — the flattened fields land
alongside the existing raw data without clobbering it.

**Smaller, unconfirmed observation from the same crawl:** 6 of 95 new
Storia listings this run used a `/hpr/...` URL path (Storia's
promoted-listing format, vs. the normal `/ro/oferta/...` path) and were all
classified `is_available=0` (expired) on first contact — correctly saved as
minimal tombstones per the existing documented design, not the blank-row
bug from #3b (`is_available` was `0` here, not `1`). Could be genuinely
expired promoted listings still showing in search results, or a
misclassification specific to the `/hpr/` page layout — not enough evidence
either way yet, flagging in case it recurs.

### 4. `property_type` / `rooms` may still be fragmented across old vs. new rows
Code now writes ASCII forms (`"Garsoniera"`), but `documentation.txt`
describes diacritic forms (`"Garsonieră"`) as canonical at an earlier point.
`apply_filters` does exact-string `.isin()` matching, so any leftover
diacritic-form rows would be invisibly excluded from filtered results.
**Not yet audited** — needs a one-off `SELECT DISTINCT property_type FROM
listings` (and same for `rooms`) against production to confirm whether any
stale diacritic rows actually exist.

### 4b. ~~`get_listings_for_availability_check` never re-checks `is_available = -1` rows~~ — FIXED
Was: the query was `.or_("is_available.eq.1,is_available.is.null")` — this
deliberately skipped `0` (confirmed expired, correct) but also
unintentionally skipped `-1` (blocked/transient, per the schema comment in
`scripts/supabase_schema.sql`). A listing marked `-1` because a scrape
attempt was blocked/rate-limited never got retried by the crawler's
availability-check pass again — stuck in limbo instead of being re-verified
on the next run. Separate from the user-facing `query_listings_by_district`
filter (which correctly excludes `-1` from what users see, regression-tested
in `tests/db/test_query_listings_by_district_columns.py`) — this was the
crawler-side companion bug.
Fixed by adding `is_available.eq.-1` to the `.or_()` filter. Test:
`tests/db/test_availability_check_includes_blocked_rows.py`.

### 5. Cross-platform listing dedup not implemented
Same physical property listed on OLX/Storia/Imobiliare under different URLs
is not deduplicated (Roadmap P5). Inflates both search result counts and the
price-fairness baseline averages (`get_price_stats`) since the same listing
can be counted multiple times.

---

## Search / ranking quality

### 6. No offline eval of ranking quality
Every fusion/weight decision (RRF, `K=60`, `W_TEXT`/`W_IMAGE`, badge
thresholds) is justified by reasoning, never measured against labeled
relevance data. No regression signal exists if a future change silently makes
ranking worse. Worth building even a small labeled query→listing eval set
before tuning anything else in this path.

### 7. ~~Semantic search silently fell back to unscoped when the candidate set was large~~ — FIXED
`db_utils.search_by_text_vibe`/`search_by_image_embedding` already supported
scoping to a caller-supplied `candidate_urls` list (added for image search),
and `pipeline/utils.py`'s `apply_ai_scores` already used it — but only when
the filtered candidate set was ≤2000 URLs; beyond that it fell back to an
unscoped global top-1000 search, silently reopening the exact "good match
outside the global cutoff gets no score at all" problem this scoping exists
to prevent (e.g. selecting many districts, or applying no price/room filter).
Fixed by moving the size limit out of `pipeline/utils.py` entirely: it now
always passes the full candidate set, and `db_utils.search_by_text_vibe`/
`search_by_image_embedding` split a large `candidate_urls` list into batches
of `_RPC_CANDIDATE_CHUNK_SIZE` (1000) and merge the results, retrying an
individual failed batch once via `_rpc_with_retry` before giving up on it.
Tests: `tests/db/test_db_utils_scoped_search.py` (chunking + retry),
`tests/ranking/test_apply_ai_scores_candidate_scoping.py` (no more size cap).

**New finding from live-testing this fix (2026-08-23):** a candidate batch
of 2000 URLs reproducibly hit Postgres's statement_timeout (57014) on the
`match_listings` RPC, while 1000-URL batches mostly succeeded — but even at
1000, an individual call occasionally timed out on its *first* attempt with
a given candidate-array shape, then succeeded quickly on an immediate retry
with a *different* 1000-URL array. That pattern (slow once per new call
shape, fast on repeats) looks like a cold query-plan cost rather than a
genuine capacity limit — worth a proper DB-side look (e.g. whether
Supabase's connection pooler prevents prepared-statement plan caching for
this RPC, or whether `url = ANY(candidate_urls)` combined with the pgvector
`ORDER BY` is choosing a bad plan for larger arrays). The retry is a
mitigation that made 3/3 live trials on a 4000-URL candidate set score
4000/4000 with no losses, not a fix for whatever is actually slow.

---

## Security / architecture

### 8. ~~Shared Supabase service-role key between crawler and Streamlit app~~ — FIXED (code side)
Was: not every read path in the Streamlit app had been audited to confirm
it never uses the service-role client, and `get_anon_client()` silently
fell back to the service-role key (with just a one-time `print()` warning)
if `SUPABASE_ANON_KEY` wasn't configured — a missing env var would quietly
hand out full read/write/delete instead of failing loudly.
Audited: zero call sites anywhere in `streamlit_interface/` use `get_client()`
or any function that uses it internally — every Streamlit-facing read
already went through `get_anon_client()`-backed functions
(`query_listings_by_district`, `search_by_text_vibe`, `fetch_analytics_data`,
etc.), confirmed via `tests/db/test_db_utils_client_routing.py`'s existing
per-function tests. Fixed the fallback: `get_anon_client()` now raises
`RuntimeError` if `SUPABASE_ANON_KEY`/`SUPABASE_PUBLISH_KEY` isn't set,
instead of degrading into the service-role key — safe to do now that RLS is
confirmed working. Added a regression guard,
`StreamlitNeverUsesServiceRoleClientTests`, that scans every `.py` file
under `streamlit_interface/` for a literal `get_client(` call, so a future
change reintroducing it fails a test instead of shipping silently — verified
it actually catches an injected violation before removing it. Live-verified
`get_anon_client()` still works correctly against production with the real
local `.env` credentials.

**Not fixed, and can't be from code:** the Streamlit app itself hasn't been
deployed publicly yet (`Roadmap.md`: "Streamlit app hosting — Not started").
Whoever deploys it needs to give that environment only `SUPABASE_URL` +
the anon key — never the service-role key. That's a deployment-config step
for whenever it actually ships, not something this repo can enforce.

---

## Crawler / scraper resilience

### 9a. ~~No exception isolation in run_full_crawl/run_incremental_crawl~~ — FIXED
Found auditing `crawler.py` end-to-end for unhandled failure paths. The
entire `for pid in platforms:` loop sat inside one try/except — an
unexpected error crawling platform N (not just a network blip; those were
already caught deeper) aborted every platform queued after it in the same
run, not just skipped. The concrete mechanism: `_save_new_listings()`
(`extractor.py`) was called with no try/except around it, and its
`image_urls`/`extras` → JSON serialization step had no error handling at
all — a single unexpected non-serializable value in one scraped item raised
uncaught, crashing that whole batch before anything was written. This is
the same failure class as the already-fixed Storia `extras` dict SQLite
crash (that fix only patched the specific dict case; the general risk was
still wide open). Hadn't visibly recurred, likely masked by the real
`crawler-job`'s `maxRetries: 3` silently retrying a single occurrence.
Fixed two places:
  - Each platform's crawl in `run_full_crawl`/`run_incremental_crawl` is now
    caught individually; the loop continues to the next platform on
    failure. If some platforms succeed and others don't, the run finishes
    with `crawl_run_logs.status='partial_failure'` (new value) listing
    every failed platform, instead of raising and discarding whatever the
    working platforms found. If *every* platform failed, that's still a
    full failure (raise, `status='failed'`) — nothing partial about it.
  - `extractor._save_new_listings`'s per-item JSON serialization is now
    isolated: a bad field is left unconverted for just that one item (it
    fails at the already-safe, skip-and-continue SQLite/Supabase write
    layer instead) rather than crashing every item in the batch.
Tests: `tests/crawler/test_crawl_run_logging.py` (`test_one_platform_failing_does_not_stop_the_others`
for both functions — confirmed erroring pre-fix, passing post-fix via a
literal patch revert-and-restore), `tests/extractor/test_save_new_listings_json_serialization.py`
(`test_non_serializable_field_on_one_item_does_not_lose_the_rest_of_the_batch`).
Full suite: 195/195.

**Follow-up items, also fixed (2026-08-27):**
- `ProxyRotator.apply_for_session` now enforces a `_MAX_HEALTH_CHECK_SECONDS`
  (60s) wall-clock budget across the whole proxy health-check loop, on top
  of each individual request's own timeout — bounds worst-case time
  regardless of pool size or how many proxies hang instead of refusing
  outright. Test: `tests/crawler/test_crawler_proxy_rotator.py::test_gives_up_after_the_time_budget_instead_of_checking_every_proxy`
  (confirmed erroring pre-fix — checked all 5 mock proxies instead of
  stopping at 2 — passing post-fix).
- Added `tests/crawler/test_crawl_orchestration.py`: direct coverage of
  `run_full_crawl`'s dedup (an already-known URL is never re-scraped) and
  `max_pages` boundary (pagination stops exactly there even when every page
  keeps returning fresh links), `run_incremental_crawl`'s early-exit
  (stops once `known_ratio` crosses `stop_threshold`, well before
  `max_pages`), and `run_availability_check`'s per-platform dispatch (a
  platform excluded by `--platform` is never even queried). These loops had
  no direct tests before — only the logging wrapper and the isolation fix
  did.
Full suite: 206/206.

### 9. Proxy/crawler resilience gaps
- Proxy health is only checked once, at session start — no mid-run failover
  if a proxy degrades partway through a crawl.
- No OLX-specific proxy verification (only `_verify_for_olx` for one target
  site so far — confirm coverage).
- No circuit breaker on URLs that fail permanently (e.g. a site starts
  blocking a specific scraper) — the crawler will keep retrying them every
  run instead of backing off.
- Imobiliare scraping never uses a proxy at all.

### 9b. ~~Entire `proxy-list` secret was dead~~ — FIXED (does not fix Imobiliare, see #9c)
Found running a real crawl via a temporary Cloud Run Job (`crawler-test-job`,
2026-08-23, `--mode full --max-pages 1`, all platforms) using the exact same
`proxy-list`/`supabase-key` secrets and service account as the production
`crawler-job`: `[proxies] checking 100/100: ... dead — trying next` →
`[proxies] WARNING: all proxies failed health check — crawling without
proxy`. Every one of the 100 proxies in the secret had died. OLX/Storia still
completed fine without a proxy that run, but a fully-dead pool is still a
real risk (repeatedly crawling from Cloud Run's shared egress IP with no
proxy at all is what eventually gets that IP rate-limited/blocked too).
Fixed: user provided a fresh Webshare proxy-list download link, fetched the
current 100-proxy list, verified a 5-proxy random sample all pass a live
`ipv4.webshare.io` check, and pushed it as a new version of the `proxy-list`
Secret Manager secret (`gcloud secrets versions add proxy-list --data-file=...`).
Re-verified live: a follow-up Cloud Run test picked `193.239.176.140:5546`
as the session proxy and it passed health check immediately (`OK`), vs. the
prior run's 100/100 failures.

**Correction — this does NOT fix Imobiliare, initial assumption was wrong.**
The first test run's reasoning ("Imobiliare 403'd because the whole proxy
pool was dead") doesn't hold up: `scrapers/imobiliare.py`'s `collect_links`
already runs with `use_proxy=False` unconditionally, and `_fetch_batch_raw`'s
subprocess explicitly pops `PROXY_URL` from its environment — both by
existing, documented design ("Imobiliare's DataDome protection blocks the
whole Webshare datacenter proxy pool"). Re-ran the same scoped test against
Imobiliare only, this time with the freshly-verified working proxy pool
available: **identical result, 403 on all 6 sector pages, 0 new listings.**
The proxy pool's health was never the variable that mattered here — see #9c.

### 9c. Imobiliare has been completely broken in production for ~7 weeks — visibility fixed, root cause is not a code fix
The most recent Imobiliare listing in the entire database has
`first_seen_at = 2026-07-08` — **46 days before this was found (2026-08-23)**,
out of 3,644 total Imobiliare rows. Every one of Imobiliare's 6 sector search
pages now returns `HTTP Error 403` on every crawl (confirmed twice live via
Cloud Run test runs, both with and without a working proxy pool — see #9b,
since Imobiliare deliberately never uses the proxy pool at all). This had
been silently invisible: `crawl_run_logs.status` recorded `success` for
every run, because a 403'd search page was handled internally as "0 links
found on this URL," identically to a genuinely empty one.

**Two separate things here — only one has a real fix:**
- **Visibility — FIXED.** `run_full_crawl`/`run_incremental_crawl` now
  track, per platform, whether *every* search URL came back completely
  empty on page 1. Zero new listings on a real (non-empty) page is routine;
  an empty page 1 across every one of Bucharest's broad sector-wide
  searches is not. When that happens the run now finishes with
  `crawl_run_logs.status='success_with_warnings'` naming the affected
  platform (folded into `'partial_failure'` if another platform also
  raised outright), instead of an indistinguishable plain `'success'`.
  Tests: `tests/crawler/test_crawl_run_logging.py`
  (`test_platform_with_empty_page_one_on_every_search_url_gets_flagged` for
  both crawl functions, plus `test_real_content_with_zero_new_listings_is_not_flagged_as_an_outage`
  confirming the routine case is untouched) — confirmed erroring pre-fix,
  passing post-fix. A 7-week outage like this will now surface on the very
  first affected run instead of by accident.
- **Root cause — no code fix exists.** Likely either Cloud Run's shared
  egress IP range is on Imobiliare's DataDome blocklist (very common for
  cloud-provider IP ranges with bot-protection vendors), or Imobiliare
  changed something in their detection since early July. The code already
  avoids proxying Imobiliare on purpose (proxying makes it *worse* — the
  Webshare datacenter pool is blocked outright), so there's no proxy
  setting or retry logic that fixes this from within the codebase. A real
  fix needs a residential/mobile proxy specifically for Imobiliare — a
  different product tier than what's currently provisioned, and a
  cost/vendor decision, not an engineering one.

---

## Test coverage gaps

### 10. Core NLP/filtering functions still untested
`apply_filters` (Streamlit-side filtering) and `extract_filters` (spaCy-based
NLP autofill) have no unit tests yet — only the CLIP-gating path, `rrf_fuse`,
`_clean_record`, BNR/currency logic, and the observability logging functions
have been covered so far this project.

---

## Lower priority (recorded for completeness, not yet scoped)

- Subprocess-per-batch overhead in the crawler (each scraping batch pays
  process-spawn cost rather than reusing a worker).
- Dead/unused parameters lingering in some functions (e.g. `skip_embed`,
  `server_url`) — candidates for removal once confirmed unused.
