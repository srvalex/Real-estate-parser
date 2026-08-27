"""
api/main.py
─────────────────
GET /listings/search — the search pipeline extracted from Streamlit
(streamlit_interface/components/home.py) into a plain HTTP endpoint, per
MIGRATION_PLAN.md Phase 1 (hard filters) + Phase 3 (vibe ranking), combined
in one pass. Hard filters only, from explicit request params — no
spaCy/agent NLP backfill of unset fields yet (Phase 5's job).

Uses get_anon_client() throughout (via db_utils), never get_client() —
same rule as every Streamlit-facing read today.
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
from api.schemas import SearchResponse
from embedding import embed_query

app = FastAPI(title="Real Estate Search API")

_allowed_origins = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET"],
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
    districts: str = Query(..., description="Comma-separated neighbourhood names (required, non-empty)"),
    nearby_districts: Optional[str] = Query(None, description="Comma-separated proximity-expanded extra zones"),
    max_price: Optional[float] = Query(None, ge=0),
    rooms: Optional[str] = Query(None),
    min_sqm: Optional[float] = Query(None, ge=0),
    max_sqm: Optional[float] = Query(None, ge=0),
    property_types: Optional[str] = Query(None, description="Comma-separated"),
    vibe: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    core_zones = _split_csv(districts)
    nearby_zones = _split_csv(nearby_districts)
    if not core_zones:
        raise HTTPException(status_code=422, detail="districts must be a non-empty comma-separated list")

    property_type_list = _split_csv(property_types)
    nearby_set = set(nearby_zones)
    # dedup while keeping a stable order; nearby zones only ever add rows,
    # never narrow the core selection
    all_zones = list(dict.fromkeys(core_zones + nearby_zones))

    rows = db_utils.query_listings_by_district(all_zones, max_price_eur=max_price)
    df = pd.DataFrame(rows)

    applied_filters: dict[str, dict] = {"districts": {"value": core_zones, "source": "user"}}
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

    embedding_sorted = False
    embed_error = None

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
        price_stats = db_utils.get_price_stats()  # not cached at this layer, see MIGRATION_PLAN.md Phase 1
        df = pipeline_core.apply_price_fairness(df, price_stats=price_stats)

        if vibe and vibe.strip():
            df, embedding_sorted, embed_error = pipeline_core.apply_ai_scores(
                df, vibe, url_col="url", embed_query=embed_query,
            )

    total_count = len(df)
    start = (page - 1) * page_size
    page_df = df.iloc[start : start + page_size] if not df.empty else df

    has_score_col = "_similarity_score" in page_df.columns

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
            "sector": sector_for(district),
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
            "textSimilarity": _clean(row.get("_similarity_score")) if has_score_col else None,
            "imageSimilarity": None,
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
