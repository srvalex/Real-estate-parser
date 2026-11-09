"""
query_model.py
───────────────
Structured query model for a text-to-SQL agent: an LLM extracts a
`ListingQuery` from a user's natural-language prompt (via tool-use /
structured output), which then translates deterministically into
Supabase/PostgREST filters. LLM output never becomes a raw SQL or filter
string directly — every field it can set is typed and, for `extras`,
restricted to a fixed registry of known-good JSONB paths.

Why `extras` is restricted rather than free-form: the column's shape
varies wildly by platform (see scripts/inspect_extras.py, which samples the
live table). Confirmed there on 2026-08-27:

  - Storia: `extras` is the entire raw ad JSON. Most of it is noise or PII
    (owner/agency phone numbers, contact names, tracking ids) unrelated to
    the property, but it also contains a clean, flat `attributes.*`
    sub-object — that's what EXTRAS_REGISTRY below targets.
  - Imobiliare.ro: `extras` currently holds only GA4/consent tracking
    dataLayer fields (session_hash, visitor_id, ad_storage, ...) — zero
    property attributes, even though scrapers/imobiliare.py appears to
    build a purpose-built dict. Likely a scraper regression. Extras
    filters simply won't match Imobiliare.ro rows until that's fixed.
  - OLX: `extras` is always NULL. No extras-based filtering is possible
    for OLX listings; canonical columns only.

Letting an LLM construct arbitrary `extras->>x` paths against a column this
inconsistent would silently miss rows or leak platform-internal/PII fields
into query results. Instead, EXTRAS_REGISTRY is the single source of truth
for which semantic fields are queryable and where they live per platform;
adding a platform's path later (e.g. once Imobiliare.ro's scraper is fixed)
is a one-line registry edit, not a query-model change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


@dataclass(frozen=True)
class ExtrasField:
    """One filterable semantic field backed by a path into `extras` JSONB.

    platform_paths maps platform name -> tuple of JSON keys to walk from
    the `extras` column root. A field may only be registered for the
    platforms it's actually confirmed to exist on.
    """

    platform_paths: dict[str, tuple[str, ...]]
    value_type: Literal["string", "number", "array"]
    description: str
    known_values: tuple[str, ...] = ()  # documented examples, not enforced


EXTRAS_REGISTRY: dict[str, ExtrasField] = {
    "heating_type": ExtrasField(
        platform_paths={"Storia": ("attributes", "heating")},
        value_type="string",
        description="Heating type",
        known_values=("gas", "urban", "electric", "other"),
    ),
    "amenities": ExtrasField(
        platform_paths={"Storia": ("attributes", "extras_types")},
        value_type="array",
        description="Amenities present on the listing",
        known_values=(
            "lift", "terrace", "balcony", "air_conditioning",
            "basement", "separate_kitchen",
        ),
    ),
    "furnishing": ExtrasField(
        platform_paths={"Storia": ("attributes", "equipment_types")},
        value_type="array",
        description="Furnishing/appliances included",
        known_values=(
            "furniture", "oven", "stove", "fridge",
            "washing_machine", "tv", "dishwasher",
        ),
    ),
    "security_features": ExtrasField(
        platform_paths={"Storia": ("attributes", "security_types")},
        value_type="array",
        description="Security features present",
        known_values=("entryphone", "monitoring", "anti_burglary_door"),
    ),
    "construction_status": ExtrasField(
        platform_paths={"Storia": ("attributes", "construction_status")},
        value_type="string",
        description="Construction/handover status",
        known_values=("ready_to_use",),
    ),
    "building_type": ExtrasField(
        platform_paths={"Storia": ("attributes", "building_type")},
        value_type="string",
        description="Building type",
        known_values=("apartment", "house", "block"),
    ),
    "move_in_date": ExtrasField(
        platform_paths={"Storia": ("attributes", "free_from")},
        value_type="string",  # ISO date text, e.g. "2026-09-01" — sorts correctly as text
        description="Earliest move-in date",
    ),
    "listed_by": ExtrasField(
        platform_paths={"Storia": ("advertType",)},
        value_type="string",
        description="Whether the listing is from an agency or a private owner",
        known_values=("AGENCY", "PRIVATE"),
    ),
    "latitude": ExtrasField(
        platform_paths={"Storia": ("location", "coordinates", "latitude")},
        value_type="number",
        description="Listing latitude, for geo/radius queries",
    ),
    "longitude": ExtrasField(
        platform_paths={"Storia": ("location", "coordinates", "longitude")},
        value_type="number",
        description="Listing longitude, for geo/radius queries",
    ),
    # Confirmed on some records via tests/db/test_clean_record.py fixtures,
    # but absent from the live 40-row sample this registry was otherwise
    # built from — coverage is unverified and likely sparse.
    "deposit": ExtrasField(
        platform_paths={"Storia": ("deposit",)},
        value_type="string",
        description="Security deposit (e.g. '1 lună')",
    ),
    "windows_type": ExtrasField(
        platform_paths={"Storia": ("windows_type",)},
        value_type="string",
        description="Window type (e.g. 'PVC')",
    ),
}

_SCALAR_OPS = ("eq", "gte", "lte")
_ARRAY_OPS = ("contains",)

_PG_OP = {"eq": "eq", "gte": "gte", "lte": "lte", "contains": "cs"}


class ExtraFilter(BaseModel):
    key: Literal[tuple(EXTRAS_REGISTRY.keys())]  # type: ignore[valid-type]
    op: Literal["eq", "gte", "lte", "contains"]
    value: Union[str, float, int]

    @field_validator("op")
    @classmethod
    def _op_matches_field_type(cls, op, info):
        key = info.data.get("key")
        if key is None:
            return op
        allowed = _ARRAY_OPS if EXTRAS_REGISTRY[key].value_type == "array" else _SCALAR_OPS
        if op not in allowed:
            raise ValueError(
                f"op={op!r} is not valid for extras key {key!r} "
                f"(type={EXTRAS_REGISTRY[key].value_type}); allowed: {allowed}"
            )
        return op


class ListingQuery(BaseModel):
    """What the agent extracts from a user prompt. Canonical fields map
    directly onto real `listings` columns (scripts/supabase_schema.sql);
    `extras` filters are restricted to EXTRAS_REGISTRY keys above."""

    price_min: Optional[float] = None
    price_max: Optional[float] = None
    rooms: Optional[list[Literal["1", "2", "3", "4", "5+"]]] = None
    area_min: Optional[float] = None
    area_max: Optional[float] = None
    district: Optional[list[str]] = None
    property_type: Optional[list[Literal["Apartament", "Garsoniera", "Studio", "Casa/Vila"]]] = None
    year_built_min: Optional[int] = None
    floor_min: Optional[int] = None
    floor_max: Optional[int] = None
    is_available: Optional[bool] = True

    extras: list[ExtraFilter] = Field(default_factory=list)

    # Escape hatch for anything not worth modeling as a column — routed to
    # db_utils.search_by_text_vibe's embedding search, not to SQL filters.
    vibe_text: Optional[str] = None

    limit: int = Field(default=50, ge=1, le=200)


@dataclass(frozen=True)
class SimpleFilter:
    column: str
    op: str
    value: object


@dataclass(frozen=True)
class OrFilter:
    """Multiple conditions, any of which may match (used when a single
    extras key resolves to more than one platform path)."""

    conditions: tuple[SimpleFilter, ...]


@dataclass(frozen=True)
class FilterPlan:
    filters: tuple[SimpleFilter, ...]
    or_groups: tuple[OrFilter, ...]
    limit: int


def _json_path(path_parts: tuple[str, ...], as_text: bool) -> str:
    """Build a PostgREST JSON-path column expression rooted at `extras`."""
    *middle, last = path_parts
    expr = "extras"
    for part in middle:
        expr += f"->{part}"
    expr += ("->>" if as_text else "->") + last
    return expr


def _pg_quote(value: object) -> str:
    """Quote a value for embedding in a hand-built PostgREST `or=(...)`
    filter string. Always quoting is safe even when not strictly required,
    and prevents a value containing `,`, `.`, `(` or `)` from being parsed
    as PostgREST filter syntax instead of literal data."""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _translate_extra_filter(f: ExtraFilter) -> OrFilter:
    """Always returns an OrFilter, even for a single condition (one per
    registered platform path) — extras columns use JSON-path/cast syntax
    like `extras->x->>y::numeric`, and postgrest-py's `.filter()` mangles
    any column string containing `:` (it double-quotes the whole thing via
    sanitize_param, meant for literal column names, not path expressions).
    `.or_()` doesn't sanitize its filter string, so routing every extras
    condition through it — even a lone one — sidesteps that entirely."""
    spec = EXTRAS_REGISTRY[f.key]
    is_array = spec.value_type == "array"
    pg_op = _PG_OP[f.op]

    conditions = []
    for path_parts in spec.platform_paths.values():
        column = _json_path(path_parts, as_text=not is_array)
        if spec.value_type == "number" and not is_array:
            column += "::numeric"
        criteria = json.dumps([f.value]) if is_array else str(f.value)
        conditions.append(SimpleFilter(column, pg_op, criteria))

    return OrFilter(tuple(conditions))


def build_filter_plan(query: ListingQuery) -> FilterPlan:
    """Pure translation from a validated ListingQuery into primitive
    filter operations. No I/O — safe to unit test without a DB."""
    filters: list[SimpleFilter] = []

    if query.price_min is not None:
        filters.append(SimpleFilter("price_numeric", "gte", query.price_min))
    if query.price_max is not None:
        filters.append(SimpleFilter("price_numeric", "lte", query.price_max))
    if query.rooms:
        filters.append(SimpleFilter("rooms", "in", tuple(query.rooms)))
    if query.area_min is not None:
        filters.append(SimpleFilter("area_sqm", "gte", query.area_min))
    if query.area_max is not None:
        filters.append(SimpleFilter("area_sqm", "lte", query.area_max))
    if query.district:
        filters.append(SimpleFilter("district", "in", tuple(query.district)))
    if query.property_type:
        filters.append(SimpleFilter("property_type", "in", tuple(query.property_type)))
    if query.year_built_min is not None:
        filters.append(SimpleFilter("year_built", "gte", query.year_built_min))
    if query.floor_min is not None:
        filters.append(SimpleFilter("floor", "gte", query.floor_min))
    if query.floor_max is not None:
        filters.append(SimpleFilter("floor", "lte", query.floor_max))
    if query.is_available is not None:
        filters.append(SimpleFilter("is_available", "eq", 1 if query.is_available else 0))

    or_groups = [_translate_extra_filter(extra) for extra in query.extras]

    return FilterPlan(filters=tuple(filters), or_groups=tuple(or_groups), limit=query.limit)


def apply_filter_plan(builder, plan: FilterPlan):
    """Apply a FilterPlan onto a Supabase/PostgREST query builder (e.g.
    `client.table("listings").select("*")`). Returns the builder, unexecuted
    — call `.execute()` on the result. Duck-typed: `builder` just needs
    `.filter(column, op, criteria)`, `.in_(column, values)`, `.or_(str)` and
    `.limit(n)`, matching postgrest-py's SyncFilterRequestBuilder."""
    for f in plan.filters:
        if f.op == "in":
            builder = builder.in_(f.column, list(f.value))
        else:
            builder = builder.filter(f.column, f.op, str(f.value))
    for group in plan.or_groups:
        clause = ",".join(
            # "cs" (contains) criteria is already a JSON array literal and
            # must stay unquoted for PostgREST to parse it as JSON; every
            # other operator's criteria is a plain scalar and gets quoted
            # so embedded "," "." "(" ")" can't be read as filter syntax.
            f"{c.column}.{c.op}.{c.value if c.op == 'cs' else _pg_quote(c.value)}"
            for c in group.conditions
        )
        builder = builder.or_(clause)
    return builder.limit(plan.limit)


def execute_listing_query(query: ListingQuery, client=None) -> list[dict]:
    """Convenience wrapper: build, apply and run a ListingQuery against the
    real `listings` table via the anon (read-only) Supabase client."""
    from db_utils import get_anon_client

    client = client or get_anon_client()
    plan = build_filter_plan(query)
    builder = apply_filter_plan(client.table("listings").select("*"), plan)
    resp = builder.execute()
    return resp.data or []
