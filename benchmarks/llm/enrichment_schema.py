"""
benchmarks/llm/enrichment_schema.py
────────────────────────────────────
The v1 structured-output schema for offline description enrichment, per
ENRICHMENT_PLAN.md's "Decided (this session)" field scope. Same
Literal-constrained style as ListingQuery/ExtraFilter in query_model.py —
never free text, so a model's output either validates or it doesn't.

This is the schema the benchmark scores candidate models against; once a
model is chosen, scripts/llm_enrich_extras.py (ENRICHMENT_PLAN.md Phase 2)
should import EnrichmentResult from here rather than redefining it.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field


class EnrichmentResult(BaseModel):
    """v2 (2026-09-06). The v1 shape had a 4-value `heating_type` enum and a
    nested parking object with a street/private/garage type. Both were
    replaced with yes/no/unknown after the first benchmark run, for product
    reasons rather than modelling ones:

    - `own_heating` — what a renter actually needs to know is whether the
      flat is independent of the building's heat supply, not which fuel it
      burns. Block/district heating (`termoficare`, a boiler serving the
      whole building) is the default everywhere and leaves the tenant
      exposed to outages; an in-apartment `centrala proprie` removes that
      risk. A stated `boiler` (electric water heater) also counts as yes:
      it secures hot water independently, which is the part of the problem
      that hurts most during an outage.
    - `parking_available` — garage vs. assigned spot is a detail nobody
      filters on. Street parking is deliberately *not* "available": it is
      not something the listing provides, so counting it as parking would
      make the filter return flats with no parking at all.
    """

    own_heating: Literal["yes", "no", "unknown"] = "unknown"
    parking_available: Literal["yes", "no", "unknown"] = "unknown"
    pets_allowed: Literal["yes", "no", "unknown"] = "unknown"
    renovation_status: Literal["renovated", "needs_work", "new_build", "unknown"] = "unknown"


ENRICHMENT_SYSTEM_PROMPT = """You extract structured facts from a real estate listing's title and description. The listing may be in Romanian or English.

Rules:
- Only report a fact if the text states or strongly implies it. If the text is silent on a field, use "unknown".
- Never guess a value that isn't supported by the text.

own_heating — does the apartment control its own heating or hot water?
- "yes" if the text mentions an in-apartment heat source: "centrala proprie", "centrala termica proprie", "centrala de apartament", "CT proprie", a boiler brand (Viessmann, Ariston, Bosch, Immergas), or a "boiler" for hot water.
- "no" if heat comes from the building or the city: "termoficare", "incalzire centralizata", "centrala de bloc", or a centrala that serves the whole building/villa rather than the apartment ("centrala termica a imobilului", "centrala care deserveste N apartamente").
- IMPORTANT: Romanian "centrala proprie" means the apartment's OWN gas boiler. It is "yes", never "no" — do not read the word "centrala" as central/district heating. Only "termoficare"/"centralizata"/a shared building plant is "no".
- "unknown" if heating is not mentioned, or if the type is stated without a source (e.g. "incalzire in pardoseala" with no boiler mentioned).

parking_available — does the listing come with a parking space?
- "yes" if it provides a spot: garage, underground parking, an assigned/included spot, a spot in the building's courtyard or lot — including when it costs extra.
- "no" if it states there is no spot, or if the only parking mentioned is on the street or public/municipal ("parcare stradala", "se parcheaza in jurul blocului", "parcare ADP/cu abonament de la primarie", "nu are loc de parcare").
- "unknown" if parking is not mentioned at all.

pets_allowed
- "yes" if pets are explicitly welcomed ("pet friendly", "animalele sunt acceptate").
- "no" for any stated restriction, including a partial one ("fara animale", "nu se accepta animale de talie mare").
- "unknown" if not mentioned.

