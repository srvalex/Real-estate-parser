"""
api/analytics.py
─────────────────
Market-analytics aggregation — the numbers behind the internal market
dashboard (analytics_ui/), computed from real `listings` rows.

Pure functions over a list[dict] of DB rows, deliberately free of any
FastAPI/Supabase import so they can be unit-tested without a network or an
app fixture (tests/api/test_analytics.py). api/analytics_app.py is the only
thing that wires them to db_utils.fetch_analytics_data().

Nothing here ever returns a listing: every function reduces rows to counts,
means, medians and buckets. That's the whole point of the split — the
public API (api/main.py) hands out individual listings and no aggregates,
this service hands out aggregates and no listings, so the market picture
we're building can't be reconstructed row-by-row through the dashboard.

Prices are normalised to EUR with db_utils.price_in_eur (live BNR rate,
same conversion the search pipeline uses) by the caller — see
`prepare_rows`. Rows outside _MIN_EUR.._MAX_EUR are excluded from every
price statistic but still counted in `total`, matching the Streamlit
dashboard's _eur_df().
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any, Callable, Iterable, Optional

# Monthly rent sanity bounds, in EUR. Below the floor is almost always a
# mis-parsed price (a per-night or per-day figure, or a deposit); above the
# ceiling is a sale price that leaked into the rentals table. Both would
# drag every mean in the dashboard.
_MIN_EUR = 50.0
_MAX_EUR = 10_000.0

# Area bounds for the price-vs-area scatter, in m².
_MIN_SQM = 10.0
_MAX_SQM = 300.0

# Mirrors _normalise_rooms exactly: 5 and above collapse into "5+", so a
# bare "5" bucket would render as a permanent empty bar in the dashboard.
ROOM_ORDER = ["1", "2", "3", "4", "5+"]

# A neighbourhood with a handful of listings produces a headline average
# that swings by hundreds of euros when one listing expires. Suppress those
# rather than publish a number the dashboard can't stand behind.
_MIN_NEIGHBOURHOOD_SAMPLE = 3


def _num(value: Any) -> Optional[float]:
    """float(value) or None — never raises on the junk that reaches us from
    scraped rows (empty strings, None, stray text)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result  # NaN


def _normalise_rooms(value: Any) -> str:
    """'2 camere' -> '2', 5 or more -> '5+', anything unparseable -> '?'."""
    if value is None:
        return "?"
    digits = "".join(c for c in str(value) if c.isdigit())
    if not digits:
        return "?"
    count = int(digits[:2])
    if count <= 0:
        return "?"
    return str(count) if count < 5 else "5+"


def prepare_rows(
    rows: Iterable[dict],
    price_in_eur: Callable[[Any, Any], Optional[float]],
    sector_for: Callable[[str, str], str],
    city_has_sectors: Optional[Callable[[str], bool]] = None,
) -> list[dict]:
    """Normalise raw DB rows once, so every aggregate below reads the same
    fields. `price_in_eur`, `sector_for` and `city_has_sectors` are injected
    rather than imported so tests don't need Supabase or a cities.json read.

    Adds: price_eur (None when absent/out of bounds), area, rooms, sector,
    sectored_city (whether this row's city has a sector layer at all).
    """
    prepared: list[dict] = []
    for row in rows:
        price = price_in_eur(row.get("price_numeric"), row.get("price_currency"))
        if price is not None and not (_MIN_EUR < price < _MAX_EUR):
            price = None
        city = row.get("city") or ""
        district = row.get("district") or ""
        prepared.append({
            **row,
            "price_eur": price,
            "area": _num(row.get("area_sqm")),
            "rooms": _normalise_rooms(row.get("rooms")),
            "district": district,
            "sector": sector_for(city, district) if district else "",
            "sectored_city": city_has_sectors(city) if city_has_sectors else True,
        })
    return prepared


