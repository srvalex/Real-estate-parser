// Lightweight regex-based Romanian filter extractor — a TS port of the spaCy-based
// pipeline in streamlit_interface/pipeline/nlp_filters.py, scoped to what the mock
// UI needs to demonstrate: pulling structured filters out of the free-text "vibe" prompt.

import type { PropertyType, RoomCount, VibeFilterKey, VibeFilters } from "./types";

function stripDiacritics(text: string): string {
  return text
    .replace(/ă/g, "a")
    .replace(/â/g, "a")
    .replace(/î/g, "i")
    .replace(/ș/g, "s")
    .replace(/ş/g, "s")
    .replace(/ț/g, "t")
    .replace(/ţ/g, "t");
}

const BOOLEAN_TAXONOMY: [RegExp, VibeFilterKey][] = [
  [/\bmetrou\b/, "HAS_METRO"],
  [/\brenovat[aă]?\b/, "CONDITION_RENOVATED"],
  [/\bmodern[aă]?\b/, "STYLE_MODERN"],
  [/\bluminos[aă]?\b/, "FEAT_BRIGHT"],
  [/\bcentral[aă]\b/, "HAS_HEATING_UNIT"],
  [/\b(parcare|garaj)\b/, "HAS_PARKING"],
  [/\bbalcon\b/, "HAS_BALCONY"],
  [/\bpet[\s-]?friendly\b/, "PET_FRIENDLY"],
  [/\banimal(e)?\s+de\s+companie\b/, "PET_FRIENDLY"],
  [/\bmobilat[aă]?\b/, "FURNISHED"],
  [/\blinistit[aă]?\b/, "FEAT_QUIET"],
];

const PROPERTY_TYPE_PATTERNS: [RegExp, PropertyType][] = [
  [/\bgarsonier[aă]|garconiera\b/, "Garsoniera"],
  [/\bstudio\b/, "Studio"],
  [/\b(casa|vila|duplex)\b/, "Casa/Vila"],
  [/\bapartament\b/, "Apartament"],
];

export function extractVibeFilters(rawText: string): VibeFilters {
  const found: VibeFilters = {};
  if (!rawText.trim()) return found;

  const normalized = stripDiacritics(rawText.toLowerCase());

  // Room count — "2 camere" / "2 camera"
  const roomMatch = normalized.match(/(\d+)\s*camer[ae]/);
  if (roomMatch) {
    const n = parseInt(roomMatch[1], 10);
    found.ROOM_COUNT = n >= 5 ? "5+" : String(n);
  }

  // Boolean taxonomy
  for (const [pattern, key] of BOOLEAN_TAXONOMY) {
    if (!found[key] && pattern.test(normalized)) {
      found[key] = true;
    }
  }

  // "nemobilat" should not also register FURNISHED
  if (/\bnemobilat[aă]?\b/.test(normalized)) {
    delete found.FURNISHED;
  }

  // Property type
  for (const [pattern, type] of PROPERTY_TYPE_PATTERNS) {
    if (pattern.test(normalized)) {
      found.PROPERTY_TYPE = type;
      break;
    }
  }

  // Area — "minim 50 mp" / "pana la 70 mp" / bare "60 mp"
  const areaMin = normalized.match(/(?:minim|cel putin|minimum|peste|mai mare de)\s+(\d+)\s*mp/);
  if (areaMin) found.AREA_MIN = parseInt(areaMin[1], 10);
  const areaMax = normalized.match(/(?:maxim|pana la|cel mult|sub)\s+(\d+)\s*mp/);
  if (areaMax) found.AREA_MAX = parseInt(areaMax[1], 10);
  if (!found.AREA_MIN && !found.AREA_MAX) {
    const bareArea = normalized.match(/(\d{2,3})\s*mp/);
    if (bareArea) found.AREA_MIN = parseInt(bareArea[1], 10);
  }

  // Price — "maxim 1500 euro" / bare "1500 euro"
  const currency = "(?:euro|eur|ron|lei)";
  const priceExplicit = normalized.match(
    new RegExp(`(?:maxim|pana la|cel mult|sub|mai putin de|buget(?: de)?|pret maxim)\\s*(\\d{3,5})\\s*${currency}`)
  );
  if (priceExplicit) {
    found.PRICE_MAX = parseInt(priceExplicit[1], 10);
  } else {
    const priceBare = normalized.match(new RegExp(`(\\d{3,5})\\s*${currency}`));
    if (priceBare) found.PRICE_MAX = parseInt(priceBare[1], 10);
  }

  return found;
}

// ── Description-level confirmation / exclusion (mirrors apply_description_filters) ──
const EXCLUSION_PATTERNS: Partial<Record<VibeFilterKey, RegExp[]>> = {
  PET_FRIENDLY: [/nu accept[aă]m animale/, /fara animale/, /animale nepermise/, /no pets/],
  HAS_PARKING: [/fara loc de parcare/, /nu (are|include|dispune de) parcare/],
  HAS_BALCONY: [/fara balcon/, /nu are balcon/],
  FURNISHED: [/nemobilat/, /fara mobila/, /nu este mobilat/],
  HAS_HEATING_UNIT: [/fara centrala/, /nu are centrala/],
};

export function isExcludedByDescription(description: string, filters: VibeFilters): VibeFilterKey[] {
  const normalized = stripDiacritics(description.toLowerCase());
  const violated: VibeFilterKey[] = [];
  (Object.keys(filters) as VibeFilterKey[]).forEach((key) => {
    const patterns = EXCLUSION_PATTERNS[key];
    if (!patterns) return;
    if (patterns.some((p) => p.test(normalized))) violated.push(key);
  });
  return violated;
}

// ── End-user-facing copy for each filter key — never expose raw internal keys ──
export const VIBE_FILTER_LABELS: Record<VibeFilterKey, string> = {
  ROOM_COUNT: "camere",
  PROPERTY_TYPE: "tip locuință",
  PRICE_MAX: "preț maxim",
  AREA_MIN: "suprafață minimă",
  AREA_MAX: "suprafață maximă",
  HAS_METRO: "aproape de metrou",
  HAS_PARKING: "parcare inclusă",
  HAS_BALCONY: "cu balcon",
  PET_FRIENDLY: "acceptă animale",
  FURNISHED: "mobilat",
  HAS_HEATING_UNIT: "centrală proprie",
  CONDITION_RENOVATED: "recent renovat",
  STYLE_MODERN: "stil modern",
  FEAT_BRIGHT: "luminos",
  FEAT_QUIET: "zonă liniștită",
};

export function formatVibeFilterValue(key: VibeFilterKey, value: string | number | boolean): string {
  if (typeof value === "boolean") return VIBE_FILTER_LABELS[key];
  if (key === "ROOM_COUNT") return `${value} camere`;
  if (key === "PRICE_MAX") return `preț ≤ ${value} €`;
  if (key === "AREA_MIN") return `suprafață ≥ ${value} m²`;
  if (key === "AREA_MAX") return `suprafață ≤ ${value} m²`;
  return String(value);
}
