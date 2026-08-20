import districtsJson from "./data/districts.json";
import { Rng } from "./seededRandom";
import type { Listing, ListingImage, Platform, PropertyType, RoomCount } from "./types";

const DISTRICTS = districtsJson as Record<string, string[]>;

// Relative rent multiplier per sector — Sector 1 (Dorobanți, Primăverii, Floreasca…)
// is the priciest, Sector 5 the most affordable. Loosely mirrors real Bucharest rents.
const SECTOR_MULTIPLIER: Record<string, number> = {
  "Sector 1": 1.5,
  "Sector 2": 1.15,
  "Sector 3": 1.0,
  "Sector 4": 0.85,
  "Sector 5": 0.78,
  "Sector 6": 0.88,
};

const ROOM_BASE_PRICE: Record<RoomCount, number> = {
  "1": 380,
  "2": 550,
  "3": 750,
  "4": 950,
  "5+": 1250,
};

const ROOM_AREA_RANGE: Record<RoomCount, [number, number]> = {
  "1": [28, 45],
  "2": [48, 68],
  "3": [64, 90],
  "4": [85, 115],
  "5+": [110, 170],
};

const ROOMS: RoomCount[] = ["1", "2", "3", "4", "5+"];
const PLATFORMS: readonly (readonly [Platform, number])[] = [
  ["OLX", 45],
  ["Storia", 35],
  ["Imobiliare", 20],
];

const POSITIVE_FEATURES = [
  { phrase: "Aproape de metrou, 5 minute pe jos.", tag: "metro" },
  { phrase: "Recent renovat, finisaje noi.", tag: "renovated" },
  { phrase: "Design modern, minimalist.", tag: "modern" },
  { phrase: "Foarte luminos, expunere sud.", tag: "bright" },
  { phrase: "Centrală proprie, apă caldă non-stop.", tag: "heating" },
  { phrase: "Loc de parcare inclus în preț.", tag: "parking" },
  { phrase: "Balcon generos, priveliște liberă.", tag: "balcony" },
  { phrase: "Pet-friendly — acceptăm animale de companie.", tag: "pets" },
  { phrase: "Complet mobilat și utilat.", tag: "furnished" },
  { phrase: "Zonă liniștită, departe de trafic.", tag: "quiet" },
] as const;

const NEGATIVE_FEATURES: Record<string, string> = {
  parking: "Fără loc de parcare propriu.",
  balcony: "Fără balcon.",
  pets: "Nu acceptăm animale de companie.",
  furnished: "Nemobilat — apartament la gri.",
  heating: "Căldură de la asociație, fără centrală proprie.",
};

const TITLE_TEMPLATES: Record<PropertyType, string[]> = {
  Apartament: ["Apartament {rooms} camere, {district}", "Apartament {rooms} camere de închiriat, {district}"],
  Garsoniera: ["Garsonieră modernă, {district}", "Garsonieră de închiriat, {district}"],
  Studio: ["Studio renovat, {district}", "Studio modern, {district}"],
  "Casa/Vila": ["Casă {rooms} camere, {district}", "Vilă cu curte, {district}"],
};

const INTROS = [
  "Închiriez direct de la proprietar,",
  "Disponibil din luna curentă,",
  "Ideal pentru familie sau colegi,",
  "Situat la doi pași de mijloacele de transport,",
  "Bloc nou, zonă în plină dezvoltare,",
];

function propertyTypeForRooms(rng: Rng, rooms: RoomCount): PropertyType {
  if (rooms === "1") return rng.pickWeighted([["Garsoniera", 6], ["Studio", 4]]);
  if (rooms === "5+") return rng.pickWeighted([["Apartament", 5], ["Casa/Vila", 5]]);
  return rng.pickWeighted([["Apartament", 9], ["Casa/Vila", 1]]);
}

