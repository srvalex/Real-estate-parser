import type { HardFilters, Listing, ScoredListing, VibeFilterKey, VibeFilters } from "./types";

const STOPWORDS = new Set([
  "un",
  "o",
  "de",
  "la",
  "cu",
  "si",
  "și",
  "in",
  "în",
  "pe",
  "care",
  "din",
  "sa",
  "să",
  "este",
  "sunt",
  "mai",
  "foarte",
  "the",
  "and",
  "a",
]);

function tokenize(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9\s]/g, " ")
      .split(/\s+/)
      .filter((t) => t.length > 2 && !STOPWORDS.has(t))
  );
}

/** Crude bag-of-words Jaccard overlap — stands in for the real text-embedding cosine similarity. */
function textOverlap(vibe: string, listing: Listing): number {
  const vibeTokens = tokenize(vibe);
  if (vibeTokens.size === 0) return 0;
  const listingTokens = tokenize(`${listing.title} ${listing.description}`);
  let hits = 0;
  vibeTokens.forEach((t) => {
    if (listingTokens.has(t)) hits += 1;
  });
  return hits / vibeTokens.size;
}

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
      if (listing.area_sqm >= Number(value)) matched.push(key);
      return;
    }
    if (key === "AREA_MAX") {
      if (listing.area_sqm <= Number(value)) matched.push(key);
      return;
    }
    const tag = FEATURE_TAG_FOR_FILTER[key];
    if (tag && listing.features.includes(tag)) matched.push(key);
  });
  return matched;
}

export function applyHardFilters(listings: Listing[], filters: HardFilters): Listing[] {
  return listings.filter((l) => {
    if (filters.maxPrice > 0 && l.price_numeric > filters.maxPrice) return false;
    if (filters.rooms !== "Orice" && l.rooms !== filters.rooms) return false;
    if (filters.minSqm > 0 && l.area_sqm < filters.minSqm) return false;
    if (filters.maxSqm > 0 && l.area_sqm > filters.maxSqm) return false;
    if (filters.propertyTypes.length > 0 && !filters.propertyTypes.includes(l.property_type)) return false;
    return true;
  });
}

const MIN_COMPARABLES = 5;

/** Avg rent per (district, rooms) bucket, falling back to (sector, rooms) when too sparse. */
export function buildPriceIndex(listings: Listing[]) {
  const byDistrictRoom = new Map<string, number[]>();
  const bySectorRoom = new Map<string, number[]>();

  for (const l of listings) {
    if (l.price_currency !== "EUR") continue;
    const dKey = `${l.district}::${l.rooms}`;
    const sKey = `${l.sector}::${l.rooms}`;
    (byDistrictRoom.get(dKey) ?? byDistrictRoom.set(dKey, []).get(dKey)!).push(l.price_numeric);
    (bySectorRoom.get(sKey) ?? bySectorRoom.set(sKey, []).get(sKey)!).push(l.price_numeric);
  }

  const avg = (arr: number[]) => arr.reduce((s, v) => s + v, 0) / arr.length;

  return function fairnessPct(listing: Listing): number | null {
    if (listing.price_currency !== "EUR") return null;
    const dKey = `${listing.district}::${listing.rooms}`;
    const sKey = `${listing.sector}::${listing.rooms}`;
    const dBucket = byDistrictRoom.get(dKey) ?? [];
    const bucket = dBucket.length >= MIN_COMPARABLES ? dBucket : bySectorRoom.get(sKey) ?? [];
    if (bucket.length < MIN_COMPARABLES) return null;
    const bucketAvg = avg(bucket);
    if (bucketAvg <= 0) return null;
    return Math.round(((listing.price_numeric - bucketAvg) / bucketAvg) * 100);
  };
}

export function scoreListings(
  listings: Listing[],
  vibe: string,
  vibeFilters: VibeFilters,
  nearbyZones: Set<string>
): ScoredListing[] {
  const fairnessOf = buildPriceIndex(listings);
  const hasVibe = vibe.trim().length > 0;
  const filterKeys = Object.keys(vibeFilters) as VibeFilterKey[];

  return listings.map((listing) => {
    const matched = hasVibe ? matchedVibeFilters(listing, vibeFilters) : [];
    const filterCoverage = filterKeys.length > 0 ? matched.length / filterKeys.length : 0;
    const textSimilarity = hasVibe ? textOverlap(vibe, listing) : null;

    let matchScore: number | null = null;
    if (hasVibe) {
      const overlapScore = textSimilarity ?? 0;
      matchScore = Math.min(1, filterCoverage * 0.6 + overlapScore * 0.9 + 0.15);
    }

    return {
      ...listing,
      matchScore,
      textSimilarity,
      imageSimilarity: null,
      priceFairnessPct: fairnessOf(listing),
      matchedFilters: matched,
      isNearbyZone: nearbyZones.has(listing.district),
    };
  });
}
