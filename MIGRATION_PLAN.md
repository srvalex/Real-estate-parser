# Migration Plan: Streamlit → React + API + Agent-Based Search

> Companion to `Roadmap.md` (which tracks the current Streamlit-era feature set) —
> this document is the forward plan for replacing the UI layer and evolving
> search from spaCy-regex NLP to an agent/tool-calling architecture. Update
> this file as decisions get made or phases complete; it's meant to be a
> living reference, not a one-time writeup.

## Why this exists

The current app (Streamlit UI directly querying Supabase) works, but doesn't
scale to a real frontend: Streamlit can't give the UX control a proper
e-commerce-style search experience needs, and the app currently holds a
single shared Supabase credential used by both the crawler and the
user-facing surface. Moving to a React frontend talking to a dedicated API
fixes both — and while rebuilding the search entry point anyway, we're also
replacing spaCy's regex/lemma filter extraction with an LLM tool-calling
agent, since most query intent maps cleanly onto structured filters and a
fixed hand-written pattern list doesn't generalize to new phrasings
(exclusions, compound conditions, code-switching).

## Principles carried over from this session (non-negotiable, apply to every phase)

1. **Real, executed unit tests for every change** — written using the
   project's `unittest` + `unittest.mock` convention, run against a real
   venv, and verified to *fail* against the pre-fix code before being
   trusted. Tests live under `tests/`, organized per-subsystem (see
   Phase 1 for the new folders this plan needs).
2. **The LLM agent may only select and parameterize from a fixed, validated
   tool set — never generate or execute SQL, never call arbitrary code.**
   Every tool argument is typed/enum-constrained and validated against known
   domains (e.g. district names checked against `districts.json`) before
   touching the database. This is the actual security boundary, not a nice-to-have.
3. **Secrets stay server-side, always.** The React frontend never holds a
   Supabase key of any kind (anon or service-role) or the LLM provider's API
   key — it only knows the API's base URL. The API is the only thing that
   ever talks to Supabase or the LLM provider.
4. **Filter state is tri-state, not boolean**: *unset* / *set* / *explicitly
   cleared*. Only *unset* fields are eligible for NLP/agent backfill — a
   field the user cleared must never be silently refilled on the next
   request.

## Decided architecture (settled this session)

- **Frontend:** React SPA (Vite-style build, bakes env vars at build time —
  matters for per-environment deploys, see Phase 4).
- **Backend:** a new HTTP API that becomes the sole holder of Supabase
  credentials, replacing Streamlit's direct DB access. *(Language/framework
  not yet confirmed — see Open Decisions.)*
- **Search is two independent stages, always in this order:**
  1. **Hard filters** (district include/exclude, price, rooms, sqm,
     property type) → resolved to a final filter set (form values +
     NLP/agent backfill for untouched fields only) → plain PostgREST
     `.eq()`/`.in_()` conditions, exactly like `query_listings_by_district`
     + `apply_filters` do today. Never raw SQL string interpolation.
  2. **Vibe ranking** (optional) → the *original full query text* is
     embedded (`embed_query`) and scored via `apply_ai_scores`/RRF, scoped
     to the candidate set stage 1 produced (`candidate_urls` — already
     built this session). This never affects which rows are *included*,
     only their order.
- **Negative keywords**, two flavors:
  - *Categorical* (district/neighbourhood, property type): set-subtraction
    against the known domain (`districts.json`) before building the
    `.in_()` filter — no new SQL operator, no new `db_utils.py` signature
    beyond adding an `exclude` list.
  - *Free-text* (title/description keyword exclusion): generalizes the
    existing `EXCLUSION_PATTERNS`/`apply_description_filters` mechanism in
    `nlp_filters.py` from "auto-inferred from a positive ask" to
    "explicitly settable," via the `exclude_keywords` tool.
- **Agent tool set** (replaces spaCy `extract_filters()` for structured
  intent; spaCy/regex retired once this lands):

  | Tool | Args | Backing implementation |
  |---|---|---|
  | `set_location_filter` | `include: list[str]`, `exclude: list[str] = []` | `query_listings_by_district` + set-subtraction |
  | `set_price_filter` | `max_price: int \| None` | `apply_filters` |
  | `set_rooms_filter` | `rooms: "1"\|"2"\|"3"\|"4"\|"5+"` | `apply_filters` |
  | `set_area_filter` | `min_sqm`, `max_sqm: int \| None` | `apply_filters` |
  | `set_property_type_filter` | `types: list[enum]` | `apply_filters` |
  | `exclude_keywords` | `phrases: list[str]` | generalized `apply_description_filters` |

