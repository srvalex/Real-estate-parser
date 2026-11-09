// Browser-side client. It only ever calls this app's own /api/* route
// handlers — never the analytics service directly, which would need the
// token in the bundle. See lib/server/analyticsClient.ts.
import type { AnalyticsSummary } from "./types";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}) as { error?: string });
    throw new Error(body.error ?? `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export function fetchSummary(
  city: string | null,
  rooms: string[],
  refresh = false,
): Promise<AnalyticsSummary> {
  const params = new URLSearchParams();
  if (city) params.set("city", city);
  if (rooms.length > 0) params.set("rooms", rooms.join(","));
  if (refresh) params.set("refresh", "true");
  const query = params.toString();
  return getJson<AnalyticsSummary>(`/api/summary${query ? `?${query}` : ""}`);
}

export function fetchCities(): Promise<{ cities: string[] }> {
  return getJson<{ cities: string[] }>("/api/cities");
}