def sector_coverage(rows: list[dict]) -> dict:
    """How much of the priced supply the sector charts actually account for.

    The sector breakdown silently omits any listing whose district doesn't
    resolve to a sector — a blank district from the crawler, or an Ilfov
    satellite town (Voluntari, Popești Leordeni) that is scraped as
    Bucharest but has no sector. Confirmed live 2026-09-08 that this was
    1,292 of 10,783 priced Bucharest listings (12%), so a chart totalling
    9,491 was quietly standing in for a city of 10,783.

    Reporting the gap is the honest fix: the charts stay restricted to rows
    that genuinely have a sector, and the dashboard says how many it left
    out. Only rows in cities that HAVE sectors are counted as missing —
    Cluj and Iași aren't a gap, they're a different geography.
    """
    priced = [r for r in rows if r.get("price_eur") is not None and r.get("sectored_city")]
    attributed = [r for r in priced if r.get("sector")]
    return {
        "attributed": len(attributed),
        "missing": len(priced) - len(attributed),
        "eligible": len(priced),
    }


def _prices(rows: Iterable[dict]) -> list[float]:
    return [r["price_eur"] for r in rows if r.get("price_eur") is not None]


def compute_kpis(rows: list[dict]) -> dict:
    prices = _prices(rows)
    areas = [r["area"] for r in rows if r.get("area") is not None]
    total = len(rows)
    return {
        "total": total,
        "with_price": len(prices),
        "with_price_pct": round(len(prices) / total * 100, 1) if total else 0.0,
        "avg_price": round(statistics.fmean(prices)) if prices else 0,
        "median_price": round(statistics.median(prices)) if prices else 0,
        "avg_area": round(statistics.fmean(areas)) if areas else 0,
    }


def daily_listings(rows: list[dict]) -> list[dict]:
    """New listings per calendar day, by first_seen_at (falling back to
    scraped_at). Timestamps arrive as ISO strings from Supabase; the day is
    the leading 10 chars, so no parsing — and no timezone library — is
    needed just to bucket them."""
    counts: Counter[str] = Counter()
    for row in rows:
        stamp = row.get("first_seen_at") or row.get("scraped_at")
        if not stamp:
            continue
        day = str(stamp)[:10]
        if len(day) == 10:
            counts[day] += 1
    return [{"day": day, "count": counts[day]} for day in sorted(counts)]


