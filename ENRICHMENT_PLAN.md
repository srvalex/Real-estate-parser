# LLM Description Enrichment Plan

> Companion to `Roadmap.md` and `MIGRATION_PLAN.md` — this document is the
> forward plan for extracting structured listing characteristics (parking,
> heating, pets, condition) from free-text descriptions via LLM, closing the
> gap left by platforms with no native structured data (OLX) or broken/
> incomplete `extras` (Imobiliare.ro). Update as decisions get made or
> phases complete.

## Why this exists

- **OLX's `extras` column is always NULL** (confirmed via
  `scripts/inspect_extras.py` and documented in `query_model.py`) — it's a
  full-on scraper with no backing JSON API. But its listing pages do carry
  a small native params block (`Compartimentare`, `Suprafata utila`,
  `An constructie`, `Etaj`) that `scrapers/olx.py` currently discards
  entirely, plus a real free-text description with genuinely extractable
  detail (furnishing, amenities, parking, pets, move-in timing) that no
  amount of DOM scraping can get.
- **Imobiliare's `extras` is currently a scraper regression** — confirmed
  in the in-progress fix to `scrapers/imobiliare.py`: it now holds only
  GTM/consent tracking fields, zero property attributes, because this
  site's current template doesn't mark up characteristics via schema.org
  microdata the way the old (wrong) implementation assumed.
- **Storia's `extras` does have real structured attributes** (heating,
  amenities, furnishing, ...) via `attributes.*`, registered in
  `EXTRAS_REGISTRY` in `query_model.py` — but only for Storia.
- **Pet-friendly detection today is a bespoke keyword heuristic**, not a
  real filter: `streamlit_interface/pipeline/nlp_filters.py` (~lines 33-95)
  hand-lists Romanian/English phrases ("pet-friendly", "fara animale", ...)
  and maps a match to a `PET_FRIENDLY` token that gets appended as a
  literal `?q=pet-friendly`-style keyword onto the platform's own search
  URL — i.e. it depends on the platform's search index matching that exact
  phrase, not on inspecting the listing's actual description, doesn't work
  as a real filter over already-crawled data, and only covers platforms
  whose search accepts a free-text query param. Not worth maintaining a
  second bespoke path for this — fold it into the same LLM extraction
  pipeline instead, once coverage is validated.

## Decided (this session)

- **Storage:** extend the existing `extras` JSONB column with an `llm`
  sub-namespace (`extras.llm.*`), tagged with the extraction model
  version. No schema migration; fits the shape `EXTRAS_REGISTRY`
  (`query_model.py`) already expects, and keeps LLM-inferred data
  provenance-separated from scraper-confirmed data (this project already
  has one silent-field-handling bug class — `_clean_record` dropping
  uncanonical columns, see `BUGS.md` — a second one shouldn't be added by
  conflating "the scraper read this" with "the model guessed this").
- **v1 field scope**, in priority order (small fixed set, not open-ended
  tagging — easier to validate and expose as real filters):
  1. **`heating_type`** — gas / central / electric / other. Extends the
     existing Storia-only registry key to OLX + Imobiliare; Storia keeps
     using its real `attributes.heating` value — LLM only fills in where
     no native value exists.
  2. **`parking`** — available (bool) + type (street / private / garage)
     when stated.
  3. **`pets_allowed`** — yes / no / unknown. Replaces the `nlp_filters.py`
     keyword/search-URL heuristic once coverage is validated.
  4. **`renovation_status`** — renovated / needs work / new-build /
     unknown.
- Furnishing status and utilities-included were discussed and deferred out
  of v1 — ship the smallest useful set first, expand once the eval loop
  (Phase 3) proves the pipeline out.
- Extraction runs **offline, per listing**, over `title + description`
  (covering both RO/EN variants where a listing has both, as the example
  OLX listing does) — never at query time.

## Phases

### Phase 1 — Free DOM wins (no LLM)
- [x] **OLX: scrape the native params block** (`Compartimentare`,
      `Suprafata utila`, `An constructie`, `Etaj`) — done in
      `scrapers/olx.py` (`_extract_params`, `_PARAM_LABELS`). Maps onto the
      raw field names `_clean_record` (`db_utils.py`) already folds:
      `m` → `area_sqm`, `floor_no` → `floor`, `build_year` → `year_built`
      (both TEXT columns, fuzzy values like `"Parter"`/`"Dupa 2000"` stored
      as-is); `compartimentare` has no canonical column and auto-folds into
      `extras`. Tests: `tests/scrapers/olx/test_olx_params.py` (9 cases,
      verified fail pre-fix/pass post-fix).
      **Live-verified 2026-08-29** against the last 100 scraped OLX
      listings (`scripts/olx_params_coverage_check.py`, live re-fetch, no
      writes): 95/100 parsed successfully (5 legitimately expired, 0
      blocked). Of those 95 — `floor_no` 98.9%, `build_year` 92.6%,
      `compartimentare` 90.5%, `m` 88.4%. This closes the "OLX extras is
      always NULL" gap for these four fields and, notably, gives OLX
      listings real `area_sqm`/`floor`/`year_built` for the first time —
      `scrapers/olx.py` never set those canonical fields at all before this
      change, so every OLX row had them NULL regardless of the `extras`
      question. Full report: `scripts/olx_params_coverage_report.json`.
