"""
api/main.py
─────────────────
GET /listings/search — the search pipeline extracted from Streamlit
(streamlit_interface/components/home.py) into a plain HTTP endpoint, per
MIGRATION_PLAN.md Phase 1 (hard filters) + Phase 3 (vibe ranking), combined
in one pass. Hard filters only, from explicit request params — no
spaCy/agent NLP backfill of unset fields yet (Phase 5's job).

POST /events — minimal alpha traffic tracking (page views, listing
clicks), writing to user_events (scripts/supabase_schema.sql section 9d).
The frontend never holds a Supabase key, so this is the only way it can
record an event — same rule as every other write path
(MIGRATION_PLAN.md principle #3).

Uses get_anon_client() throughout (via db_utils), never get_client() —
same rule as every Streamlit-facing read today. log_user_search and
log_user_event are the only exceptions, by design: they're backend-only
writes to observability tables, not user-facing reads.
"""
import ast
import os
import uuid
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import db_utils
import pipeline_core
from api.locations import sector_for
from api.schemas import EventIn, EventOut, SearchResponse, TemplatePhotoOut
from api.template_photos import get_combined_embedding, list_template_photos
from embedding import embed_query

app = FastAPI(title="Real Estate Search API")

_allowed_origins = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:3002"
    ).split(",")
    if o.strip()
]
# `next dev` bumps to the next free port (3001, 3002, ...) whenever 3000 is
# already taken — e.g. this API's own dev server left running from an
# earlier session alongside a separately-started one. Covering a few
# adjacent ports here means CORS doesn't silently break search just because
# two frontend instances happened to be up at once; a fetch blocked by CORS
# surfaces in the browser as a bare "Failed to fetch" with nothing else
# logged, which is easy to mistake for the API being down entirely.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _split_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _clean(value):
    """NaN/NaT -> None; everything else (including list/dict JSONB columns
    like features/image_urls, which pd.isna() can't take a scalar truth
    value of) passes through unchanged. pandas leaves gaps as NaN even in
    object columns once a Series has been through any groupby/merge-style
    op — not JSON serialisable as-is."""
    if value is None or isinstance(value, (list, dict)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _parse_list_field(value) -> list:
    """features (and, defensively, image_urls) don't consistently come back
    as a real JSON array from Supabase — some rows hold a Python
    repr()-style string ("['agency', 'balcony', ...]") instead of a native
    list, confirmed live 2026-08-27. Never let one malformed row 500 the
    whole response: fall back to an empty list rather than raising."""
    value = _clean(value)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, SyntaxError):
            return []
    return []


