# Product Roadmap
> Last updated: May 2026
> Stack: Streamlit · Sentence Transformers · pgvector · CLIP · Supabase (Postgres) · Google Cloud Run · Webshare proxies

---

## Current State

Working demo with the following complete:
- Natural language prompt → semantic ranking via `paraphrase-multilingual-MiniLM-L12-v2` (ChromaDB `web_archive`)
- CLIP image embeddings pipeline — Colab GPU server + local text encoder, ChromaDB `listing_image_embeddings`
- Score fusion: 60% text + 40% image (listings with images), text-only fallback
- Template photo picker — select reference photos → embed → drive visual similarity search; embeddings **pre-computed** into `template_photos/embeddings.json` (no runtime model load)
- Streamlit UI with property cards, cover photo + thumbnail strip, similarity badges
- Scrapers: **OLX**, **Storia**, **Imobiliare.ro** (all three working)
- Dual persistence: Firestore + SQLite → **migrated to Supabase**
- 3-state availability: `1` = live, `0` = confirmed expired (skip reruns), `-1` = blocked/transient (retry)
- OLX HTTP 410 expired detection; Imobiliare redirect-to-homepage expired detection
- Backfill scripts for image URLs (all 3 platforms) and image embeddings (resumable)
- Folder structure: `embedders/`, `pipeline/`, `static/`, `scrapers/`, `scripts/`
- **Automated crawler** (`crawler.py`) — full + incremental + **availability-check** modes, session-level proxy rotation
- **Proxy rotation** — Webshare datacenter proxies, one proxy per crawl session, health check + auto-fallback, persistent index across runs
- **Cloud crawler** — Docker image on Google Artifact Registry, Cloud Run Job (`crawler-job`, europe-west1, 4Gi), scheduled daily at 02:00 UTC (incremental) and weekly (full) via Cloud Scheduler. Credentials in Secret Manager. **Incremental runs confirmed working in production.**
- **Availability check scheduler** — dedicated `avail-check-job` Cloud Run Job (same image as `crawler-job`, `--mode availability-check`), triggered Mon + Thu 03:00 UTC by Cloud Scheduler. Runs independently of the crawler job.
- **Price fairness indicator** — `apply_price_fairness()` in `pipeline/utils.py`: aggregates avg price per (district, rooms) bucket from Supabase, adds `price_fairness` column to df, rendered as green/red badge on listing cards.
- **Embedder Cloud Run Job** (`embedder-job`, europe-west1, 4Gi) — replaces the always-on Cloud Run Service (deleted May 2026, was costing ~$1/day from `--min-instances 1`). `embedding-service/embed_job.py` loads ST + CLIP locally, runs text + image backfill against Supabase, exits. Triggered by `_trigger_embedder_job()` in `crawler.py` at the end of each crawl. Build via `embedding-service/cloudbuild.yaml` (project-root context required for `db_utils.py`).
- **Post-crawl embedding** — split into two steps: (1) `run_text_backfill()` inline in crawler (ST model baked into crawler image, completes in seconds); (2) `_trigger_embedder_job()` fires `embedder-job` asynchronously for image embeddings (CLIP, slower). Streamlit query-time text embedding uses local `@st.cache_resource` ST model — no cloud service dependency.
- **Analytics dashboard** — `components/analytics.py`: interactive Plotly charts (price distribution, avg rent by sector, neighbourhood drilldown, rooms breakdown, platform split, rent vs area scatter). Property type + rooms multiselect filters. `price_eur_normalized` column converts RON→EUR at 5.1 rate so RON listings participate in all price charts. Data pre-filtered to `is_available=1 AND property_type IS NOT NULL` at DB level.
- **districts.json** expanded to 120 neighbourhoods (was 87) — cross-referenced against live Supabase `district` values; all missing Bucharest neighbourhoods added to correct sectors.
- **Multi-dimension search filters** — rooms, area (min/max m²), property type (Apartament / Garsonieră / Casă / Vilă) filter controls added to the main search UI. `apply_filters` extended with `min_sqm`, `max_sqm`, `property_types` parameters; listings without those columns are always kept (no data-loss penalty).
- **NLP auto-fill** — if a filter field is left at its default (rooms="Any", all property types, sqm=0, price=0), `extract_filters` fills it from the vibe prompt automatically. Form always wins; NLP only acts on untouched fields. Extracted fields: `ROOM_COUNT`, `PROPERTY_TYPE`, `AREA_MIN`, `AREA_MAX`, `PRICE_MAX`. User notified via toast.

