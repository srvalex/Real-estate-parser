import type { Listing, VibeFilterKey, VibeFilters } from "./types";

// Hard filtering, semantic ranking and price-fairness are now computed
// server-side (api/main.py, pipeline_core.py) against real listings —
// matchedVibeFilters is the one piece still worth keeping client-side: a
// display-layer helper turning the live-typed vibe filters into the
// MatchReceipt checklist, cross-checked against whatever the real
// `features` column actually holds for a given listing (its vocabulary
// doesn't fully match this list — see api/main.py's _parse_list_field
// comment — so this degrades to "no checkmark shown" rather than a wrong
// one for filters that don't have a matching real tag yet).
const FEATURE_TAG_FOR_FILTER: Partial<Record<VibeFilterKey, string>> = {
  HAS_METRO: "metro",
  HAS_PARKING: "parking",
  HAS_BALCONY: "balcony",
  PET_FRIENDLY: "pets",
  FURNISHED: "furnished",
  HAS_HEATING_UNIT: "heating",
  CONDITION_RENOVATED: "renovated",
  STYLE_MODERN: "modern",
  FEAT_BRIGHT: "bright",
  FEAT_QUIET: "quiet",
};

export function matchedVibeFilters(listing: Listing, filters: VibeFilters): VibeFilterKey[] {
  const matched: VibeFilterKey[] = [];
  (Object.keys(filters) as VibeFilterKey[]).forEach((key) => {
    const value = filters[key];
    if (value === undefined) return;

    if (key === "ROOM_COUNT") {
      if (listing.rooms === String(value)) matched.push(key);
      return;
    }
    if (key === "PROPERTY_TYPE") {
      if (listing.property_type === value) matched.push(key);
      return;
    }
    if (key === "PRICE_MAX") {
      if (listing.price_numeric <= Number(value)) matched.push(key);
      return;
    }
    if (key === "AREA_MIN") {
      if (listing.area_sqm !== null && listing.area_sqm >= Number(value)) matched.push(key);
      return;
    }
    if (key === "AREA_MAX") {
      if (listing.area_sqm !== null && listing.area_sqm <= Number(value)) matched.push(key);
      return;
    }
    const tag = FEATURE_TAG_FOR_FILTER[key];
    if (tag && listing.features.includes(tag)) matched.push(key);
  });
  return matched;
}
