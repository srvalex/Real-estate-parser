import { NextResponse } from "next/server";
import { AnalyticsApiError, fetchFromAnalyticsApi } from "@/lib/server/analyticsClient";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const cities = await fetchFromAnalyticsApi<{ cities: string[] }>("/analytics/cities");
    return NextResponse.json(cities);
  } catch (err) {
    const status = err instanceof AnalyticsApiError ? err.status : 500;
    return NextResponse.json({ error: (err as Error).message }, { status });
  }
}