renovation_status
- "renovated" (renovat/renovare recenta, whole apartment), "needs_work" (de renovat/nefinisat/nemodernizat), "new_build" (bloc nou/imobil nou/constructie noua), or "unknown".
- A repainted apartment ("zugravit") or a thermally rehabilitated block ("bloc anvelopat/reabilitat") is NOT renovated — that is "unknown".

Respond with only the structured fields — no extra commentary."""


class CanonicalFill(BaseModel):
    """Canonical `listings` columns a description can fill in when the
    scraper's native params block didn't (ENRICHMENT_PLAN.md Phase 1 got
    OLX's params block to ~90% coverage, not 100% — and `total_floors` has
    no params-block source at all, so it is NULL on every OLX row).

    Types deliberately mirror the real column types in
    scripts/supabase_schema.sql rather than being "nicer": `rooms`,
    `floor`, `total_floors` and `year_built` are TEXT columns holding fuzzy
    scraper values ("Parter", "Dupa 2000"), and `rooms` uses the
    '1'..'5+' bucketing that db_utils._clean_record normalises to. Only
    `area_sqm` is numeric. A field is None when the text does not state it.
    """

    rooms: Optional[Literal["1", "2", "3", "4", "5+"]] = None
    area_sqm: Optional[float] = None
    floor: Optional[str] = None
    total_floors: Optional[str] = None
    year_built: Optional[str] = None


CANONICAL_FILL_SYSTEM_PROMPT = """You extract a real estate listing's physical characteristics from its title and description. The listing may be in Romanian or English.

Rules:
- Only report a value the text states. If the text is silent on a field, use null. Never infer or guess.
- rooms: one of "1", "2", "3", "4", "5+" (a garsoniera/studio is "1"). Ignore "camere" used for window glazing specs (e.g. "geam cu 5 camere") — that is not a room count.
- area_sqm: usable/built area in square metres as a number. If both utila and construita are given, use utila.
- floor: the floor number as digits ("3"), or exactly one of "Parter", "Demisol", "Mansarda", "Subsol". From "et. 5/10" take "5". Anything else — "etaj intermediar", "retras", "ultimul etaj" — is null, not free text.
- total_floors: the building's floor count as digits, e.g. from "et. 5/10" take "10".
- year_built: the construction year as a 4-digit number only, e.g. "2019". If the text only says the building is new ("bloc nou", "constructie noua") without giving a year, use null — "nou" is not a year. A renovation year or a first-rental year is not a construction year.

Respond with only the structured fields — no extra commentary."""


# `floor` and `year_built` are TEXT columns, so a structured-output schema
# validates any string a model puts there — the first benchmark run
# produced `year_built="bloc nou"` and `floor="prima închiriere"`. These
# guards are what a writer must run before anything reaches the DB;
# rejecting a bad value costs one NULL, while storing it silently corrupts
# a column every filter and the analytics tab read.
_FLOOR_WORDS = {"parter", "demisol", "mansarda", "mansardă", "subsol"}
_DIGITS = re.compile(r"^\d{1,3}$")
_YEAR = re.compile(r"^(1[89]\d{2}|20\d{2})$")


def _clean_floor(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if _DIGITS.match(text):
        return text
    return text if text.lower() in _FLOOR_WORDS else None


def _clean_year(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text if _YEAR.match(text) else None


def sanitize_canonical_fill(fill: CanonicalFill) -> CanonicalFill:
    """Drop values whose shape the column can't mean: a floor that is
    neither a number nor a named level, a year that is not a 4-digit year,
    a non-positive or absurd area. Returns a new CanonicalFill — the
    original is left alone so a caller can log what was discarded.
    """
    area = fill.area_sqm
    if area is not None and not (5 <= area <= 1000):
        area = None
    return CanonicalFill(
        rooms=fill.rooms,
        area_sqm=area,
        floor=_clean_floor(fill.floor),
        total_floors=_clean_floor(fill.total_floors),
        year_built=_clean_year(fill.year_built),
    )