- [ ] Finish the in-progress Imobiliare DOM scrape for
      "Detalii apartament"/"Utilități" (flagged not-yet-implemented in the
      current uncommitted diff to `scrapers/imobiliare.py`).
- [ ] Re-run `scripts/inspect_extras.py` after both land to confirm the
      actual coverage change before starting Phase 2.

### Phase 2 — LLM extraction schema + prototype
- [x] Pydantic schema for the 4 v1 fields, same style as
      `ListingQuery`/`ExtraFilter` in `query_model.py` — literal/enum
      constrained, never free text: `EnrichmentResult` in
      `benchmarks/llm/enrichment_schema.py`, alongside `CanonicalFill` for
      the canonical columns a description can also fill. Both are the
      schemas the Phase 3 validation set is labeled against, so
      `scripts/llm_enrich_extras.py` should import them rather than
      redefine either.
- [ ] Prototype script (e.g. `scripts/llm_enrich_extras.py`), same shape as
      `scripts/backfill_embeddings.py`: reads `title` + `description`,
      calls the LLM with structured/tool-calling output, writes
      `extras.llm.*` + a model-version tag.
- [ ] Dry-run on a small sample (~50 listings across all 3 platforms,
      weighted toward OLX since it has zero structured data today) —
      report-only, no writes.

### Phase 3 — Validate, then land
- [x] **Validation set built** — `benchmarks/data/olx_validation_set.jsonl`:
      the 200 most recently scraped OLX listings (2026-09-04 → 09-05),
      pulled by `benchmarks/prepare_olx_validation_set.py` and hand-labeled
      against both the v1 enrichment schema and a new `CanonicalFill`
      schema (`rooms`/`area_sqm`/`floor`/`total_floors`/`year_built` as
      stated by the text). Labeling rules are written down in
      `benchmarks/LABELING_GUIDE.md`; label distribution and canonical
      coverage in `benchmarks/data/olx_validation_set_report.md`
      (`benchmarks/summarize_olx_validation_set.py`). Single-annotator, no
      adjudication pass — treat >~95% measured accuracy on a field as
      inside the label noise.
      Two numbers that shape the rest of this plan:
      - **The v1 enrichment fields are sparse in OLX free text.** Silent on
        heating 59%, parking 68%, pets 80%, renovation 69%. The fields are
        real where present (70/200 state gas heating, 58 state parking,
        41 state a pet rule) but a "coverage" claim for these filters has
        to be stated against that ceiling, not against 200.
      - **`total_floors` is the biggest single win and is invisible today**
        — NULL on all 200 rows (no params-block source at all) and stated
        in the text on 45. `rooms` fills 35 of its 49 blanks. `area_sqm`,
        `floor` and `year_built` are already ~90% covered by Phase 1, so
        text extraction adds almost nothing there (2, 4 and 2 rows).
- [x] **Local-model benchmark run against the 200-row set** (2026-09-05,
      `benchmarks/run_enrichment_benchmark.py`, temperature 0, Ollama
      structured output). 800 calls; both models returned schema-valid
      JSON on every one — 0/200 errors each, on both tasks.

      | | qwen3:14b | phi4:14b |
      |---|---|---|
      | enrichment (excl. `parking.type`) | **92.0%** | 92.1% |
      | canonical fill | **96.0%** | 95.5% |
      | median latency | 8.05s / 7.52s | 9.11s / 7.12s |

      Per-listing paired comparison: enrichment 164 ties / 18 wins each;
      canonical 173 ties / qwen3 16 : phi4 11. **The two models are not
      meaningfully separated by this dataset** — pick on operational
      grounds (qwen3 has a hosted-equivalent price mapping and won the
      canonical task; phi4 has none listed, see `llm/cost_estimates.py`),
      and don't read the 0.1pp enrichment gap as a result.
      `parking.type` is excluded from the headline per the product call
      that having a spot matters and its type doesn't — it is still
      measured (qwen3 60.3%, phi4 51.7%) via `aggregate_accuracy`'s
      `secondary_fields`.

      Two findings worth more than the model choice:
      - **The biggest single error class is a prompt problem, not a model
        one.** `gas` mislabeled as `central` accounts for 26 of qwen3's 38
        heating misses and 16 of phi4's 32 — both read Romanian
        "centrala proprie" (an in-apartment gas boiler) as "central".
        Fixing that wording is worth ~13pp of heating accuracy on qwen3
        before any model change is worth discussing.
      - **Hallucination lands in the free-text canonical columns**, which
        the schema cannot constrain: models filled `year_built` with
        "bloc nou"/"nou"/"nouă" and `floor` with "retras", "un nivel",
        "prima închiriere". Any writer for these columns needs a
        value-shape guard (a year regex, a floor allowlist) — the schema
        alone will not stop junk from reaching the DB.