---

## Priority Stack (ordered — do top before bottom)

### P1 — Automated Crawler ✅ DONE

#### 1.1 Full Crawl Script ✅
- `crawler.py` with `--mode full|incremental` and `--platform` filter
- Covers all 6 sectors × all 3 platforms via `build_search_urls(full_sectors=...)`
- Paginates until empty page or `--max-pages` limit
- SQLite URL deduplication before scraping; `scraped_this_run` set prevents double-scraping within a run

#### 1.2 Incremental Crawl ✅
- `--mode incremental` early-exit: if ≥`--stop-threshold` (default 80%) of a page is already known → stop that search URL
- Typical run: 1–3 pages per search URL instead of 10+
- `_build_page_url()` uses `&page=N` for all platforms (fixes latent double-`?` bug in original `collect_links`)

#### 1.3 Scheduling ✅
- **Cloud (production):** Google Cloud Scheduler → Cloud Run Job (`crawler-job`)
  - `crawl-incremental`: daily at 02:00 UTC (`"0 2 * * *"`) — **confirmed working in production**
  - `crawl-full`: every Sunday at 03:00
- **Local (fallback):** `python crawler.py --mode incremental --proxy-file "Webshare 10 proxies.txt"` if you need to trigger a manual run

---

### P2 — Database Migration: SQLite → Supabase (Postgres + pgvector) ✅ DONE

**Why second:** SQLite can't handle concurrent writes. Once the crawler runs independently, it will collide with app reads/writes. This must happen before cloud deployment.

**Target: Supabase** — Postgres + pgvector built-in, generous free tier, REST API compatible with current Firestore fast-path pattern.

#### 2.1 Schema design ✅
- Single `listings` table replacing both SQLite and Firestore
- `first_seen_at`, `last_seen_at` columns for listing age tracking (M3.2)
- `image_urls`: native Postgres JSONB array (no more JSON-serialized strings)
- `embedding`: `vector(384)` column via pgvector (replaces ChromaDB `web_archive` text collection)
- Image embeddings stay in ChromaDB for now (512-dim CLIP, separate collection)
- Schema in `scripts/supabase_schema.sql`

#### 2.2 Migration ✅
- `scripts/normalize_listings.py` normalises all three platform schemas → canonical structure
  - Detects platform from URL for 4,340 rows with NULL `platform_id`
  - Parses `price_numeric` (FLOAT), `rooms` ('1'–'5+'), `area_sqm` (FLOAT)
  - Handles `€`/`²` encoding corruption from SQLite
- `db_utils.py` replaces `firebase_utils.py` — wraps Supabase client
- `extractor.py` and `home.py` import `save_to_firestore`/`query_listings_by_district` from `db_utils`
- `db_utils._clean_record` normalises raw scraped fields and strips non-canonical columns
- ~7,000 rows migrated from SQLite to Supabase

#### 2.3 pgvector for text search ✅
- ChromaDB `web_archive` collection **replaced** by `embedding vector(384)` column in Supabase
- `apply_ai_scores` text path: embed query → `db_utils.search_by_text_vibe()` → Supabase `match_listings` RPC
- New listings embedded at scrape time in `extractor.py` (SentenceTransformer, no Streamlit dependency)
- `scripts/backfill_embeddings.py` — one-time backfill for historical rows (`python scripts/backfill_embeddings.py`)
- OLX district extracted from listing title using hardcoded `districts.json` neighbourhood map

---

### P3 — Proxy Rotation ✅ DONE

#### 3.1 Proxy pool ✅
- **Current:** 10 Webshare datacenter proxies (`Webshare 10 proxies.txt`)
- Injected into `scrapers/http.py` (`set_proxy` / `get_proxy`) for curl_cffi (OLX)
- Injected into Playwright via `PROXY_URL` env var, read by both Storia + Imobiliare subprocess scripts
- `ProxyRotator` in `crawler.py`: one proxy per session, round-robin, persistent index in `.crawler_proxy_state.json`
- Health check at startup (via `api.ipify.org`) with automatic fallback to next proxy if dead
- Parses Webshare format (`host:port:user:pass`) automatically

#### 3.2 Rate limiting & jitter ✅
- All delays randomised: `time.sleep(random.uniform(...))` throughout crawler and extractor
- Sequential scraping (no concurrency) keeps per-IP request rate low

