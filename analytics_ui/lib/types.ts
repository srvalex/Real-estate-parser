// Mirrors api/analytics_schemas.py::AnalyticsSummaryOut field-for-field.
// Every shape here is an aggregate — there is deliberately no Listing type
// in this app, because the analytics service never returns one.

export interface Kpis {
  total: number;
  with_price: number;
  with_price_pct: number;
  avg_price: number;
  median_price: number;
  avg_area: number;
}

export interface SectorCoverage {
  attributed: number;
  missing: number;
  eligible: number;
}

export interface DailyPoint {
  day: string; // YYYY-MM-DD
  count: number;
}

export interface HistogramBin {
  bucket: number;
  label: string;
  count: number;
}

export interface SectorPrice {
  sector: string;
  label: string;
  avg: number;
  median: number;
  count: number;
}

export interface NeighbourhoodPrice {
  district: string;
  avg: number;
  median: number;
  count: number;
}

export interface RoomPrice {
  rooms: string;
  avg: number;
  median: number;
  min: number;
  max: number;
  count: number;
}

export interface RoomCount {
  rooms: string;
  count: number;
}

export interface BreakdownSlice {
  name: string;
  value: number;
}

export interface ScatterPoint {
  area: number;
  price: number;
  rooms: string;
}

export interface AnalyticsSummary {
  city: string | null;
  rooms: string[];
  generated_at: string;
  kpis: Kpis;
  sector_coverage: SectorCoverage;
  daily_listings: DailyPoint[];
  price_histogram: HistogramBin[];
  by_sector: SectorPrice[];
  by_neighbourhood: Record<string, NeighbourhoodPrice[]>;
  by_rooms: RoomPrice[];
  rooms_distribution: RoomCount[];
  platforms: BreakdownSlice[];
  property_types: BreakdownSlice[];
  price_vs_area: ScatterPoint[];
}