@app.get("/listings/search", response_model=SearchResponse)
def search_listings(
    city: str = Query(..., description="e.g. Bucuresti, Cluj-Napoca, Iasi — see api/data/cities.json"),
    districts: Optional[str] = Query(
        None, description="Comma-separated neighbourhood names (required unless all_districts=true)"
    ),
    all_districts: bool = Query(
        False, description="Search every listing in `city`, ignoring `districts`/`nearby_districts`"
    ),
    nearby_districts: Optional[str] = Query(None, description="Comma-separated proximity-expanded extra zones"),
    max_price: Optional[float] = Query(None, ge=0),
    rooms: Optional[str] = Query(None),
    min_sqm: Optional[float] = Query(None, ge=0),
    max_sqm: Optional[float] = Query(None, ge=0),
    property_types: Optional[str] = Query(None, description="Comma-separated"),
    vibe: Optional[str] = Query(None),
    template_photos: Optional[str] = Query(
        None, description="Comma-separated template photo ids (template_1..template_4) for visual-similarity search"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    core_zones = _split_csv(districts)
    nearby_zones = _split_csv(nearby_districts)
    if not all_districts and not core_zones:
        raise HTTPException(
            status_code=422, detail="districts must be a non-empty comma-separated list, or all_districts=true"
        )

    property_type_list = _split_csv(property_types)
    template_photo_ids = _split_csv(template_photos)
    image_embedding = get_combined_embedding(template_photo_ids) if template_photo_ids else None
    nearby_set = set(nearby_zones)
    # dedup while keeping a stable order; nearby zones only ever add rows,
    # never narrow the core selection
    all_zones = list(dict.fromkeys(core_zones + nearby_zones))

    applied_filters: dict[str, dict] = {"city": {"value": city, "source": "user"}}
    if all_districts:
        applied_filters["all_districts"] = {"value": True, "source": "user"}
    else:
        applied_filters["districts"] = {"value": core_zones, "source": "user"}
    if nearby_zones:
        applied_filters["nearby_districts"] = {"value": nearby_zones, "source": "user"}
    if max_price:
        applied_filters["max_price"] = {"value": max_price, "source": "user"}
    if rooms:
        applied_filters["rooms"] = {"value": rooms, "source": "user"}
    if min_sqm:
        applied_filters["min_sqm"] = {"value": min_sqm, "source": "user"}
    if max_sqm:
        applied_filters["max_sqm"] = {"value": max_sqm, "source": "user"}
    if property_type_list:
        applied_filters["property_types"] = {"value": property_type_list, "source": "user"}
    if vibe:
        applied_filters["vibe"] = {"value": vibe, "source": "user"}
    if template_photo_ids:
        applied_filters["template_photos"] = {"value": template_photo_ids, "source": "user"}

    embedding_sorted = False
    embed_error = None
    needs_ranking = bool((vibe and vibe.strip()) or image_embedding)

    if all_districts and not needs_ranking:
        # No ranking requested, so there's no need to pull the whole city
        # into memory just to hand back one page of it — every hard
        # filter is pushed into the SQL query itself and the DB paginates
        # directly (query_listings_by_city_paginated), instead of the
        # fetch-everything-then-filter-in-Python approach below, which
        # measured ~34s end-to-end for a ~9000-row city.
        rows, total_count = db_utils.query_listings_by_city_paginated(
            city,
            max_price_eur=max_price,
            rooms=rooms if rooms and rooms != "Orice" else None,
            min_sqm=min_sqm,
            max_sqm=max_sqm,
            property_types=property_type_list or None,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        page_df = pd.DataFrame(rows)
        if not page_df.empty:
            page_df = pipeline_core.prepare_dataframe(page_df)
            price_stats = db_utils.get_price_stats(city=city)
            page_df = pipeline_core.apply_price_fairness(page_df, price_stats=price_stats)
    else:
        if all_districts:
            rows = db_utils.query_listings_by_city(city, max_price_eur=max_price)
        else:
            rows = db_utils.query_listings_by_district(all_zones, max_price_eur=max_price, city=city)
        df = pd.DataFrame(rows)

        if not df.empty:
            df = pipeline_core.prepare_dataframe(df)
            df = pipeline_core.apply_filters(
                df,
                max_price=max_price or 0,
                sel_rooms=rooms or "Orice",
                min_sqm=min_sqm or 0,
                max_sqm=max_sqm or 0,
                property_types=property_type_list or None,
            )
            price_stats = db_utils.get_price_stats(city=city)  # not cached at this layer, see MIGRATION_PLAN.md Phase 1
            df = pipeline_core.apply_price_fairness(df, price_stats=price_stats)

            if needs_ranking:
                df, embedding_sorted, embed_error = pipeline_core.apply_ai_scores(
                    df, vibe or "", url_col="url", embed_query=embed_query, image_embedding=image_embedding,
                )

        total_count = len(df)
        start = (page - 1) * page_size
        page_df = df.iloc[start : start + page_size] if not df.empty else df

    has_score_col = "_similarity_score" in page_df.columns
    has_text_score_col = "_text_similarity" in page_df.columns
    has_image_score_col = "_image_similarity" in page_df.columns

    results = []
    for _, row in page_df.iterrows():
        district = _clean(row.get("district")) or ""
        results.append({
            "url": row.get("url"),
            "platform": _clean(row.get("platform")) or "",
            "title": _clean(row.get("title")) or "",
            "description": _clean(row.get("description")) or "",
            "price_numeric": _clean(row.get("price_numeric")) or 0,
            "price_currency": _clean(row.get("price_currency")) or "EUR",
            "district": district,
            "sector": sector_for(city, district),
            "location_full": _clean(row.get("location_full")) or "",
            "rooms": str(_clean(row.get("rooms")) or ""),
            "area_sqm": _clean(row.get("area_sqm")),
            "property_type": _clean(row.get("property_type")) or "",
            "is_available": 1,
            "scraped_at": _clean(row.get("scraped_at")),
            "first_seen_at": _clean(row.get("first_seen_at")),
            "features": _parse_list_field(row.get("features")),
            "image_urls": _parse_list_field(row.get("image_urls")),
            "matchScore": _clean(row.get("_similarity_score")) if has_score_col else None,
            "textSimilarity": _clean(row.get("_text_similarity")) if has_text_score_col else None,
            "imageSimilarity": _clean(row.get("_image_similarity")) if has_image_score_col else None,
            "priceFairnessPct": _clean(row.get("price_fairness_pct")),
            "matchedFilters": [],
            "isNearbyZone": district in nearby_set and district not in core_zones,
        })

    session_id = str(uuid.uuid4())
    db_utils.log_user_search(
        session_id=session_id,
        visitor_id=session_id,
        http_method="GET",
        http_path="/listings/search",
        form_fields=applied_filters,
        results_count=total_count,
        vibe_text=vibe,
        embedding_sorted=embedding_sorted,
        error_message=embed_error,
    )

    return {
        "results": results,
        "applied_filters": applied_filters,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "embedding_sorted": embedding_sorted,
        "embed_error": embed_error,
    }


@app.get("/template-photos", response_model=list[TemplatePhotoOut])
def get_template_photos():
    return list_template_photos()


@app.post("/events", response_model=EventOut)
def log_event(event: EventIn):
    logged = db_utils.log_user_event(
        event_type=event.event_type,
        visitor_id=event.visitor_id,
        session_id=event.session_id,
        path=event.path,
        metadata=event.metadata,
    )
    return {"logged": logged}