#### 3.3 Remaining / upgrade path
- Datacenter proxies may be detected by OLX at full-crawl scale — upgrade to residential (Smartproxy ~$75/mo) if ban rate increases
- Backoff on 429/503 not yet implemented — blocked requests currently dropped silently (retried next run via `-1` state)

---

### P4 — Cloud Deployment

**Why fourth:** Depends on P2 (cloud DB) and P3 (proxies). Without these, deploying to cloud just moves the local problems to a server.

#### 4.1 Crawler worker — Google Cloud Run Jobs + Cloud Scheduler ✅ DONE (confirmed in production)
- **Google Cloud Run Jobs**: container runs to completion, then exits — correct model for a batch crawler
  - `python:3.12-slim` base + `playwright install --with-deps chromium`
  - SentenceTransformer model pre-cached in Docker layer (no download on each run)
  - 4Gi memory (upgraded from 2Gi; Chromium + SentenceTransformer + page rendering headroom)
  - Region: `europe-west1` (Belgium)
  - Cost: ~$0/month for 8 crawls/day at current scraping volume
- **Cloud Scheduler**: two triggers live and confirmed active
  - `crawl-incremental`: `"0 2 * * *"` — incremental daily at 02:00 UTC
  - `crawl-full`: `"0 3 * * 0"` — full crawl every Sunday at 03:00
- Proxy credentials injected via Secret Manager (`proxy-list` secret → `ProxyRotator.from_env()`)
- Supabase key injected via Secret Manager (`supabase-key` secret)
- Deduplication: `_load_supabase_known()` pre-loads all known URLs from Supabase at startup (SQLite is empty in container)
- Reliability: `_upsert_batch` retries transient DNS/network errors with exponential backoff (1s, 2s) before row-by-row fallback
- Non-root `appuser` for container security; `HF_HOME` and `PLAYWRIGHT_BROWSERS_PATH` redirected to `/app/` so model cache is accessible to non-root user

#### 4.2 Embedder Cloud Run Job ✅ DONE (replaces Cloud Run Service, May 2026)
- **Cloud Run Job** (`embedder-job`, `europe-west1`, 4Gi, 2 vCPU, 1h task timeout)
- Entrypoint: `embedding-service/embed_job.py` — loads ST + CLIP, runs full text + image backfill, exits
- Models baked into Docker image at build time; `HF_HUB_OFFLINE=1` at runtime
- Build: `gcloud builds submit . --config embedding-service/cloudbuild.yaml` (project root context)
- Image: `europe-west1-docker.pkg.dev/<your-project>/repo-crawler/embedder`
- Triggered by crawler via Cloud Run Jobs v2 API (`_trigger_embedder_job()` in `crawler.py`) — fire-and-forget, runs async after each crawl
- Cost: cents/month (billed for execution time only) vs ~$30/month for the always-on Service

**Why the Service was replaced:**
`--min-instances 1` was required to avoid gVisor's 7-minute cold start (see notes below). At 4Gi + 2 vCPU always-on, idle cost reached $3+/day. As a Job, cold start time is irrelevant — the job runs to completion with no HTTP probe to satisfy.

**gVisor cold-start notes (kept for reference — relevant if ever running as a Service again):**

**gVisor cold-start problem and fix (documented for future reference):**

Cloud Run gen1 runs containers inside gVisor (a sandboxed kernel). gVisor restricts `pthread_create` and related syscalls in a way that causes PyTorch, sentence-transformers, and transformers to hang indefinitely — but **only when they perform their first thread-pool initialisation inside a background worker thread**. The hang goes away completely when the same import runs in the main Python thread.

