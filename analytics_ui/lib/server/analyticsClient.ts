// Server-only client for the internal analytics API (api/analytics_app.py).
//
// It lives under lib/server/ and is imported exclusively by the route
// handlers in app/api/. That is the whole point: ANALYTICS_API_TOKEN is a
// plain (non-NEXT_PUBLIC_) env var, so it is read in the Node process and
// never inlined into the client bundle. The browser talks to this app's own
// /api/* routes; only this app's server talks to the analytics service.
//
// Putting the token behind NEXT_PUBLIC_ and fetching the service directly
// from the browser would have shipped the credential to every visitor —
// which would undo the reason the analytics service is a separate,
// token-guarded process in the first place.
import "server-only";

const ANALYTICS_API_BASE_URL = process.env.ANALYTICS_API_BASE_URL ?? "http://localhost:8100";

export class AnalyticsApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "AnalyticsApiError";
  }
}

export async function fetchFromAnalyticsApi<T>(path: string): Promise<T> {
  const token = process.env.ANALYTICS_API_TOKEN;
  if (!token) {
    throw new AnalyticsApiError(
      "ANALYTICS_API_TOKEN is not set — copy .env.example to .env.local and fill it in.",
      500,
    );
  }

  let res: Response;
  try {
    res = await fetch(`${ANALYTICS_API_BASE_URL}${path}`, {
      headers: { "X-Analytics-Token": token },
      // The analytics service caches server-side already; caching again in
      // Next's data layer would make the dashboard's Refresh button lie.
      cache: "no-store",
    });
  } catch {
    throw new AnalyticsApiError(
      `Analytics service unreachable at ${ANALYTICS_API_BASE_URL}. Is it running? ` +
        `(uvicorn api.analytics_app:app --port 8100)`,
      503,
    );
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new AnalyticsApiError(
      `Analytics API returned ${res.status}${detail ? `: ${detail}` : ""}`,
      res.status,
    );
  }
  return res.json() as Promise<T>;
}
