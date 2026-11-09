# OLX enrichment validation set — labeling guide

The rules the 200 rows in `benchmarks/data/olx_validation_set.jsonl` were
labeled by. They exist so the labels are reproducible, disputes are
resolvable against a written rule rather than taste, and a model's
"mistake" can be checked against the rule before anyone tunes a prompt.

## What the dataset is

- 200 most-recently-scraped OLX listings (Cluj / Iași / Bucharest mix,
  2026-09-04 → 2026-09-05), pulled by
  `benchmarks/prepare_olx_validation_set.py`. OLX-only and recency-ordered
  on purpose: OLX is the platform with no native structured data
  (`ENRICHMENT_PLAN.md`), and recent rows reflect the current scraper
  (post the Phase 1 `_extract_params` fix).
- Each row carries `db` — the listing's canonical column values as stored
  today — alongside two hand-labeled targets:
  - `expected`: the v1 enrichment fields (`EnrichmentResult`).
  - `expected_canonical`: canonical `listings` columns as stated **by the
    text** (`CanonicalFill`), independent of what `db` holds.
- `expected_canonical` is deliberately not copied from `db`: it records
  what a model reading title+description *should* be able to say. Where
  the two disagree (see `olx_validation_set_report.md`'s `contradicts`
  column) it is usually OLX's fuzzy params bucket vs. an exact figure in
  the text — e.g. `floor` "10 si peste" vs. "10", `year_built` "Dupa 2000"
  vs. "2012" — not a labeling error.
- Labels are single-annotator (no second pass, no adjudication). Treat
  measured accuracy above ~95% on any field as inside the label noise.

## Rules used

**General.** A field is labeled only from what title+description state. No
inference from price, district, photos or platform. Silence → `"unknown"`
(enums) or `null` (canonical fields, `parking.*`).

