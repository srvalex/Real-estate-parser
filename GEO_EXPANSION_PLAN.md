# Geo Expansion Plan: Bucharest-only → Multi-City

> Companion to `Roadmap.md`, `MIGRATION_PLAN.md`, and `ENRICHMENT_PLAN.md` —
> this document is the forward plan for extending the app beyond Bucharest
> to the largest Romanian student cities, broadening the user pool. Update
> this file as decisions get made or phases complete.

## Why this exists

Every layer of the app currently assumes Bucharest, not as a default but as
a hardcoded fact:

- **Schema**: `listings.district` (`scripts/supabase_schema.sql`) holds a
  neighbourhood name with no `city` column at all. Every row today is a
  Bucharest neighbourhood, so `district` values happen to be unique — but
  many other Romanian cities have a neighbourhood literally named "Centru"
  (Cluj-Napoca, Iași, Timișoara, Sibiu, Brașov all do), which would silently
  collide the moment a second city's rows exist. `db_utils.query_listings_by_district`
  does a flat `.in_("district", chunk)` with no city scoping.
- **Scrapers**: `scrapers/olx.py`, `scrapers/storia.py`, `scrapers/imobiliare.py`
  all hardcode `/bucuresti/` in the URL path, *and* `build_search_urls` in
  each one encodes Bucharest's sector-1-through-6 administrative structure
  directly (`sector_num = int(district_name.split(" ")[1])`,
  `olx_id = (sector_num * 2) - 1`, etc.). Other Romanian cities don't have
  sectors — search goes straight from city to neighbourhood. This is a real
  refactor (decouple the sector layer as a Bucharest-specific case), not a
  string substitution.
- **Frontend/data**: `streamlit_interface/districts.json` (120 Bucharest
  neighbourhoods) and `mock_ui/lib/locations.ts` / `ZoneSelector.tsx` are
  flat, Bucharest-shaped.
- **The in-flight agent/API layer** (`MIGRATION_PLAN.md`): `query_model.py`'s
  `ListingQuery` and the planned `set_location_filter` tool have no `city`
  concept yet. Worth adding now, while that layer is still being designed,
  rather than retrofitting it after Phase 1 of that plan ships.

**Business motivation:** broaden the user pool beyond Bucharest by covering
Romania's largest student-population cities — a constant, renewing source of
rental demand.

## Decided (this session)

- **Pilot cities: Cluj-Napoca and Iași, together, in Phase 1** — not a
  single pilot. Doing both at once (rather than one-then-generalize) forces
  the scraper refactor to actually be city-generic instead of accidentally
  overfit to one city's neighbourhood shape, and gets two large markets live
  at once.
- **Schema first.** Add a `city` column to `listings` and backfill every
  existing row to `'Bucuresti'` before any second-city scraping begins —
  retrofitting `city` onto already-ambiguous `district` values after two
  cities' data is mixed together is much harder than doing it up front.
- **`districts.json` restructured to be keyed by city**:
  `{"Bucuresti": {"Sector 1": [...], ...}, "Cluj-Napoca": {"Centru": [...], ...}}`.
  Bucharest keeps its sector-grouping; other cities are a flat
  neighbourhood list under the city key (no sector layer to preserve).
- **Sector logic becomes the Bucharest-specific case**, not the default —
  `build_search_urls` needs a generic "city + areas" path that Bucharest's
  sector math plugs into, not the other way around.
- **No assuming platform URL schemes** — OLX/Storia/Imobiliare are national
  portals so coverage for these cities is near-certain, but the exact slug
  format (`cluj-napoca` vs `cluj`, whether Storia nests a county level, etc.)
  must be confirmed live against each site before scraper code is written.

## Open decisions (resolve before/during the phase that needs them)

