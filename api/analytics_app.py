"""
api/analytics_app.py
─────────────────
The internal market-analytics service — a **separate** FastAPI app from
api/main.py, deployed as its own process on its own port, consumed only by
the internal dashboard (analytics_ui/).

Why a second app rather than a router on the public API:

1. The aggregate market picture (rent by sector, supply per day, platform
   mix) is the asset this project is accumulating — it's what
   MONETIZATION_PLAN.md expects to sell. Renters searching for a flat have
   no need for it, so it shouldn't be reachable from the surface they hit.
2. Isolation you can see from the outside. A router behind an `if token`
   check inside api/main.py is one bad edit away from being public, and it
   ships in the same deployment, same CORS list, same rate limits. Two
   processes means the public one has no analytics code path to reach at
   all — the dashboard's origin isn't in its CORS list and its endpoints
   aren't in its route table.

Both layers of the boundary are enforced here:

* **Auth** — every endpoint requires `X-Analytics-Token` matching
  ANALYTICS_API_TOKEN. Startup fails loudly if that variable is unset,
  rather than serving the market data open to the internet (same reasoning
  as db_utils.get_anon_client() refusing to fall back to the service key).
* **Aggregates only** — responses come from api/analytics.py, which reduces
  rows to counts and statistics. No endpoint here returns a listing, so the
  underlying table can't be walked through this service.

Reads go through db_utils.get_anon_client() (inside fetch_analytics_data)
like every other user-facing read — the dashboard being internal doesn't
make service-role access appropriate.

Run with:
    uvicorn api.analytics_app:app --port 8100
"""
import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import db_utils
from api.analytics import ROOM_ORDER, build_summary, filter_by_rooms, prepare_rows
from api.analytics_schemas import AnalyticsCitiesOut, AnalyticsSummaryOut
from api.locations import city_has_sectors, known_cities, sector_for

ANALYTICS_TOKEN_HEADER = "X-Analytics-Token"

# A full scan of `listings` is expensive and the numbers move at crawl
# cadence (hours), not per request — so serve a cached summary. The
# dashboard's own refresh button bypasses it via ?refresh=true.
_SUMMARY_TTL_SECONDS = int(os.environ.get("ANALYTICS_CACHE_TTL", "900"))
# Keyed by (city, rooms) — a cache keyed on city alone would serve a
# 2-room-filtered summary to the next caller asking for the whole city.
_summary_cache: dict[tuple[Optional[str], tuple[str, ...]], tuple[float, dict]] = {}

app = FastAPI(
    title="Real Estate Market Analytics API (internal)",
    description="Aggregate-only market statistics for the internal dashboard. Not public.",
)

# Defaults cover the analytics dashboard's dev ports only — deliberately
# NOT the public frontend's 3000-3002. If the two ever share an origin
# list, the separation this module exists for is gone.
_allowed_origins = [
    o.strip()
    for o in os.environ.get(
        "ANALYTICS_CORS_ORIGINS", "http://localhost:3100,http://localhost:3101"
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _expected_token() -> str:
    token = os.environ.get("ANALYTICS_API_TOKEN", "")
    if not token:
        # Refused rather than defaulted: an unset token on a service whose
        # whole purpose is to be non-public must fail closed. 503 (not 500)
        # because this is a deployment misconfiguration, not a bug in the
        # request.
        raise HTTPException(
            status_code=503,
            detail=(
                "ANALYTICS_API_TOKEN is not configured — the analytics service "
                "refuses to serve market data unauthenticated."
            ),
        )
    return token


def require_token(x_analytics_token: Optional[str] = Header(default=None)) -> None:
    """Constant-time compare so a wrong token can't be narrowed down by
    timing the response."""
    import hmac

    expected = _expected_token()
    if not x_analytics_token or not hmac.compare_digest(x_analytics_token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Analytics-Token")


def _load_summary(city: Optional[str], rooms: tuple[str, ...], refresh: bool) -> dict:
    now = time.monotonic()
    key = (city, rooms)
    cached = _summary_cache.get(key)
    if cached and not refresh and now - cached[0] < _SUMMARY_TTL_SECONDS:
        return cached[1]

    rows = db_utils.fetch_analytics_data(city=city)
    prepared = prepare_rows(
        rows,
        price_in_eur=db_utils.price_in_eur,
        sector_for=sector_for,
        city_has_sectors=city_has_sectors,
    )
    # Filtering here rather than in SQL keeps one cached DB read serving
    # every room selection for a city: `rooms` in the DB is free text
    # ("2 camere", "2"), and prepare_rows is what normalises it, so a
    # WHERE clause could not match reliably anyway.
    prepared = filter_by_rooms(prepared, rooms)
    summary = build_summary(prepared, rooms_filtered=bool(rooms))
    summary["city"] = city
    summary["rooms"] = list(rooms)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    _summary_cache[key] = (now, summary)
    return summary


@app.get("/analytics/cities", response_model=AnalyticsCitiesOut, dependencies=[Depends(require_token)])
def get_cities():
    """Cities the dashboard can scope to — from api/data/cities.json, the
    same source the public API's sector lookup uses, so the two can't drift."""
    return {"cities": known_cities()}


@app.get("/analytics/summary", response_model=AnalyticsSummaryOut, dependencies=[Depends(require_token)])
def get_summary(
    city: Optional[str] = Query(None, description="Scope to one city; omit for all cities"),
    rooms: Optional[str] = Query(
        None,
        description=f"Comma-separated room counts to include ({', '.join(ROOM_ORDER)}); omit for all",
    ),
    refresh: bool = Query(False, description="Bypass the server-side cache"),
):
    if city and city not in known_cities():
        raise HTTPException(status_code=422, detail=f"Unknown city: {city}")

    selected = tuple(dict.fromkeys(r.strip() for r in (rooms or "").split(",") if r.strip()))
    unknown = [r for r in selected if r not in ROOM_ORDER]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown room count(s): {', '.join(unknown)}. Valid: {', '.join(ROOM_ORDER)}",
        )
    return _load_summary(city, selected, refresh)


@app.get("/health")
def health():
    """Unauthenticated on purpose — it reports nothing about the market,
    only whether the process is up, which a load balancer needs to know."""
    return {"status": "ok", "service": "analytics"}