- [x] **Schema v2 + prompt fix, re-benchmarked** (2026-09-06). Both
      findings above were acted on and the full 800-call run repeated.
      - `heating_type` (gas/central/electric/other) -> **`own_heating`**
        (yes/no/unknown): what matters to a renter is independence from
        the building's heat supply, not the fuel. A stated `boiler` counts
        as yes — independent hot water is the part of an outage that
        hurts. The prompt gained an explicit contrast line that
        "centrala proprie" is the apartment's own boiler, never district
        heating.
      - `parking` (available + street/private/garage type) ->
        **`parking_available`** (yes/no/unknown), with street/municipal
        parking counted as **no**: it is not a space the listing provides.
      - `sanitize_canonical_fill()` guards the free-text canonical
        columns (floor must be digits or Parter/Demisol/Mansarda/Subsol,
        year_built a 4-digit year, area 5-1000 m2). The canonical task now
        scores the guarded value — what would reach the DB — and keeps the
        raw model answer in the predictions.

      | | v1 qwen3 / phi4 | v2 qwen3 / phi4 |
      |---|---|---|
      | enrichment overall | 92.0% / 92.1% | **95.9% / 95.9%** |
      | heating | 81.0% / 83.0% | **93.5% / 93.5%** |
      | renovation | 90.5% / 89.0% | 93.5% / 94.5% |
      | canonical overall | 96.0% / 95.5% | 95.9% / 95.8% |

      The heating jump (+12.5pp on qwen3) came entirely from prompt
      wording — same models, same listings, same temperature. That is
      three times the largest gap ever measured between the two models,
      and the case for spending review effort on prompts and label
      definitions before model selection.
      The guard fired on only 5 of 400 canonical calls (3 junk floors, 2
      junk years) — the prompt fix removed most of the junk at the source,
      and the guard caught what was left. Keep it anyway: it is the only
      thing standing between a free-text column and a bad write.
      Models remain inseparable: 176/200 and 177/200 listings scored
      identically, with the remaining rows split 12-12 and 12-11.
- [ ] Manual accuracy spot-check against the dry-run sample — this is the
      same "no offline eval of output quality" gap already open in the
      ranking backlog, just applied to a new subsystem: don't tune or trust
      this without measuring it first.
- [ ] Once accuracy is acceptable: register the 4 v1 keys in
      `EXTRAS_REGISTRY`, resolving Storia's `heating_type` from its native
      path first and falling back to `extras.llm.heating_type` only when
      the native value is absent.
- [ ] Historical backfill across the existing ~7-10k rows — batched,
      cheap model, resumable (reuse the same resumable-batch pattern
      already used by `scripts/backfill_embeddings.py`, not a fresh
      design).
- [ ] Retire the `PET_FRIENDLY` branch of `nlp_filters.py`'s keyword system
      once `pets_allowed` coverage is validated — replace the
      query-string-append behavior with a real
      `extras.llm.pets_allowed = "yes"` filter.

### Phase 4 (extended)
- [ ] Expand field set (furnishing, utilities-included, others) once the
      Phase 3 eval loop is proven out — same schema-then-validate
      discipline, not ad hoc additions.
- [ ] Reuse the same extraction schema for the planned single-URL "reverse
      search" analyze feature (`Roadmap.md` M3.5) — one-off LLM call
      instead of a batch job.
- [ ] Cross-check LLM-claimed `renovation_status`/amenities against CLIP
      image embeddings for a quality/trust signal — extends the
      already-planned M4.3 listing quality scoring in `Roadmap.md`.
- [ ] If volume/cost justifies it, distill a small local classifier for the
      highest-value fields once the schema has stabilized, to cut
      recurring per-listing LLM spend.

## Open decisions (not yet resolved)

| Decision | Notes |
|---|---|
| LLM provider/model for extraction | Cost-sensitive, offline, high volume — likely a cheap model (e.g. Claude Haiku) rather than whatever ends up backing the interactive `query_model.py` agent (Phase 5 of `MIGRATION_PLAN.md`), which is lower-volume and latency-sensitive. **Narrowed 2026-09-05:** local 14B models are accurate enough to be a real option (92% / 96% on the two tasks, zero schema failures), and qwen3:14b vs phi4:14b is a coin flip on this dataset — so the decision is now local-vs-hosted on throughput and ops, not on quality. At ~8s/listing a full backfill of ~7-10k rows is ~20 hours of single-stream local inference. |
| Exact enum values per field | e.g. does `parking` need an "included vs. extra cost" distinction? Needs a look at real description phrasing across a broader sample before locking the schema in Phase 2. |
| New listings only vs. full historical backfill in v1 | Backfill cost scales with ~7-10k existing rows; may want to ship new-listings-only first (cheap, ongoing) and backfill separately once real per-listing cost is known from Phase 2's dry run. |

## Related

- `query_model.py` — `EXTRAS_REGISTRY` / `ListingQuery` / `ExtraFilter`,
  the existing constrained-field system this plan extends rather than
  replaces.
- `MIGRATION_PLAN.md` — the interactive text-to-SQL agent this enrichment
  work is independent of, but will eventually expose fields to.
- `BUGS.md` — silent-field-drop precedent (`_clean_record`) motivating the
  `extras.llm.*` provenance separation above.
