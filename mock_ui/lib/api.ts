import type { HardFilters, PropertyType, RoomCount, ScoredListing, VibeFilters } from "./types";
import { extractVibeFilters } from "./nlpFilters";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface SearchParams {
  city: string;
  wholeCity?: boolean;
  zones: string[];
  nearbyZones: string[];
  hardFilters: HardFilters;
  vibe: string;
  templatePhotos?: string[];
  page?: number;
  pageSize?: number;
}

export interface TemplatePhotoMeta {
  id: string;
  label: string;
}

export interface SearchResponse {
  results: ScoredListing[];
  applied_filters: Record<string, { value: unknown; source: string }>;
  total_count: number;
  page: number;
  page_size: number;
  embedding_sorted: boolean;
  embed_error: string | null;
}

// Exported so the search form (app/home) can build a /results?<query> URL
// with exactly the same shape the API expects — the results page then
// forwards that same query string straight through to the backend
// (searchListingsByQueryString below) instead of re-deriving it.
export function buildQuery(params: SearchParams): string {
  const q = new URLSearchParams();
  q.set("city", params.city);
  if (params.wholeCity) {
    q.set("all_districts", "true");
  } else {
    q.set("districts", params.zones.join(","));
    if (params.nearbyZones.length > 0) q.set("nearby_districts", params.nearbyZones.join(","));
  }
  if (params.hardFilters.maxPrice > 0) q.set("max_price", String(params.hardFilters.maxPrice));
  if (params.hardFilters.rooms !== "Orice") q.set("rooms", params.hardFilters.rooms);
  if (params.hardFilters.minSqm > 0) q.set("min_sqm", String(params.hardFilters.minSqm));
  if (params.hardFilters.maxSqm > 0) q.set("max_sqm", String(params.hardFilters.maxSqm));
  if (params.hardFilters.propertyTypes.length > 0) q.set("property_types", params.hardFilters.propertyTypes.join(","));
  if (params.vibe.trim()) q.set("vibe", params.vibe.trim());
  if (params.templatePhotos && params.templatePhotos.length > 0) {
    q.set("template_photos", params.templatePhotos.join(","));
  }
  q.set("page", String(params.page ?? 1));
  q.set("page_size", String(params.pageSize ?? 60));
  return q.toString();
}

export async function searchListingsByQueryString(qs: string): Promise<SearchResponse> {
  const res = await fetch(`${API_BASE_URL}/listings/search?${qs}`);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Căutarea a eșuat (${res.status})${detail ? `: ${detail}` : ""}`);
  }
  return res.json();
}

// The /results page re-derives display-only state (filter pills, the vibe
// match checklist) from its own URL rather than receiving it from the
// search form directly — that's what makes a results URL shareable and
// survivable across a refresh.
export function hardFiltersFromQuery(sp: URLSearchParams): HardFilters {
  const propertyTypes = sp.get("property_types");
  return {
    maxPrice: Number(sp.get("max_price")) || 0,
    rooms: (sp.get("rooms") as RoomCount | null) ?? "Orice",
    minSqm: Number(sp.get("min_sqm")) || 0,
    maxSqm: Number(sp.get("max_sqm")) || 0,
    propertyTypes: propertyTypes ? (propertyTypes.split(",").filter(Boolean) as PropertyType[]) : [],
  };
}

export function vibeFiltersFromQuery(sp: URLSearchParams): VibeFilters {
  return extractVibeFilters(sp.get("vibe") ?? "");
}