function buildImages(rng: Rng, seed: number): ListingImage[] {
  if (rng.bool(0.12)) return []; // ~12% of listings have no photos — exercises the fallback state
  const count = rng.int(1, 6);
  return Array.from({ length: count }, (_, i) => {
    const photoSeed = `listing-${seed}-${i}`;
    return {
      thumbnail: `https://picsum.photos/seed/${photoSeed}/160/110`,
      small: `https://picsum.photos/seed/${photoSeed}/400/280`,
      medium: `https://picsum.photos/seed/${photoSeed}/800/560`,
      large: `https://picsum.photos/seed/${photoSeed}/1400/980`,
    };
  });
}

function buildDescription(rng: Rng, rooms: RoomCount, district: string): { text: string; features: string[] } {
  const featureCount = rng.int(2, 4);
  const chosen = rng.shuffle(POSITIVE_FEATURES).slice(0, featureCount);
  const lines: string[] = [];
  const activeFeatures: string[] = [];

  for (const feature of chosen) {
    // ~18% chance a feature the listing "has a tag for" is actually negated in prose —
    // this is what the description-level exclusion filter is meant to catch.
    if (NEGATIVE_FEATURES[feature.tag] && rng.bool(0.18)) {
      lines.push(NEGATIVE_FEATURES[feature.tag]);
    } else {
      lines.push(feature.phrase);
      activeFeatures.push(feature.tag);
    }
  }

  const intro = `${rng.pick(INTROS)} apartament cu ${rooms} camere în ${district}.`;
  return { text: [intro, ...lines].join(" "), features: activeFeatures };
}

function daysAgoIso(rng: Rng, maxDays: number): string {
  const ms = Date.parse("2026-08-19T12:00:00Z") - rng.float(0, maxDays) * 86_400_000;
  return new Date(ms).toISOString();
}

function generateListings(count: number, seed: number): Listing[] {
  const rng = new Rng(seed);
  const sectorNames = Object.keys(DISTRICTS);
  const listings: Listing[] = [];

  for (let i = 0; i < count; i++) {
    const sector = rng.pick(sectorNames);
    const district = rng.pick(DISTRICTS[sector]);
    const rooms = rng.pick(ROOMS);
    const propertyType = propertyTypeForRooms(rng, rooms);
    const platform = rng.pickWeighted(PLATFORMS);

    const [areaMin, areaMax] = ROOM_AREA_RANGE[rooms];
    const areaSqm = Math.round(rng.float(areaMin, areaMax));

    const basePrice = ROOM_BASE_PRICE[rooms] * (SECTOR_MULTIPLIER[sector] ?? 1);
    const priceNoise = rng.float(0.85, 1.2);
    const priceNumeric = Math.round((basePrice * priceNoise) / 5) * 5;

    const { text: description, features } = buildDescription(rng, rooms, district);
    const titleTemplate = rng.pick(TITLE_TEMPLATES[propertyType]);
    const title = titleTemplate.replace("{rooms}", rooms).replace("{district}", district);

    const firstSeen = daysAgoIso(rng, 45);
    const scraped = daysAgoIso(rng, 5);

    listings.push({
      url: `https://www.${platform.toLowerCase()}.ro/listing/${seed}-${i}`,
      platform,
      title,
      description,
      price_numeric: priceNumeric,
      price_currency: "EUR",
      district,
      sector,
      location_full: `${district}, ${sector}, București`,
      rooms,
      area_sqm: areaSqm,
      floor: rng.int(0, 10),
      total_floors: rng.int(4, 12),
      year_built: rng.int(1965, 2024),
      heating: features.includes("heating") ? "Centrală proprie" : "Termoficare",
      features,
      image_urls: buildImages(rng, i),
      property_type: propertyType,
      is_available: 1,
      scraped_at: scraped,
      first_seen_at: firstSeen,
    });
  }

  return listings;
}

// Generated once at module load — deterministic seed keeps server and client
// render identical (this stands in for `SELECT * FROM listings` until the
// real Supabase-backed API route is wired up).
export const ALL_LISTINGS: Listing[] = generateListings(220, 20260819);

export function getDistrictsBySector(): Record<string, string[]> {
  return DISTRICTS;
}