*What was tried (in order), and why each failed:*
1. **`OMP_NUM_THREADS=1` env vars** — prevents OpenMP from spawning extra threads, but doesn't prevent the initial pthread setup inside torch/ST/transformers from hanging in worker threads
2. **Synchronous lifespan loading** — blocks the event loop; port 8080 never opens; TCP startup probe times out and Cloud Run kills the container
3. **background thread + `daemon=False`** — uvicorn starts immediately (TCP probe passes), but each `import` inside the thread hangs for 15+ minutes per library before eventually unblocking
4. **HTTP startup probe on `/health`** — correct architectural decision, but the probe path was mangled by PowerShell path expansion (`/health` → `D:/Git/health`); deployment failed after 90 s because `/health` was never checked; PowerShell workaround: set probe via YAML or use `gcloud run services replace`
5. **Pre-import torch at module level only** — `import torch` in main thread is fast (5 s); background thread's `import torch` is then instant. But `from sentence_transformers import SentenceTransformer` in the background thread hit the same gVisor hang next
6. **Pre-import all slow libraries at module level** — final fix: `import torch`, `from sentence_transformers import SentenceTransformer`, `from transformers import CLIPModel, CLIPProcessor` all run in the main Python thread before uvicorn starts. Background thread then only loads model weights (fast, no pthread setup). TCP probe passes ~25 s after container start; models ready ~7 min after (gVisor still stalls ~1–2 min between each model's weight-loading and the next init step)

*Additional bugs discovered and fixed during debugging:*
- **`HF_HUB_OFFLINE=1` placement**: must be set AFTER the `RUN python -c "...download models..."` step in Dockerfile. If set before, the build-time download fails silently. If set correctly, runtime never calls hf.co (prevents hub verification hang)
- **`CLIPModel.get_text_features()` return type**: returns `BaseModelOutputWithPooling` (not a tensor) in newer transformers versions — calling `.norm()` on it crashes. Fix: use `text_model(...)` → `text_projection(pooler_output)` → `F.normalize()` directly
- **Same issue for `get_image_features()`**: fixed to use `vision_model(pixel_values=...)` → `visual_projection(pooler_output)` → `F.normalize()`
- **Crawler infinite retry on 503**: the `break` in `except Exception` exited only the inner `for` batch-loop, not the outer `while True` — causing infinite retries on the same rows. Fixed with a `batch_failed` flag propagated to the outer loop
- **`SUPABASE_URL` missing from `crawler-job`**: only `SUPABASE_KEY` was wired as a secret; `SUPABASE_URL` was never added. Every crawler run silently failed all DB writes. Fixed by adding it as a plain env var (it's a URL, not a credential)

*Current limitation — 7-minute cold start:*
The service works correctly once warm. Cold starts take ~7 minutes because gVisor stalls ~1–2 min between model init steps even after the library hang is fixed. Two upgrade paths:
- **Switch to gen2 execution environment** (`--execution-environment gen2`): standard Linux kernel, no gVisor restrictions → cold start drops to ~30 s. Run: `gcloud run services update embedder --region europe-west1 --execution-environment gen2`
- **Keep one warm instance** (`--min-instances 1`): eliminates cold starts entirely, ~$8/month for 4Gi in europe-west1

#### 4.3 Post-crawl embedding backfill ✅ DONE
- **Text** (`run_text_backfill()` in `crawler.py`): inline after each crawl, uses the ST model baked into the crawler image. Queries Supabase for `embedding IS NULL`, upserts 384-dim vectors in batches of 64.
- **Image** (`embedding-service/embed_job.py` via `embedder-job`): triggered asynchronously by `_trigger_embedder_job()` at end of each crawl. Queries for `image_urls IS NOT NULL AND image_embedding IS NULL`, fetches cover photo, runs local CLIP inference, upserts 512-dim vectors. Auth: `google.auth.default()` with `cloud-platform` scope (metadata server in Cloud Run, service account key locally).
- Supabase schema: `image_embedding vector(512)` column + `match_listings_by_image` pgvector RPC (`scripts/supabase_schema.sql`)
- Image search path: Supabase `match_listings_by_image` RPC (migrated from local ChromaDB)

#### 4.4 Streamlit app hosting
- Streamlit Community Cloud (free, good enough for demo/early users)
- Or Google Cloud Run (always-on, scales to zero between sessions)
- Remove remaining local file path assumptions (`D:\temp\hub`)

#### 4.5 CLIP image server (GPU backfill)
- The embedder-job currently runs CLIP on CPU (Cloud Build uses E2 machine) — sufficient for incremental backfill of ~10–50 new listings/day
- For bulk re-embedding (e.g. schema change): run `gcloud run jobs execute embedder-job --wait` manually, or consider a one-off Colab run for large batches

**CDN URL expiry (important):** OLX and Storia serve photos from CDNs with short-lived tokens. Stored `image_urls` in Supabase go stale within hours to days. Because of this, `embedder-job` will never succeed on historical listings — it fetches 404s for every image, and the `seen_urls` guard breaks the loop after one pass (`image=0` is the expected result for a run over historical data). Only newly scraped listings (URLs fresh from that day's crawl) get image embeddings; this is by design. First confirmed clean run: `embedder-job-8snnl`, `text=0 image=0`, `exit(0)`.

**Infinite loop fix (deployed):** Before the `seen_urls` set was added, `_image_backfill` cycled forever — `get_listings_missing_image_embedding()` returned the same rows on every iteration (no embeddings were ever written), and the job ran until the 1-hour task timeout. Fix: track attempted listing URLs in a `set[str]` and break the outer loop when all rows in the current page have already been seen this run.

---

## P5 — Listing Deduplication

### Problem
The `url` PK prevents exact same-URL duplicates, but two distinct problems remain:
1. **Cross-platform duplicates**: the same apartment appears on OLX, Storia, and/or Imobiliare under different URLs — shown to the user multiple times and counted multiple times in analytics.
2. **Near-duplicate re-ingestion**: a re-crawl before the URL is marked known can result in a slightly-variant URL for the same listing (e.g. extra query param).

Impact: inflated listing counts and price averages in analytics; duplicated cards in search results.

### Planned implementation

#### 5.1 Canonical URL fingerprint (cheap, high-coverage)
- Add `content_hash` column to `listings`: MD5 of `(normalised_title, price_numeric, district, rooms)` — normalise by stripping diacritics, lowercase, trimming whitespace.
- On upsert, compute hash. If a row with the same hash already exists on a different platform, set `canonical_url` → the existing row's URL (prefer Storia/Imobiliare over OLX for richer data).
- Cost: one DB read per upsert (or a nightly dedup pass).

#### 5.2 Analytics dedup
- `fetch_analytics_data()` filters to `canonical_url IS NULL` (the row IS the canonical) before aggregating — eliminates inflated counts.

#### 5.3 UI dedup
- In `render_results`, group rows by `content_hash`; show one card, add a "📎 Also on OLX" footnote listing alternate platform links.

#### 5.4 Nightly dedup script
- `scripts/dedup_listings.py` — scans for rows sharing the same `content_hash`, elects a canonical, sets `canonical_url` on the others.
- Safe to run repeatedly; idempotent.

---

## Month 3 — User-Facing Intelligence Features

These were originally Month 2/3. Moved down because infrastructure (P1-P4) must land first for them to work at scale.

### 3.1 Image Search UI
- ✅ Template photo picker grid — already implemented
- [ ] Free photo upload: `st.file_uploader` → CLIP embed → visual search
- [ ] Auto room-type detection on upload (CLIP classifier, labels already in ChromaDB metadata)

### 3.2 Listing Age & History
- Track `first_seen_at` / `last_seen_at` (add columns in P2 schema — cheap)
- Detect relisting: same listing reappears after >7 days `is_available=0` → flag as "relisted"
- Display on card: "On market 34 days" or "⚠️ Relisted Mar 12"

### 3.3 Price Fairness Indicator ✅ DONE
```
"Priced 12% above average for 2-room apartments in Floreasca"
```
- `apply_price_fairness()` in `pipeline/utils.py`: paginates all EUR listings from Supabase, groups by `(district, rooms)`, computes avg price per bucket (min 5 comparables). Cached for 1 hour via `@st.cache_data`.
- Adds `price_fairness` column to df: `"+12% vs avg"` / `"-8% vs avg"` / `None` (suppressed within ±5% or <5 comparables)
- Rendered as green `📉` / red `📈` chip in listing cards in `results.py`

### 3.4 Price Drop Alerts
- User saves a search → receives alert when new matching listing appears or price drops
- Requires user accounts (email only for MVP)
- Crawler runs incremental diff → check saved searches → send via SendGrid free tier
- Depends on P2 (user accounts table in Supabase) and P1 (crawler generating the diff)

### 3.5 Reverse Search — "Find listings like this one"
- User pastes a listing URL → fetch its photos → embed → find visually similar listings
- Trivial to implement given current image infrastructure
- High perceived value: useful when a liked listing is unavailable or overpriced

---

## Month 4 — Monetization Foundation

### 4.1 User interaction logging
The app's long-term moat is proprietary interaction data. Log from day one:
- Search queries (text vibe + filters)
- Card clicks / listing views
- Template photo selections
- Session duration

Store in a `user_events` table in Supabase. Don't need to use it yet — just collect it.

### 4.2 Preference learning / swipe mode
```python
preference_vector = mean([embed(img) for img in liked_photos])
# Use as query vector alongside uploaded photo
```
- No extra ML — pure vector arithmetic
- Generates labeled interaction data for eventual CLIP fine-tuning on Romanian RE photos

### 4.3 Listing quality scoring
- Score photo quality 1-3: photo count + blur detection (Laplacian variance) + CLIP embedding spread
- Display as subtle badge on card
- Low-quality listings are often from non-serious landlords — useful signal for users

### 4.4 Multi-room query
- User uploads/selects photos per room type: "Kitchen like this" + "Bedroom like this"
- Two embeddings → per-room scores → averaged into one image score before fusion with text
- Natural extension of template photo picker

---

## Technical Debt (address during P1-P4 work)

| Item | When to fix |
|------|-------------|
| Stale ChromaDB entries (taken-down listings never deleted) | During P2 — add cleanup job keyed on `is_available` |
| `web_archive` has no filter metadata | Replaced entirely in P2.3 (pgvector) |
| `rooms` vs `rooms_num` column inconsistency | Fix during P2 schema design |
| Local file paths hardcoded (`D:\temp\hub`, etc.) | Fix during P4.2 |
| `ollama_parser.py` dead code | Delete during P4 cleanup |
| Storia backfill ~77% incomplete | Run `python scripts/backfill_image_urls.py --platform storia` — do before first full crawl |
| Embedding versioning (model name in ChromaDB metadata) | Before any model upgrade |
| No backoff on 429/503 in crawler | Add exponential retry in `_scrape_and_save` — low priority until ban rate increases |
| Local Task Scheduler (superseded) | Cloud Scheduler handles scheduling — local Task Scheduler no longer needed |
| `EMBED_SERVICE_URL` in `.env` | Set to empty string (service deleted). Remove entirely before Streamlit Community Cloud deploy. |
| `embedding-service/main.py` (FastAPI) | Kept in image for reference but unused — CMD is now `embed_job.py`. Safe to delete if image size becomes a concern. |
| Cross-platform duplicate listings | Analytics inflated; user sees same apartment multiple times — fix in P5 (dedup script + `canonical_url` column) |

---

## Feature Priority Summary

| Feature | Phase | Status | User Value | Complexity |
|---------|-------|--------|------------|------------|
| Imobiliare.ro scraper | Done | ✅ | High | Medium |
| 3-state availability | Done | ✅ | Foundation | Low |
| Template photo search | Done | ✅ | High | Medium |
| Template photo embeddings pre-computed | Done | ✅ | Performance | Low |
| Automated full crawl | P1 | ✅ Done | Critical | Medium |
| Incremental crawl (2h) | P1 | ✅ Done | Critical | Low |
| Availability check (Mon+Thu) | P1 | ✅ Done | Data quality | Low |
| Proxy rotation | P3 | ✅ Done | Required | Medium |
| Supabase migration | P2 | ✅ Done | Foundation | High |
| pgvector replaces ChromaDB text | P2 | ✅ Done | Foundation | Medium |
| Cloud crawler worker | P4 | ✅ Done (confirmed) | Required | Medium |
| Embedder Cloud Run Job (replaces Service) | P4 | ✅ Done | Cost reduction | Medium |
| Post-crawl embedding backfill | P4 | ✅ Done | Required | Medium |
| Supabase image embeddings (pgvector) | P4 | ✅ Done | Required | Medium |
| Availability check as dedicated job | P4 | ✅ Done | Ops hygiene | Low |
| Analytics dashboard | Done | ✅ Done | High | Medium |
| RON→EUR price normalisation | Done | ✅ Done | Data quality | Low |
| districts.json expanded (87→120) | Done | ✅ Done | Data quality | Low |
| OLX district backfill from URL slug | Done | ✅ Done | Data quality | Low |
| Imobiliare expired redirect detection | Done | ✅ Done | Data quality | Low |
| Multi-dimension search filters (rooms/sqm/type) | Done | ✅ Done | High | Low |
| NLP auto-fill for all filter fields incl. price | Done | ✅ Done | High | Low |
| Listing deduplication (cross-platform) | P5 | Not started | High | Medium |
| Cloud Streamlit hosting | P4 | Not started | Required | Low |
| Modal.com CLIP server (GPU) | P4 | Not started | Nice-to-have | Low |
| Free photo upload UI | M3 | Not started | High | Low |
| Listing age + relist detection | M3 | Not started | High | Low |
| Price fairness indicator | M3 | ✅ Done | Very High | Low |
| Price drop alerts | M3 | Not started | High | Medium |
| Reverse search | M3 | Not started | High | Low |
| User interaction logging | M4 | Not started | Strategic | Low |
| Swipe / preference learning | M4 | Not started | Medium | Low |
| Listing quality scoring | M4 | Not started | Medium | Low |
| Multi-room query | M4 | Not started | Medium | Low |