| Decision | Blocks | Notes |
|---|---|---|
| Neighbourhood list sourcing per city | Phase 1 | Bucharest's 120-neighbourhood list was hand-curated and cross-referenced against live `district` values. For Cluj/Iași, likely best sourced from each platform's own location-filter facets (they already maintain a canonical neighbourhood list per city) rather than hand-curating from scratch. |
| Is `city` a required top-level filter, or optional (defaulting to "all cities")? | Phase 3 (frontend), Phase 5 of `MIGRATION_PLAN.md` (agent) | Affects both the API contract and whether a vibe-only query without a city needs to search everything or prompt for one. |
| Price-fairness baseline scoping | Phase 3 | `get_price_stats`/`apply_price_fairness` currently pools all rows into one set of (district, rooms) buckets. Once `district` names collide across cities, this must bucket by `(city, district, rooms)` — otherwise a Cluj "Centru" studio gets compared against a Bucharest "Centru" baseline. |
| Analytics dashboard city scoping | Phase 3 | `components/analytics.py`'s sector/neighbourhood drilldowns are Bucharest-sector-shaped; needs a city selector or a per-city view. |

## Phases

### Phase 0 — Data model

**Goal:** the schema and reference data can represent more than one city
before any second-city scraper code exists.

**Tasks:**
- [ ] Add `city TEXT` column to `listings` (`scripts/supabase_schema.sql`),
      indexed alongside `district` (likely a composite index on
      `(city, district)` given how `query_listings_by_district` filters).
- [ ] Backfill: `UPDATE listings SET city = 'Bucuresti' WHERE city IS NULL`
      — one-off, all existing rows are Bucharest.
- [ ] Restructure `streamlit_interface/districts.json` (and the `mock_ui`
      copy) to the per-city keyed shape described above; migrate Bucharest's
      existing 120-neighbourhood data in as the `"Bucuresti"` key unchanged.
- [ ] `db_utils.query_listings_by_district` gains a required `city: str`
      parameter (or a `city_district_pairs` shape, if a query ever needs to
      span cities) — no more implicit "district names are globally unique."
- [ ] Any other read path assuming Bucharest-only `district` values
      (`apply_filters`, `get_price_stats`, `nlp_filters.py`'s district
      matching) audited and updated to be city-aware.

**Tests:**
- Schema migration applies cleanly; backfill sets `city='Bucuresti'` on
  every pre-existing row and nothing else.
- `query_listings_by_district` scoped to `(city, district)` — a same-named
  district in two different cities returns only the requested city's rows
  (this is the actual regression this phase exists to prevent — write it as
  a literal two-city fixture test, not just single-city coverage).
- `districts.json` loader handles the new per-city shape; Bucharest data is
  byte-for-byte preserved under its city key.

**Exit criteria:** the database and reference data can hold two cities'
worth of listings with no name collisions, verified by test, with zero
behavior change yet for existing Bucharest users.

---

### Phase 1 — Scraper refactor + Cluj-Napoca & Iași

**Goal:** all three scrapers can target an arbitrary city, proven against
two real cities at once so the abstraction isn't accidentally
Bucharest-shaped underneath.

**Tasks:**
- [ ] Live-verify each platform's URL scheme for Cluj-Napoca and Iași
      (OLX, Storia, Imobiliare) — confirm slug format and whether any
      platform needs a county-level segment. Do this before writing the
      generalized `build_search_urls`, not after.
- [ ] Refactor `build_search_urls` in all three scrapers: extract a generic
      `city + areas` path; Bucharest's `full_sectors`/`partial_by_sector`
      sector math becomes conditional on `city == "Bucuresti"` rather than
      the only path that exists.
- [ ] Populate `districts.json` entries for `"Cluj-Napoca"` and `"Iasi"`
      (source per the Open Decisions row above).
- [ ] `extractor.py` / `_clean_record` (`db_utils.py`) write the correct
      `city` value on every saved row, sourced from which search URL
      produced the listing (not parsed/guessed from the listing page).