**own_heating** (v2 — replaced v1's `heating_type` gas/central/electric/other)
- `yes`: an in-apartment heat or hot-water source — `centrala proprie` /
  `centrala termica proprie` / `centrala de apartament` / `CT proprie`, a
  named boiler brand, or a `boiler` for hot water. A stated boiler counts
  even when the heating itself is the block's: it is independent hot
  water, which is the part of an outage that actually hurts.
- `no`: heat supplied by the building or the city — `termoficare`,
  `incalzire centralizata`, `centrala de bloc`, or a plant serving the
  whole building ("centrala termica a vilei", "centrala care deserveste 6
  apartamente").
- `unknown`: not mentioned, or a heating *type* with no source
  ("incalzire in pardoseala" alone, `teracota` with no boiler). Radiator
  cost-allocators (`repartitoare`) alone stay `unknown` — they imply
  district heating, but that is an inference, not a statement.
- "nu dispune de centrala termica" is `no`: it states the flat has no own
  boiler, which is exactly what the field asks.

**parking_available** (v2 — replaced v1's `available` + street/private/garage `type`)
- `yes`: the listing provides a space — garage, underground spot, an
  assigned or included spot, a spot in the block's courtyard or lot.
  Still `yes` when it costs extra ("loc de parcare optional, 50 €/luna"):
  the space exists and is offered.
- `no`: the text denies a space ("nu are loc de parcare"), **or** the only
  parking mentioned is on the street or municipal — `parcare stradala`,
  "se parcheaza in jurul blocului in limita locurilor", `parcare ADP`,
  "abonament de la primarie". Street parking is not a service the listing
  provides, so counting it as available would return flats with no
  parking to someone filtering for it.
- `unknown`: parking is not mentioned, or the mention is too vague to be
  either ("disponibilitate loc de parcare la orice ora").

**pets_allowed**
- `no` for any stated restriction, including partial ones ("nu sunt
  acceptate animale de talie mare") — the field is coarse, and the
  false-positive cost of `yes` is higher than the false-negative cost.
- `yes` only for an explicit welcome ("pet friendly", "animalele de
  companie sunt acceptate").
- Complex amenities aimed at pets (a dog-walking area in the ansamblu, a
  vet clinic nearby) are `unknown`: they say nothing about the tenancy.
- In wanted-ads (someone looking for a place), "fara animale" describes
  the seeker, not the property → `unknown`.

**renovation_status**
- `renovated`: explicit `renovat` / `renovare` / `modernizat`, whole-unit.
  A partial-scope claim ("baia a fost recent renovata") is `unknown`, as
  are cosmetic-refresh words alone (`zugravit`, `reimprospatat`).
- `new_build`: `bloc nou` / `imobil nou` / `constructie noua` / an
  explicit "finalizat in <recent year>". "Prima inchiriere" alone is not
  new-build — plenty of old flats are first-time rentals.
- `needs_work`: explicit `de renovat` / `nefinisat` / `nemodernizat`.
- Building-level thermal rehab (`bloc reabilitat/anvelopat`) says nothing
  about the apartment → `unknown`.

**rooms** (Romanian convention: *camere* = living + bedrooms)
- Labeled from an explicit count ("2 camere", `garsoniera`/`studio` → `1`)
  or from a complete breakdown (living + N `dormitoare` → N+1).
- When title and description disagree, the more specific and internally
  consistent one wins (e.g. #141's title says 2 camere, its body describes
  a living plus 2 dormitoare → `3`).
- `null` for a room rented inside a shared flat, a dorm bed, and wanted-ads.
- "camere" in a window-glazing spec is never a room count (the bug already
  documented in `scripts/supabase_schema.sql`'s `autofill_rooms` comment).

**area_sqm / floor / total_floors / year_built**
These are labeled from the text, but a model's answer for them is passed
through `sanitize_canonical_fill` before scoring — `floor` must be digits
or one of Parter/Demisol/Mansarda/Subsol, `year_built` must be a 4-digit
year, `area_sqm` must be 5-1000 — because these are free TEXT columns that
structured output cannot constrain on its own.

- `area_sqm`: the *utila* figure when both utila and construita are given;
  terraces/balconies are excluded ("83 mp + 16 mp terasa" → 83).
- `floor` / `total_floors`: split from "et. 5/10". Non-numeric floors are
  kept as written (`Parter`, `Demisol`, `Mansarda`, `Subsol`); vague ones
  ("etaj intermediar", "etaj retras") are `null`, as is an ambiguous
  choice ("et 1/11 sau 7/11" → floor `null`, total_floors `11`).
- `year_built` is the construction year only. A renovation year, a
  thermal-rehab year, or "prima inchiriere 2026" is not a build year.

## Schema history

The enrichment labels were migrated from v1 to v2 on 2026-09-06, after the
first benchmark run: `heating_type` (gas/central/electric/other) became
`own_heating` (yes/no/unknown) and the nested parking object became a
single `parking_available`. The migration was mechanical
(gas->yes, central->no, a typed spot->yes, street->no, denial->no) except
for seven rows re-read individually: #2 and #127 (underfloor heating with
no stated source -> unknown), #11, #71 and #119 (a stated boiler -> yes),
#109 (dual electric + centralized -> yes), and #126 (vague parking
mention -> unknown). The v1 benchmark artifacts under `data/` were left
as they were; they are not comparable to v2 runs field-for-field.

## Edge cases kept on purpose

The sample is unfiltered, so it includes rows that are not straightforward
rental listings: wanted-ads from seekers (#59, #93, #146, #162),
roommate/room-share posts (#18, #168, #199), a student dorm bed (#3), a
storage-box rental (#117), an agency page dump scraped into the
description field (#73), and exact duplicate listings posted twice
(#83/#84, #88/#89, #95/#96, #111/#115, #122/#134, #136/#150, #137/#158,
#141/#160, #143/#163, #138/#156). All are labeled by the same rules — a
model that confidently invents fields for these is exactly what this set
is meant to catch.
