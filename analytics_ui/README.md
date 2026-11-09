# analytics_ui — internal market dashboard

The rental-market analytics dashboard. **Internal only** — it is a separate
app from `mock_ui/` (the renter-facing search UI) on purpose.

## Why it's separate

The aggregate market picture — rent by sector, supply per day, platform mix
— is the asset this project accumulates, and `MONETIZATION_PLAN.md` expects
to sell it. Renters looking for a flat have no need for it, so it should not
be reachable from the surface they use.

Keeping it separate means the isolation is structural rather than a
conditional someone can delete by accident:

| | `mock_ui` (public) | `analytics_ui` (internal) |
|---|---|---|
| Port | 3000 | 3100 |
| Backend | `api/main.py` (:8000) | `api/analytics_app.py` (:8100) |
| Auth | none | `X-Analytics-Token` |
| Returns | individual listings | aggregates only |

The public API has no `/analytics` route and the analytics API has no
`/listings` route. `tests/api/test_analytics_app.py::IsolationFromPublicApiTests`
asserts both, so merging the two apps fails a test instead of silently
exposing the market data.

## Where the token lives

`ANALYTICS_API_TOKEN` is a plain (non-`NEXT_PUBLIC_`) env var, read only in
the Next server process by `lib/server/analyticsClient.ts`. The browser
calls this app's own `/api/summary` and `/api/cities` route handlers, which
attach the header server-side. **Do not** rename it to `NEXT_PUBLIC_*` and
fetch `:8100` from the browser — that ships the credential to every visitor
and undoes the reason the service is guarded at all.

## Running it

Both processes are needed. From the repo root:

```bash
ANALYTICS_API_TOKEN=local-dev-analytics-token venv/bin/uvicorn api.analytics_app:app --reload --port 8100
```

```bash
npm --prefix analytics_ui run dev
```

Then open <http://localhost:3100>. Copy `.env.example` to `.env.local` and
set `ANALYTICS_API_TOKEN` to the same value the service was started with —
they must match or every request comes back 401.

Both are also registered in `.claude/launch.json` as `analytics_api` and
`analytics_ui`.

## Data flow

`listings` (Supabase, anon key + RLS)
→ `db_utils.fetch_analytics_data(city=…)`
→ `api/analytics.py` (reduces rows to statistics; RON→EUR at the live BNR
rate, same conversion the search pipeline uses)
→ `api/analytics_app.py` (token check, 15-minute cache, `GET /analytics/summary`)
→ this app's `/api/summary` proxy
→ the dashboard.

## Filters

The header carries two filter boxes — **city** and **room count** — and both
are applied server-side, because the dashboard only ever receives
aggregates and so has no rows of its own to filter.

`GET /analytics/summary?city=Bucuresti&rooms=2` (`rooms` takes a
comma-separated list, e.g. `rooms=1,3`; valid values are `1 2 3 4 5+`, and
anything else is a 422). The filter matches the *normalised* room count, so
`5+` collects every flat with five rooms or more, and a raw `"2 camere"` in
the DB matches `rooms=2`.

Room filtering happens after the DB read rather than in SQL: `rooms` is
free text in the table (`"2 camere"`, `"2"`), so a WHERE clause could not
match it reliably, and filtering in Python lets one cached read serve every
room selection for a city. The summary cache is keyed on `(city, rooms)` —
keyed on city alone it would hand a 2-room summary to the next caller
asking for the whole city.

While a room filter is active the two rooms-native charts ("Camere" and
"Chirie medie pe număr de camere") are omitted from the response and hidden
by the dashboard: narrowed to a single room count they collapse into one bar
restating the filter.

Nothing in that chain hands a listing to the browser. The summary is
computed over the whole table, so it is cached server-side for
`ANALYTICS_CACHE_TTL` seconds (default 900); the dashboard's **Reîmprospătează**
button passes `refresh=true` to bypass it.
