"""
api/analytics_schemas.py
─────────────────
Response models for the internal analytics service (api/analytics_app.py).

Kept out of api/schemas.py on purpose: that module describes the public
search API's contract, this one the internal dashboard's, and the two ship
as separate processes. A shared module would make it easy to grow an
accidental import edge between them.
"""
from typing import Optional

from pydantic import BaseModel


class KpisOut(BaseModel):
    total: int
    with_price: int
    with_price_pct: float
    avg_price: int
    median_price: int
    avg_area: int


class DailyPointOut(BaseModel):
    day: str  # YYYY-MM-DD
    count: int


class HistogramBinOut(BaseModel):
    bucket: int
    label: str
    count: int


class SectorCoverageOut(BaseModel):
    """How many priced listings the sector charts actually account for, in
    cities that have sectors at all. `missing` is the honest footnote on
    every sector-based number."""
    attributed: int
    missing: int
    eligible: int


class SectorPriceOut(BaseModel):
    sector: str
    label: str
    avg: int
    median: int
    count: int


class NeighbourhoodPriceOut(BaseModel):
    district: str
    avg: int
    median: int
    count: int


class RoomPriceOut(BaseModel):
    rooms: str
    avg: int
    median: int
    min: int
    max: int
    count: int


class RoomCountOut(BaseModel):
    rooms: str
    count: int


class BreakdownSliceOut(BaseModel):
    name: str
    value: int


class ScatterPointOut(BaseModel):
    area: float
    price: int
    rooms: str


class AnalyticsSummaryOut(BaseModel):
    """One response per dashboard load — aggregates only, never a listing."""
    city: Optional[str] = None
    # Echoed back so the dashboard can confirm what the numbers are scoped
    # to, rather than trusting that its own request state still matches the
    # response it got.
    rooms: list[str] = []
    generated_at: str
    kpis: KpisOut
    sector_coverage: SectorCoverageOut
    daily_listings: list[DailyPointOut]
    price_histogram: list[HistogramBinOut]
    by_sector: list[SectorPriceOut]
    by_neighbourhood: dict[str, list[NeighbourhoodPriceOut]]
    # Both empty while a room filter is active — filtered to one room count
    # they would just restate the filter. The dashboard hides those cards.
    by_rooms: list[RoomPriceOut]
    rooms_distribution: list[RoomCountOut]
    platforms: list[BreakdownSliceOut]
    property_types: list[BreakdownSliceOut]
    price_vs_area: list[ScatterPointOut]


class AnalyticsCitiesOut(BaseModel):
    cities: list[str]
