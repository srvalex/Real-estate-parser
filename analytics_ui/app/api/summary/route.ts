import { NextResponse } from "next/server";
import { AnalyticsApiError, fetchFromAnalyticsApi } from "@/lib/server/analyticsClient";
import type { AnalyticsSummary } from "@/lib/types";

// Forces a per-request run — without it Next would try to statically
// evaluate this route at build time, when the analytics service isn't up.
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const incoming = new URL(request.url).searchParams;
  // Rebuilt rather than forwarded wholesale: only these params mean
  // anything to the analytics service, and passing arbitrary query strings
  // straight through to an internal service is how a proxy turns into an
  // open one. The service validates `rooms` itself and 422s on anything
  // outside its known set, so this stays a pass-through, not a second
  // place the valid values have to be listed.
  const params = new URLSearchParams();
  const city = incoming.get("city");
  if (city) params.set("city", city);
  const rooms = incoming.get("rooms");
  if (rooms) params.set("rooms", rooms);
  if (incoming.get("refresh") === "true") params.set("refresh", "true");

  const query = params.toString();
  try {
    const summary = await fetchFromAnalyticsApi<AnalyticsSummary>(
      `/analytics/summary${query ? `?${query}` : ""}`,
    );
    return NextResponse.json(summary);
  } catch (err) {
    const status = err instanceof AnalyticsApiError ? err.status : 500;
    return NextResponse.json({ error: (err as Error).message }, { status });
  }
}
