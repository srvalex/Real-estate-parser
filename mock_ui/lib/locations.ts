import citiesJson from "./data/cities.json";

// Country-wide location tree (GEO_EXPANSION_PLAN.md Phase 0/3). Most cities
// are flat (a city has neighbourhoods directly); a few — București so far —
// are split into districts (sectors) that each hold their own
// neighbourhoods. Sourced from lib/data/cities.json, a mirror of
// api/data/cities.json (București's existing 120-neighbourhood curated
// list, Cluj-Napoca/Iași's live distinct district values — see that file's
// own comment for why "live data" rather than hand-curated for those two).
export type LocationDistrict = {
  name: string;
  zones: string[];
};

export type LocationCity =
  | { city: string; districts: LocationDistrict[]; zones?: undefined }
  | { city: string; districts?: undefined; zones: string[] };

// The `city` field above is the pretty display name (with diacritics) —
// it's what's shown in the UI and what SearchExperience tracks as
// `selectedCity`. The actual `listings.city` column (and therefore the
// API's `city` query param) uses the plain ASCII form the scrapers write.
// Translate only at the point of firing a search request, never earlier —
// every other piece of UI logic (matching, chips, breadcrumb) works on the
// display name directly.
const DISPLAY_TO_API_CITY: Record<string, string> = {
  "București": "Bucuresti",
  "Cluj-Napoca": "Cluj-Napoca",
  "Iași": "Iasi",
};

export function toApiCity(displayName: string): string {
  return DISPLAY_TO_API_CITY[displayName] ?? displayName;
}

const API_TO_DISPLAY_CITY: Record<string, string> = {
  Bucuresti: "București",
  "Cluj-Napoca": "Cluj-Napoca",
  Iasi: "Iași",
};

// Inverse of toApiCity — needed to rehydrate the search form's
// `selectedCity` (display name) from the API-form `city` query param when
// restoring state from a /results URL (e.g. the "Căutare nouă" back link).
export function toDisplayCity(apiCity: string): string {
  return API_TO_DISPLAY_CITY[apiCity] ?? apiCity;
}

export function getLocations(): LocationCity[] {
  const cities = citiesJson as Record<string, Record<string, string[]> | string[]>;
  return Object.entries(cities).map(([apiCity, value]) => {
    const city = API_TO_DISPLAY_CITY[apiCity] ?? apiCity;
    if (Array.isArray(value)) {
      return { city, zones: value };
    }
    return {
      city,
      districts: Object.entries(value).map(([name, zones]) => ({ name, zones })),
    };
  });
}
