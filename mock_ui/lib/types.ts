// Mirrors the canonical Supabase `listings` schema (see db_utils.py::_CANONICAL_COLUMNS)
// plus the derived fields the UI computes client-side.

export type Platform = "OLX" | "Storia" | "Imobiliare";

export type PropertyType = "Apartament" | "Garsoniera" | "Studio" | "Casa/Vila";

export type RoomCount = "1" | "2" | "3" | "4" | "5+";

export interface ListingImage {
  thumbnail?: string;
  small?: string;
  medium?: string;
  large?: string;
}

export interface Listing {
  url: string;
  platform: Platform;
  title: string;
  description: string;
  price_numeric: number;
  price_currency: "EUR" | "RON";
  district: string;
  sector: string;
  location_full: string;
  rooms: RoomCount;
  area_sqm: number;
  floor: number;
  total_floors: number;
  year_built: number;
  heating: string;
  features: string[];
  image_urls: ListingImage[];
  property_type: PropertyType;
  is_available: 1 | 0;
  scraped_at: string; // ISO timestamp
  first_seen_at: string; // ISO timestamp
}

// ── Hard filters — user-controlled, exact ────────────────────────────────
export interface HardFilters {
  maxPrice: number; // 0 = no limit
  rooms: RoomCount | "Orice";
  minSqm: number;
  maxSqm: number;
  propertyTypes: PropertyType[];
}

// ── Soft/vibe filters — NLP-inferred from the free-text prompt ──────────
export type VibeFilterKey =
  | "ROOM_COUNT"
  | "PROPERTY_TYPE"
  | "PRICE_MAX"
  | "AREA_MIN"
  | "AREA_MAX"
  | "HAS_METRO"
  | "HAS_PARKING"
  | "HAS_BALCONY"
  | "PET_FRIENDLY"
  | "FURNISHED"
  | "HAS_HEATING_UNIT"
  | "CONDITION_RENOVATED"
  | "STYLE_MODERN"
  | "FEAT_BRIGHT"
  | "FEAT_QUIET";

export type VibeFilters = Partial<Record<VibeFilterKey, string | number | boolean>>;

export interface SearchParams {
  vibe: string;
  hardFilters: HardFilters;
  zones: string[];
  proximityZones: string[];
}

export interface ScoredListing extends Listing {
  matchScore: number | null; // 0..1 overall relevance, null when no vibe/photo query was given
  textSimilarity: number | null; // 0..1
  imageSimilarity: number | null; // 0..1
  priceFairnessPct: number | null; // negative = under district/room average (good)
  matchedFilters: VibeFilterKey[]; // which vibe filters this listing satisfies
  isNearbyZone: boolean;
}

export type SourceStatus = "pending" | "loading" | "done" | "slow";

export interface SourceState {
  platform: Platform;
  status: SourceStatus;
}