def price_histogram(rows: list[dict], bucket_size: int = 100) -> list[dict]:
    """Every bucket between the cheapest and priciest listing, including
    empty ones — skipping them would render as a continuous bar chart with
    no visible gaps, silently compressing the x-axis."""
    prices = _prices(rows)
    if not prices:
        return []
    lo = int(min(prices) // bucket_size) * bucket_size
    hi = int(max(prices) // bucket_size) * bucket_size
    counts: Counter[int] = Counter(int(p // bucket_size) * bucket_size for p in prices)
    return [
        {"bucket": bucket, "label": f"€{bucket}", "count": counts.get(bucket, 0)}
        for bucket in range(lo, hi + bucket_size, bucket_size)
    ]


def _grouped_prices(rows: list[dict], key: str) -> dict[str, list[float]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        price = row.get("price_eur")
        value = row.get(key)
        if price is None or not value:
            continue
        groups[str(value)].append(price)
    return groups


def avg_price_by_sector(rows: list[dict]) -> list[dict]:
    groups = _grouped_prices(rows, "sector")
    return [
        {
            "sector": sector,
            "label": sector.replace("Sector ", "S"),
            "avg": round(statistics.fmean(prices)),
            "median": round(statistics.median(prices)),
            "count": len(prices),
        }
        for sector, prices in sorted(groups.items())
    ]


def avg_price_by_neighbourhood(rows: list[dict], sector: str) -> list[dict]:
    groups = _grouped_prices([r for r in rows if r.get("sector") == sector], "district")
    result = [
        {
            "district": district,
            "avg": round(statistics.fmean(prices)),
            "median": round(statistics.median(prices)),
            "count": len(prices),
        }
        for district, prices in groups.items()
        if len(prices) >= _MIN_NEIGHBOURHOOD_SAMPLE
    ]
    return sorted(result, key=lambda d: d["avg"])


def avg_price_by_rooms(rows: list[dict]) -> list[dict]:
    groups = _grouped_prices(rows, "rooms")
    return [
        {
            "rooms": rooms,
            "avg": round(statistics.fmean(groups[rooms])),
            "median": round(statistics.median(groups[rooms])),
            "min": round(min(groups[rooms])),
            "max": round(max(groups[rooms])),
            "count": len(groups[rooms]),
        }
        for rooms in ROOM_ORDER
        if rooms in groups
    ]


def rooms_distribution(rows: list[dict]) -> list[dict]:
    counts = Counter(r["rooms"] for r in rows)
    return [{"rooms": rooms, "count": counts.get(rooms, 0)} for rooms in ROOM_ORDER]


def _breakdown(rows: list[dict], key: str) -> list[dict]:
    counts = Counter(str(r.get(key)) for r in rows if r.get(key))
    return [{"name": name, "value": value} for name, value in counts.most_common()]


def platform_breakdown(rows: list[dict]) -> list[dict]:
    return _breakdown(rows, "platform_id")


def property_type_breakdown(rows: list[dict]) -> list[dict]:
    return _breakdown(rows, "property_type")


def price_vs_area(rows: list[dict], limit: int = 2000) -> list[dict]:
    """Scatter points, capped so the payload (and the browser) stay small.

    The cap takes an even stride through the price-sorted rows rather than a
    random sample, so the shape of the cloud — and the extremes at both ends
    — survive the downsample, and so the same dataset always yields the same
    chart (a random sample would make the scatter jitter on every refresh).
    """
    points = [
        {"area": r["area"], "price": round(r["price_eur"]), "rooms": r["rooms"]}
        for r in rows
        if r.get("price_eur") is not None
        and r.get("area") is not None
        and _MIN_SQM < r["area"] < _MAX_SQM
    ]
    if len(points) <= limit:
        return points
    points.sort(key=lambda p: (p["price"], p["area"]))
    stride = len(points) / limit
    return [points[int(i * stride)] for i in range(limit)]


def filter_by_rooms(rows: list[dict], rooms: Optional[Iterable[str]]) -> list[dict]:
    """Narrow to the given room counts. None/empty means no filtering — an
    empty selection is "everything", never "nothing", so a cleared filter
    can't blank the whole dashboard.

    Matches against the normalised `rooms` field from prepare_rows, so the
    caller passes "5+" rather than having to know that 5, 6 and 7 all fold
    into it.
    """
    if not rooms:
        return rows
    wanted = set(rooms)
    return [r for r in rows if r.get("rooms") in wanted]


def build_summary(rows: list[dict], rooms_filtered: bool = False) -> dict:
    """Everything the dashboard renders, in one response — the charts are
    all views of the same row set, so a per-chart endpoint would mean N
    full-table reads per page load instead of one.

    `rooms_filtered` says a room-count filter is active. The two
    rooms-native breakdowns are then omitted rather than returned: filtered
    to one room count they collapse to a single bar restating the filter,
    which is not an answer to anything. The dashboard hides those cards when
    the key is absent.
    """
    sectors = avg_price_by_sector(rows)
    summary = {
        "kpis": compute_kpis(rows),
        "sector_coverage": sector_coverage(rows),
        "daily_listings": daily_listings(rows),
        "price_histogram": price_histogram(rows),
        "by_sector": sectors,
        "by_neighbourhood": {
            entry["sector"]: avg_price_by_neighbourhood(rows, entry["sector"])
            for entry in sectors
        },
        "by_rooms": [] if rooms_filtered else avg_price_by_rooms(rows),
        "rooms_distribution": [] if rooms_filtered else rooms_distribution(rows),
        "platforms": platform_breakdown(rows),
        "property_types": property_type_breakdown(rows),
        "price_vs_area": price_vs_area(rows),
    }
    return summary