- **Filter pane UX:** e-commerce style — shows the *resolved* active filter
  state as removable pills, no visual distinction between user-set and
  agent-inferred (the API response includes `applied_filters` for this;
  see Phase 1).

## Open decisions (blocking specific phases — resolve before starting them)

| Decision | Blocks | Notes from discussion |
|---|---|---|
| API language/framework | Phase 1 | FastAPI was suggested (lets `db_utils.py`/`pipeline/utils.py` become route handlers with minimal rewriting) — not yet confirmed. |
| LLM provider for the agent | Phase 5 | Determines tool-schema format (Claude tool use vs. OpenAI function calling) and where that API key lives (backend-only, same secret story as Supabase keys). |
| Agent runs on every search, or only when the vibe box is non-empty | Phase 5 | Cost/latency tradeoff — a tool-calling LLM call is a real network round trip, unlike the current free/instant local spaCy call. Not the old 30–45s Ollama problem, but not zero either. |
| Free-text negative keywords in v1, or categorical-only first | Phase 3 | Categorical exclusion is nearly free (already-existing filter machinery); free-text exclusion needs new query conditions. Can ship separately. |

---

## Phase 0 — Finish the security groundwork already in progress

**Goal:** the anon/service-role split done in `db_utils.py` this session is
code-complete but not yet *live* — this must land before any public-facing
API exists, or the new API inherits the same "one god-credential" problem
it's meant to fix.

**Tasks (yours — I can't do these, they're your live infra):**
- [ ] Run Section 8 of `scripts/supabase_schema.sql` (RLS policy) in the
      Supabase SQL editor.
- [ ] Run the updated `match_listings`/`match_listings_by_image` definitions
      (candidate_urls scoping) from the same file, if not already run.
- [ ] Run Section 9 of the same file (`crawl_run_logs`, `availability_check_logs`,
      `user_searches` — see Phase 0.5 below) — additive, safe to run
      alongside Section 8 in the same sitting.
- [ ] Add `SUPABASE_ANON_KEY` to wherever the app currently runs; confirm
      `get_anon_client()` picks it up (no more fallback-warning in logs).
- [ ] Add a pre-commit secret scanner (`gitleaks` or `trufflehog`) — cheap
      insurance, and worth having before a second codebase (the frontend
      repo) exists to also worry about.

**Exit criteria:** Streamlit app runs cleanly with `SUPABASE_ANON_KEY` set
and no service-role key anywhere in its process environment.

---

## Phase 0.5 — Observability tables ✅ done (code side)

**Goal:** stop relying on `print()` output evaporating into Cloud Run's log
stream for the crawler, and have the schema for search-request logging
ready before Phase 1 needs it — done ahead of the rest of this plan since
it's low-risk, additive, and useful independent of the migration.

**Done:**
- `crawl_run_logs`, `availability_check_logs`, `user_searches` tables +
  RLS lockdown (default-deny for `anon`, service-role only) — Section 9 of
  `scripts/supabase_schema.sql`.