- [ ] `crawler.py`'s `run_full_crawl`/`run_incremental_crawl` iterate cities
      the same way they already iterate platforms — confirm the existing
      per-platform exception isolation (`BUGS.md` #9a) extends cleanly to
      a city dimension too (one city's failure shouldn't abort another
      city's crawl).

**Tests:**
- `build_search_urls` unit tests per platform: Bucharest behavior is
  byte-for-byte unchanged (regression guard), plus new cases for Cluj-Napoca
  and Iași producing the expected URLs for both full-city and
  specific-neighbourhood selections.
- `_clean_record`/extractor: saved rows carry the correct `city` for a
  non-Bucharest search URL.
- Crawler orchestration: a failure scraping one city doesn't stop another
  city's crawl (same shape as the existing per-platform isolation test in
  `tests/crawler/test_crawl_orchestration.py`).

**Exit criteria:** a full crawl run produces correctly `city`-tagged,
correctly `district`-scoped listings for Bucharest, Cluj-Napoca, and Iași,
with no cross-city data corruption — verified live against Supabase, not
just unit tests.

---

### Phase 2 — Remaining cities (sequenced alongside `Roadmap.md` P5 dedup)

**Goal:** roll out the rest of the target list using the now-generic
scraper path proven in Phase 1, **together with** cross-platform
deduplication (`Roadmap.md` P5, not yet built) rather than after it —
decided this session. Dedup value scales with how many listings-per-metro
exist across OLX/Storia/Imobiliare, so launching each new city without it
means that city's analytics (`get_price_stats`, the analytics dashboard)
are pre-inflated with cross-platform duplicates from day one.

**Tasks:**
- [ ] Timișoara, Brașov, Sibiu, Constanța, Oradea — same live-verify +
      `districts.json` entry + crawl as Phase 1, but no scraper code
      changes expected (that's the point of generalizing first).
- [ ] Land `Roadmap.md` P5 (`content_hash` fingerprint, `canonical_url`,
      analytics/UI dedup, `scripts/dedup_listings.py`) before or during this
      phase, not after. **Update to that plan**: the `content_hash` must
      include `city` in its input tuple
      (`(city, normalised_title, price_numeric, district, rooms)`), not just
      `(normalised_title, price_numeric, district, rooms)` — otherwise a
      coincidentally similar listing in two different cities could
      collide once `district` names are no longer globally unique
      (see Phase 0).
- [ ] Note on Constanța: coastal/tourist rental listings will skew its
      price-fairness baseline differently from other cities — expected,
      not a bug, but worth a callout if it looks anomalous later.
- [ ] Consider Craiova (University of Craiova) and Târgu Mureș (UMF, large
      medical school) as substitutes/additions to Oradea if student-density
      is the optimization target — Oradea's student population is
      meaningfully smaller than the rest of this list.

**Tests:** same shape as Phase 1's per-city coverage, extended per new city.

**Exit criteria:** all target cities crawling successfully on the regular
schedule, each with correct `city`/`district` tagging.

---

### Phase 3 — Frontend + cross-cutting city awareness

**Goal:** users can actually pick a city, and city-blind logic elsewhere in
the app (price fairness, analytics) stops silently pooling across cities.

**Tasks:**
- [ ] City selector in `mock_ui` (and Streamlit, if still live at this
      point) as the top-level facet before district — resolve the "required
      vs. optional/all-cities" open decision first.
- [ ] `apply_price_fairness`/`get_price_stats` bucket by
      `(city, district, rooms)`, not `(district, rooms)`.
- [ ] `components/analytics.py` dashboard: city selector or per-city view
      for the sector/neighbourhood drilldowns.
- [ ] `query_model.py`'s `ListingQuery` gains a `city` field; once
      `MIGRATION_PLAN.md` Phase 5's agent tools exist, `set_location_filter`
      takes `city` alongside `include`/`exclude` districts.

**Tests:**
- Price-fairness bucketing: same-named district in two cities gets two
  independent baselines, not one shared/blended one.
- `ListingQuery`/filter-building tests extended with a `city` dimension.

**Exit criteria:** feature-equivalent city-aware experience across search,
filters, and analytics — no remaining code path silently assumes
single-city data.

---

## Explicitly out of scope for this plan

Student-specific search features (near-campus distance search,
semester/lease-length filtering, shared-room/roommate listings,
furnished-only) are a natural follow-on once multi-city coverage exists,
but are a separate roadmap item — not scoped here. Distance-based "near
campus" search in particular needs lat/lon data this schema doesn't have
yet (a further gap worth flagging, not solving in this document).

## Related

- `Roadmap.md` — existing priority stack and Month 3/4 feature list this
  plan doesn't replace.
- `MIGRATION_PLAN.md` — the API/agent layer `city` needs to be threaded
  through once it exists.
- `ENRICHMENT_PLAN.md` — independent LLM enrichment work; no direct
  dependency, but both extend `query_model.py`'s `ListingQuery`/`EXTRAS_REGISTRY`.
