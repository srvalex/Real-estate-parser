"""
benchmarks/llm/scoring.py
────────────────────────────
Pure field-level accuracy scoring for both benchmark tasks. No I/O, no
model calls — safe to unit test directly against hand-built expected/actual
pydantic objects.
"""

from __future__ import annotations

from benchmarks.llm.enrichment_schema import CanonicalFill, EnrichmentResult
from query_model import ExtraFilter, ListingQuery

_FILTER_QUERY_LIST_FIELDS = {"rooms", "district", "property_type"}
_FILTER_QUERY_SKIP_FIELDS = {"extras", "limit"}
_FILTER_QUERY_PRESENCE_ONLY_FIELDS = {"vibe_text"}


def score_enrichment(expected: EnrichmentResult, actual: EnrichmentResult) -> dict[str, bool]:
    """Per-field match between an expected and actual EnrichmentResult.

    Every field is a flat yes/no/unknown-style enum since the v2 schema
    (see enrichment_schema.EnrichmentResult), so this is plain per-field
    equality — the v1 special case that skipped `parking.type` when
    parking was absent has no counterpart to skip any more.
    """
    return {
        field: getattr(expected, field) == getattr(actual, field)
        for field in EnrichmentResult.model_fields
    }


_CANONICAL_TEXT_FIELDS = ("floor", "total_floors", "year_built")
_AREA_TOLERANCE_SQM = 0.5


def _normalize_text(value):
    """Fold the cosmetic differences that make two identical answers look
    different: `listings.floor` / `year_built` are free-text columns, so
    "Parter" and "parter " are the same value, not a miss."""
    return value.strip().lower() if isinstance(value, str) else value


def score_canonical_fill(expected: CanonicalFill, actual: CanonicalFill) -> dict[str, bool]:
    """Per-field match between an expected and actual CanonicalFill.

    Text fields are compared case-insensitively after stripping (see
    _normalize_text). `area_sqm` is compared with a small tolerance —
    descriptions state areas like "63,3 mp" or "aproximativ 56 mp", and a
    float that differs in the last decimal is not a real extraction error;
    anything further apart than that is. None is only equal to None, so
    hallucinating a value where the text said nothing scores as a miss —
    which is the failure mode this whole dataset exists to catch.
    """
    scores: dict[str, bool] = {"rooms": expected.rooms == actual.rooms}
    for field in _CANONICAL_TEXT_FIELDS:
        scores[field] = _normalize_text(getattr(expected, field)) == _normalize_text(getattr(actual, field))

    exp_area, act_area = expected.area_sqm, actual.area_sqm
    if exp_area is None or act_area is None:
        scores["area_sqm"] = exp_area is act_area is None
    else:
        scores["area_sqm"] = abs(exp_area - act_area) <= _AREA_TOLERANCE_SQM
    return scores


def _extras_signature(extras: list[ExtraFilter]) -> list[tuple[str, str, str]]:
    """Order-independent signature for an extras list — key/op/value only,
    coercing value to str so int vs. float from a model doesn't spuriously
    mismatch."""
    return sorted((e.key, e.op, str(e.value)) for e in extras)


def score_filter_query(expected: ListingQuery, actual: ListingQuery) -> dict[str, bool]:
    """Per-field match between an expected and actual ListingQuery.

    List-valued canonical fields (rooms/district/property_type) are compared
    as sets (order shouldn't matter). `extras` is compared as an
    order-independent multiset of (key, op, value). `limit` is excluded —
    it's a query-execution default, not something a prompt meaningfully
    specifies in the common case. `vibe_text` is free text with no fixed
    phrasing — scored on presence (did the model correctly decide something
    belongs here) rather than exact string equality, since two semantically
    equivalent phrasings (e.g. "with parking" vs. "must have parking")
    would otherwise be scored as a mismatch.
    """
    scores: dict[str, bool] = {}
    for field in ListingQuery.model_fields:
        if field in _FILTER_QUERY_SKIP_FIELDS:
            continue
        exp_val = getattr(expected, field)
        act_val = getattr(actual, field)
        if field in _FILTER_QUERY_LIST_FIELDS:
            scores[field] = set(exp_val or []) == set(act_val or [])
        elif field in _FILTER_QUERY_PRESENCE_ONLY_FIELDS:
            scores[field] = (exp_val is None) == (act_val is None)
        else:
            scores[field] = exp_val == act_val

    scores["extras"] = _extras_signature(expected.extras) == _extras_signature(actual.extras)
    return scores


def aggregate_accuracy(
    all_field_scores: list[dict[str, bool]],
    secondary_fields: frozenset[str] = frozenset(),
) -> dict[str, float]:
    """Per-field accuracy rate across a sample set, plus an "overall" mean
    across every scored field-instance (fields that weren't scored for a
    given sample, e.g. parking.type when parking was absent, don't count
    toward or against that sample).

    `secondary_fields` are still measured and reported per-field, but are
    left out of "overall" — they are fields whose accuracy is worth
    knowing yet shouldn't decide which model gets picked. The one in use
    today is `parking.type`: for a renter, whether a listing has a parking
    spot at all is the filter that matters; whether it is labeled garage
    vs. private is a detail, and letting it drag the headline would rank
    models on the least product-relevant thing they do.
    """
    per_field: dict[str, list[bool]] = {}
    for scores in all_field_scores:
        for field, correct in scores.items():
            per_field.setdefault(field, []).append(correct)

    result = {field: sum(vals) / len(vals) for field, vals in per_field.items()}
    primary = [v for field, vals in per_field.items() if field not in secondary_fields for v in vals]
    result["overall"] = sum(primary) / len(primary) if primary else 0.0
    return result
