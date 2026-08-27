import { ALL_LISTINGS } from "./mockData";
import type { Listing, PropertyType, RoomCount } from "./types";

export const CHART_PALETTE = ["#A8461F", "#3E4E3A", "#B8892B", "#8C8579", "#C97247", "#647A5E", "#D4AF63"];

const ROOM_ORDER: RoomCount[] = ["1", "2", "3", "4", "5+"];

function eurPrice(l: Listing): number | null {
  if (l.price_currency !== "EUR") return null;
  if (l.price_numeric < 50 || l.price_numeric > 10_000) return null;
  return l.price_numeric;
}

export function computeKpis(listings: Listing[] = ALL_LISTINGS) {
  const withPrice = listings.map(eurPrice).filter((p): p is number => p !== null);
  const avg = withPrice.length ? withPrice.reduce((s, v) => s + v, 0) / withPrice.length : 0;
  const sorted = [...withPrice].sort((a, b) => a - b);
  const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
  const avgArea = listings.length
    ? listings.reduce((s, l) => s + l.area_sqm, 0) / listings.length
    : 0;

  return {
    total: listings.length,
    withPrice: withPrice.length,
    withPricePct: listings.length ? (withPrice.length / listings.length) * 100 : 0,
    avgPrice: Math.round(avg),
    medianPrice: Math.round(median),
    avgArea: Math.round(avgArea),
  };
}

export function dailyListingsSeries(listings: Listing[] = ALL_LISTINGS) {
  const byDay = new Map<string, number>();
  for (const l of listings) {
    const day = l.first_seen_at.slice(0, 10);
    byDay.set(day, (byDay.get(day) ?? 0) + 1);
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([day, count]) => ({ day: day.slice(5), count }));
}

export function priceHistogram(listings: Listing[] = ALL_LISTINGS, bucketSize = 100) {
  const prices = listings.map(eurPrice).filter((p): p is number => p !== null);
  const buckets = new Map<number, number>();
  for (const p of prices) {
    const bucket = Math.floor(p / bucketSize) * bucketSize;
    buckets.set(bucket, (buckets.get(bucket) ?? 0) + 1);
  }
  return [...buckets.entries()]
    .sort(([a], [b]) => a - b)
    .map(([bucket, count]) => ({ bucket: `€${bucket}`, count }));
}

export function avgPriceBySector(listings: Listing[] = ALL_LISTINGS) {
  const bySector = new Map<string, number[]>();
  for (const l of listings) {
    const p = eurPrice(l);
    if (p === null) continue;
    (bySector.get(l.sector) ?? bySector.set(l.sector, []).get(l.sector)!).push(p);
  }
  return [...bySector.entries()]
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([sector, prices]) => {
      const sorted = [...prices].sort((a, b) => a - b);
      return {
        sector,
        label: sector.replace("Sector ", "S"),
        avg: Math.round(prices.reduce((s, v) => s + v, 0) / prices.length),
        median: Math.round(sorted[Math.floor(sorted.length / 2)]),
        count: prices.length,
      };
    });
}

export function avgPriceByNeighborhood(sector: string, listings: Listing[] = ALL_LISTINGS) {
  const byDistrict = new Map<string, number[]>();
  for (const l of listings) {
    if (l.sector !== sector) continue;
    const p = eurPrice(l);
    if (p === null) continue;
    (byDistrict.get(l.district) ?? byDistrict.set(l.district, []).get(l.district)!).push(p);
  }
  return [...byDistrict.entries()]
    .map(([district, prices]) => ({
      district,
      avg: Math.round(prices.reduce((s, v) => s + v, 0) / prices.length),
      count: prices.length,
    }))
    .filter((d) => d.count >= 3)
    .sort((a, b) => a.avg - b.avg);
}

export function avgPriceByRooms(listings: Listing[] = ALL_LISTINGS) {
  const byRoom = new Map<RoomCount, number[]>();
  for (const l of listings) {
    const p = eurPrice(l);
    if (p === null) continue;
    (byRoom.get(l.rooms) ?? byRoom.set(l.rooms, []).get(l.rooms)!).push(p);
  }
  return ROOM_ORDER.filter((r) => byRoom.has(r)).map((rooms) => {
    const prices = byRoom.get(rooms)!.sort((a, b) => a - b);
    return {
      rooms,
      avg: Math.round(prices.reduce((s, v) => s + v, 0) / prices.length),
      min: prices[0],
      max: prices[prices.length - 1],
      count: prices.length,
    };
  });
}

export function roomsDistribution(listings: Listing[] = ALL_LISTINGS) {
  const counts = new Map<RoomCount, number>();
  for (const l of listings) counts.set(l.rooms, (counts.get(l.rooms) ?? 0) + 1);
  return ROOM_ORDER.map((rooms) => ({ rooms, count: counts.get(rooms) ?? 0 }));
}

export function platformBreakdown(listings: Listing[] = ALL_LISTINGS) {
  const counts = new Map<string, number>();
  for (const l of listings) counts.set(l.platform, (counts.get(l.platform) ?? 0) + 1);
  return [...counts.entries()].map(([platform, count]) => ({ name: platform, value: count }));
}

export function propertyTypeBreakdown(listings: Listing[] = ALL_LISTINGS) {
  const counts = new Map<PropertyType, number>();
  for (const l of listings) counts.set(l.property_type, (counts.get(l.property_type) ?? 0) + 1);
  return [...counts.entries()].map(([name, value]) => ({ name, value }));
}

export function priceVsArea(listings: Listing[] = ALL_LISTINGS) {
  return listings
    .filter((l) => l.area_sqm > 10 && l.area_sqm < 300 && eurPrice(l) !== null)
    .map((l) => ({ area: l.area_sqm, price: l.price_numeric, rooms: l.rooms }));
}