- `db_utils.py`: `start_crawl_run_log`/`finish_crawl_run_log`,
  `start_availability_check_log`/`finish_availability_check_log`,
  `log_user_search` (all service-role, all fail-safe — a logging error
  never breaks the operation it's observing).
- Wired into `crawler.py`'s `run_full_crawl`, `run_incremental_crawl`, and
  `run_availability_check` — each starts a log row at entry and finishes
  it (with `status='failed'` and the error captured, then re-raised) even
  if the run itself crashes, so nothing is left stuck in `'running'` forever.
- Tests: `tests/db/test_observability_logging.py`,
  `tests/crawler/test_crawl_run_logging.py`,
  `tests/crawler/test_availability_check_logging.py`.

**Still open:**
- `log_user_search` has no caller yet — nothing to log until Phase 1's
  endpoint exists. Its `form_fields` shape (`{field: {"value", "source"}}`)
  is designed to directly support the tri-state filter tracking from
  Phase 5, so wire it in as part of Phase 1 rather than bolting it on later.
- Not built: per-search-URL granularity within a crawl run (pages scraped,
  new-vs-known ratio per sector/neighbourhood). `crawl_run_logs` is
  run-level only, by design — add a child table later only if run-level
  summaries turn out not to be enough for debugging a specific failure mode.

---

## Phase 1 — Extract the search pipeline into an API, hard filters only

**Goal:** a working HTTP endpoint that does exactly what `query_listings_by_district`
+ `apply_filters` do today — no vibe, no agent yet. This is the foundation
everything else builds on, and it's independently useful/testable before
any frontend or agent code exists.

**Tasks:**
1. Decide the framework (open decision above) and scaffold a new top-level
   `api/` directory.
2. **Relocate the Streamlit-coupled pipeline code.** `streamlit_interface/pipeline/utils.py`
   imports `streamlit` and uses `@st.cache_data`/`@st.cache_resource` for
   caching — neither exists outside a Streamlit runtime. Extract the
   Streamlit-agnostic logic (`apply_filters`, `apply_ai_scores`, `rrf_fuse`
   import, `apply_price_fairness`) into a shared module the API and (for
   now) Streamlit can both import, and replace the `@st.cache_*` decorators
   with something that works in both contexts (`functools.lru_cache` for
   process-local caching, or drop caching at this layer and cache at the
   HTTP response level instead).
3. Build `GET /listings/search` accepting: `districts`, `exclude_districts`,
   `max_price`, `rooms`, `min_sqm`, `max_sqm`, `property_types` — all
   genuinely optional (no sentinel defaults like Streamlit's `"Orice"`/`0`;
   absent means unset).
4. **Add pagination** (`page`, `page_size`) — `query_listings_by_district`
   currently returns everything unbounded, fine behind Streamlit, not fine
   for a public endpoint.
5. Response shape: `{ results: [...], applied_filters: {...}, total_count, page }`.
   `applied_filters` echoes back the resolved filter state for the frontend's
   filter pane.
6. CORS: locked to the frontend's actual origin(s), not `*`.
7. Confirm the endpoint uses `get_anon_client()` under the hood, not
   `get_client()` — same rule as every other Streamlit-facing read today.
8. Call `db_utils.log_user_search()` (already built, Phase 0.5) at the end
   of the request — `session_id`/`visitor_id` from the request (client-
   generated, anonymous, no PII), `form_fields` built with per-field
   `source` tags from the resolution logic in step 3, `returned_listings`
   from the response's results (consider capping to the current page
   rather than the full result set, to keep row size bounded — decide
   based on whether Phase 5's later analysis needs beyond-page-1 data).

**Tests** (new folder: `tests/api/`):
- Endpoint returns correct filtered rows for each filter param individually
  and combined (mock the DB layer, don't hit real Supabase).
- Omitted params behave as "no constraint," not as a zero/default value
  filtering something out.
- `exclude_districts` correctly removes names from the include-set before
  querying (this is also where Phase 3's categorical exclusion tests live
  once that lands).
- Pagination: correct slice, correct `total_count`, stable ordering across
  pages.
- CORS headers present and scoped correctly.

**Exit criteria:** the API alone, hit with `curl`, reproduces exactly what
the Streamlit form's hard filters produce today, with tests proving it —
no frontend needed to validate this phase.

---

## Phase 2 — React frontend, hard filters only

**Goal:** replace Streamlit's search form + results grid with the React
equivalent, talking only to Phase 1's endpoint. No vibe box yet.

**Tasks:**
- Search form (district picker, price/rooms/sqm/type) → calls
  `/listings/search` → renders results.
- E-commerce-style filter pane rendered from `applied_filters`, each value
  removable (re-issues the search with that param dropped).
- `.env.local` holds only `VITE_API_BASE_URL` — confirm nothing else sneaks
  in (this is the concrete check for the "frontend has no secrets" design goal).
- Decide hosting target now (affects Phase 4's env var / build pipeline
  setup) — Cloud Run Service fits the existing GCP footprint but isn't required.

**Tests:** frontend component/integration tests are up to whatever the
React tooling convention ends up being (out of scope for this Python-repo
test suite) — at minimum, confirm the app builds with only
`VITE_API_BASE_URL` set and nothing else, as a check against accidental
secret bundling.

**Exit criteria:** feature-equivalent to today's Streamlit hard-filter
search, running as two separate deployable pieces.

---

## Phase 3 — Vibe ranking + negative keywords (categorical)

**Goal:** bring back semantic ranking and add district-level exclusion,
both of which are mostly wiring existing, already-tested logic into the
new endpoint.

**Tasks:**
- Add `vibe: str | None` to the search endpoint. When present: run stage 2
  (embed + `apply_ai_scores`, scoped to stage 1's candidate set) after the
  hard filters, exactly as designed this session — never before, never
  unscoped.
- `exclude_districts` (categorical negative keywords) — likely already
  covered by Phase 1 if scoped in from the start; otherwise add here.
- Frontend: vibe text box, results re-sort (no filter change) when present.
- Decide whether to ship free-text `exclude_keywords` now or defer to
  Phase 5 (it's more natural once the agent exists to populate it, per the
  Open Decisions table).

**Tests** (`tests/api/`, extending Phase 1's suite):
- Vibe present → ranking applied, row set unchanged from hard-filter-only baseline.
- Vibe absent → no ranking call attempted at all (mirrors the existing
  `has_vibe`/`has_image` gating tests from `tests/ranking/`).
- `exclude_districts` end-to-end through the real endpoint (not just the
  unit-level set-subtraction test from Phase 1).

**Exit criteria:** feature parity with today's full Streamlit search
(filters + vibe ranking), still without the agent.

---

## Phase 4 — Production hardening

**Goal:** close the gaps that only matter once this is actually deployed
and public, not just running locally.

**Tasks:**
- GCP Secret Manager wiring for the new API service (same pattern as
  crawler-job/embedder-job already use) — no `.env` file inside any
  deployed container.
- Per-environment frontend builds (dev/staging/prod each need their own
  build if `VITE_API_BASE_URL` differs — can't swap env vars post-build
  for a static SPA).
- Rate limiting on the public search endpoint (no auth exists yet, so this
  is the only abuse control).
- Confirm no write/admin endpoints are reachable from the public router —
  crawler-only operations (`save_to_db`, `batch_update_availability`
  equivalents) either don't exist on this API at all, or sit behind
  separate auth if they ever need to.

**Exit criteria:** the API and frontend are both actually deployed and
reachable, with the same secret-hygiene bar as the existing crawler infra.

---

## Phase 5 — Agent tool-calling layer

**Goal:** replace spaCy's `extract_filters()` with the LLM tool-calling
agent for structured intent extraction, including exclusion phrasing
("dar nu X," "fără parter") that regex patterns don't generalize to.

**Tasks:**
- Resolve the two Open Decisions above (provider, run-every-search-or-not)
  before writing code here — they shape the tool schema and the
  request/latency budget.
- Implement the tool set from the "Decided architecture" table as
  validated, typed functions with tight descriptions (the descriptions
  *are* the "documentation" the model reasons against — write them with
  the same care as an external API's docs, not as an afterthought).
- Wire tri-state filter tracking (unset / set / explicitly-cleared) into
  the frontend and API contract — this is the piece that makes "remove a
  pill" actually stick instead of having the agent silently re-derive it
  next request.
- Free-text `exclude_keywords`, if deferred from Phase 3, lands here
  naturally as one more tool.
- Residual vibe text (or the full original query, per the design decided
  this session) still flows to `embed_query` for ranking, unchanged.
- Retire `nlp_filters.py`'s `extract_filters()` once the agent covers its
  ground — keep `apply_description_filters`'s pattern-matching *mechanism*
  (it's reused by `exclude_keywords`), just stop calling the spaCy
  extraction function.

**Tests** (new folder: `tests/agent/`):
- Each tool: correct backing-function call for valid args; rejects/ignores
  args outside the validated domain (e.g. an unknown district name) rather
  than passing them through to the DB.
- End-to-end: a handful of representative queries (including exclusion
  phrasing) against a mocked LLM response, asserting the right tool calls
  come out — don't test against a live LLM API in the unit suite; mock the
  provider call and test your own tool-dispatch/validation logic, same
  principle as not hitting live Storia in `tests/scrapers/`.
- Tri-state regression test: agent-inferred filter → user clears it →
  same vibe text resubmitted → filter stays cleared.

**Exit criteria:** the "Sector 6 but not Militari Residence" example from
this session works from natural language, end to end, with test coverage
proving the removal-doesn't-resurrect behavior specifically.

---

## Explicitly out of scope for this plan

Auth/user accounts, saved searches, price-drop alerts, monetization —
these already exist as future items in `Roadmap.md` (Month 3/4) and aren't
part of this migration. Worth revisiting once Phase 4 ships, since a real
API is a prerequisite for most of them anyway, but not part of this plan.
