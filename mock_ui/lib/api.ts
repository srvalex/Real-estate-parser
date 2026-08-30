import type { HardFilters, ScoredListing } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface SearchParams {
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

function buildQuery(params: SearchParams): string {
  const q = new URLSearchParams();
  q.set("districts", params.zones.join(","));
  if (params.nearbyZones.length > 0) q.set("nearby_districts", params.nearbyZones.join(","));
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

export async function searchListings(params: SearchParams): Promise<SearchResponse> {
  const res = await fetch(`${API_BASE_URL}/listings/search?${buildQuery(params)}`);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Căutarea a eșuat (${res.status})${detail ? `: ${detail}` : ""}`);
  }
  return res.json();
}
