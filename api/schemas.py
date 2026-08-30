"""
api/schemas.py
─────────────────
Pydantic response models, matching mock_ui/lib/types.ts::ScoredListing
field-for-field so the frontend's existing types need minimal changes.
"""
from typing import Literal, Optional

from pydantic import BaseModel


class ListingImageOut(BaseModel):
    thumbnail: Optional[str] = None
    small: Optional[str] = None
    medium: Optional[str] = None
    large: Optional[str] = None


class ScoredListingOut(BaseModel):
    url: str
    platform: str
    title: str
    description: str
    price_numeric: float
    price_currency: str
    district: str
    sector: str
    location_full: str
    rooms: str
    area_sqm: Optional[float] = None
    property_type: str
    is_available: int = 1
    scraped_at: Optional[str] = None
    first_seen_at: Optional[str] = None
    features: list[str] = []
    image_urls: list[ListingImageOut] = []

    matchScore: Optional[float] = None
    textSimilarity: Optional[float] = None
    imageSimilarity: Optional[float] = None
    priceFairnessPct: Optional[float] = None
    matchedFilters: list[str] = []
    isNearbyZone: bool = False


class AppliedFilterField(BaseModel):
    value: object
    source: str  # "user" | "unset" — no NLP/agent backfill yet (Phase 5)


class SearchResponse(BaseModel):
    results: list[ScoredListingOut]
    applied_filters: dict[str, AppliedFilterField]
    total_count: int
    page: int
    page_size: int
    embedding_sorted: bool
    embed_error: Optional[str] = None


class EventIn(BaseModel):
    """POST /events body — minimal alpha traffic tracking, see user_events
    in scripts/supabase_schema.sql (section 9d). event_type is restricted
    to the alpha's known set (extend this Literal, not a free string, when
    a new event type is actually needed)."""
    event_type: Literal["page_view", "listing_click"]
    visitor_id: str
    session_id: Optional[str] = None
    path: Optional[str] = None
    metadata: Optional[dict] = None


class EventOut(BaseModel):
    logged: bool


class TemplatePhotoOut(BaseModel):
    """One of the 4 curated visual-style reference photos (api/template_photos.py),
    for GET /template-photos and the /listings/search `template_photos` param."""
    id: str
    label: str
