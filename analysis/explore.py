"""
analysis/explore.py
─────────────────
Exploratory cuts over the cached pull (analysis/fetch_cache.py), aimed at
finding one or two defensible claims for a LinkedIn post.

Reads only the cache — no network — so it is cheap to re-run and re-cut.
Every table it prints is also written to analysis/cache/*.csv.

Two conventions, applied throughout:

* **Median, not mean.** Rental price distributions are heavily right-skewed
  (a handful of €9k listings sit in the same table as €300 rooms), so the
  mean overstates the typical rent by a wide margin. Both are reported side
  by side once, in `outlier_sensitivity`, to show the size of the gap.
* **Sanity bounds.** €50–€10,000/month, the same window the dashboard uses.
  Below it is almost always a per-night rate or a deposit; above it is a
  sale price that leaked into the rentals table.

Nothing here is safe to publish without reading the caveats printed at the
end — particularly `is_available = 0`, which is NOT confirmed "rented".
"""
import os

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_HERE, "cache")
RAW_CSV = os.path.join(CACHE_DIR, "listings_since_2026-08-01.csv")

MIN_EUR, MAX_EUR = 50, 10_000
MIN_SAMPLE = 30          # below this a median is too jumpy to quote publicly
ROOM_ORDER = ["1", "2", "3", "4", "5+"]


def _save(df: pd.DataFrame, name: str) -> pd.DataFrame:
    path = os.path.join(CACHE_DIR, f"{name}.csv")
    df.to_csv(path, index=False)
    return df


def _hdr(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def load() -> pd.DataFrame:
    df = pd.read_csv(RAW_CSV)
    df["priced"] = df["price_eur"].between(MIN_EUR, MAX_EUR)
    return df


def query_equivalent(df: pd.DataFrame) -> pd.DataFrame:
    """The grouped table from the SQL under discussion, for reference."""
    out = (
        df.groupby(["is_available", "city", "property_type_norm", "rooms_norm"], dropna=False)
        .agg(no_listings=("url", "nunique"), avg_price=("price_eur", "mean"))
        .round({"avg_price": 0})
        .reset_index()
        .sort_values(["is_available", "city", "property_type_norm", "rooms_norm"])
    )
    return _save(out, "agg_query_equivalent")


def outlier_sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    """How much the unbounded mean differs from the bounded median — the
    single most important thing to settle before quoting a number publicly."""
    rows = []
    for city, g in df[df["price_eur"].notna()].groupby("city"):
        bounded = g[g["priced"]]
        rows.append({
            "city": city,
            "n_priced": len(g),
            "n_within_bounds": len(bounded),
            "raw_mean": round(g["price_eur"].mean()),
            "bounded_mean": round(bounded["price_eur"].mean()),
            "bounded_median": round(bounded["price_eur"].median()),
            "max_price": round(g["price_eur"].max()),
        })
    return _save(pd.DataFrame(rows).sort_values("n_priced", ascending=False), "outlier_sensitivity")


def city_comparison(df: pd.DataFrame) -> pd.DataFrame:
    """Bucharest vs the second cities — on rent AND on €/m², which is the
    comparison that actually controls for flat size."""
    d = df[df["priced"]]
    out = (
        d.groupby("city")
        .agg(
            listings=("url", "nunique"),
            median_rent=("price_eur", "median"),
            median_sqm=("area_sqm", "median"),
            median_eur_per_sqm=("price_per_sqm", "median"),
        )
        .round(2)
        .reset_index()
        .sort_values("median_eur_per_sqm", ascending=False)
    )
    return _save(out, "city_comparison")


def bucharest_sectors(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["priced"] & df["city"].eq("Bucuresti") & df["sector"].notna() & df["sector"].ne("")]
    out = (
        d.groupby("sector")
        .agg(
            listings=("url", "nunique"),
            median_rent=("price_eur", "median"),
            mean_rent=("price_eur", "mean"),
            median_sqm=("area_sqm", "median"),
            median_eur_per_sqm=("price_per_sqm", "median"),
        )
        .round(2)
        .reset_index()
        .sort_values("median_eur_per_sqm", ascending=False)
    )
    return _save(out, "bucharest_sectors")


def sector_by_rooms(df: pd.DataFrame) -> pd.DataFrame:
    """Median rent per sector for a fixed room count — the like-for-like
    comparison. A sector's headline average mostly reflects what SIZE of
    flat is listed there, not what it costs to live there."""
    d = df[df["priced"] & df["city"].eq("Bucuresti") & df["sector"].ne("") & df["sector"].notna()]
    piv = (
        d.pivot_table(index="sector", columns="rooms_norm", values="price_eur", aggfunc="median")
        .reindex(columns=[r for r in ROOM_ORDER])
        .round(0)
    )
    counts = d.pivot_table(index="sector", columns="rooms_norm", values="url", aggfunc="count")
    piv = piv.where(counts.reindex(columns=piv.columns) >= MIN_SAMPLE)  # suppress thin cells
    return _save(piv.reset_index(), "sector_by_rooms_median")


def rooms_curve(df: pd.DataFrame) -> pd.DataFrame:
    """What each extra room actually costs, and whether €/m² falls with
    size (it usually does — small flats carry a premium per square metre)."""
    d = df[df["priced"] & df["city"].eq("Bucuresti")]
    out = (
        d.groupby("rooms_norm")
        .agg(
            listings=("url", "nunique"),
            median_rent=("price_eur", "median"),
            median_sqm=("area_sqm", "median"),
            median_eur_per_sqm=("price_per_sqm", "median"),
        )
        .reindex(ROOM_ORDER)
        .round(2)
        .reset_index()
    )
    out["step_vs_prev"] = out["median_rent"].diff()
    return _save(out, "rooms_curve")


def turnover(df: pd.DataFrame) -> pd.DataFrame:
    """Share of listings first seen since 1 Aug that are already gone.

    A proxy for how fast supply clears — NOT a confirmed let. See caveats.
    """
    d = df[df["priced"] & df["city"].eq("Bucuresti") & df["sector"].ne("") & df["sector"].notna()]
    out = (
        d.groupby("sector")
        .agg(listings=("url", "nunique"), still_listed=("is_available", "mean"),
             median_rent=("price_eur", "median"))
        .reset_index()
    )
    out["pct_gone"] = ((1 - out["still_listed"]) * 100).round(1)
    out = out.drop(columns="still_listed").sort_values("pct_gone", ascending=False)
    return _save(out.round(2), "turnover_by_sector")


def price_band_turnover(df: pd.DataFrame) -> pd.DataFrame:
    """The same clearing rate, cut by price band instead of geography."""
    d = df[df["priced"] & df["city"].eq("Bucuresti")].copy()
    d["band"] = pd.cut(
        d["price_eur"],
        bins=[0, 300, 450, 600, 800, 1200, 10_000],
        labels=["<€300", "€300-450", "€450-600", "€600-800", "€800-1200", "€1200+"],
    )
    out = (
        d.groupby("band", observed=True)
        .agg(listings=("url", "nunique"), still_listed=("is_available", "mean"))
        .reset_index()
    )
    out["pct_gone"] = ((1 - out["still_listed"]) * 100).round(1)
    return _save(out.drop(columns="still_listed"), "turnover_by_price_band")


def reclassification(df: pd.DataFrame) -> pd.DataFrame:
    """What the property_type override actually changed — worth knowing
    before leaning on platform labels in a public claim."""
    moved = df[df["property_type"] != df["property_type_norm"]]
    out = (
        moved.groupby(["property_type", "property_type_norm", "rooms_norm"])
        .agg(listings=("url", "nunique"))
        .reset_index()
        .sort_values("listings", ascending=False)
    )
    return _save(out, "reclassification_impact")


def main() -> None:
    df = load()
    pd.set_option("display.width", 140)

    _hdr("0 · Dataset")
    print(f"rows: {len(df):,}   first_seen_at >= 2026-08-01   pulled 2026-09-08")
    print(f"priced & within €{MIN_EUR}-{MAX_EUR}: {df['priced'].sum():,}")
    print(f"available: {(df['is_available'] == 1).sum():,}   expired: {(df['is_available'] == 0).sum():,}")

    _hdr("1 · Mean vs median — why the headline number matters")
    print(outlier_sensitivity(df).to_string(index=False))

    _hdr("2 · City comparison (median, bounded)")
    print(city_comparison(df).to_string(index=False))

    _hdr("3 · Bucharest by sector")
    print(bucharest_sectors(df).to_string(index=False))

    _hdr("4 · Bucharest: median rent by sector × rooms (cells with <30 listings blanked)")
    print(sector_by_rooms(df).to_string(index=False))

    _hdr("5 · What an extra room costs (Bucharest)")
    print(rooms_curve(df).to_string(index=False))

    _hdr("6 · Share already delisted, by sector")
    print(turnover(df).to_string(index=False))

    _hdr("7 · Share already delisted, by price band")
    print(price_band_turnover(df).to_string(index=False))

    _hdr("8 · property_type reclassification impact")
    print(reclassification(df).to_string(index=False))

    _hdr("CAVEATS — read before publishing any of this")
    print("""
1. is_available = 0 means "the listing is gone", NOT "the flat was rented".
   It also covers delisted, expired-and-relisted, and agency churn. Any
   claim about "how fast flats rent" is a proxy, and should be worded as
   listing turnover, not tenancy.
2. Cross-platform duplicates are NOT deduplicated (Roadmap.md 5.1). The same
   flat on OLX + Storia counts twice, and agency stock is over-represented
   because agencies multi-post. Counts are listings, not distinct homes.
3. Asking prices, not achieved rents. No negotiation, no signed-lease data.
4. One month of data (from 1 Aug) — no seasonality control. September is
   peak student season in Cluj and Iasi especially.
5. Coverage is three cities and three portals, weighted heavily to Storia.
   This is not the Romanian market; it is these portals' Bucharest-heavy mix.
6. RON->EUR pinned at 5.2508 (BNR, 2026-09-08). ~9% of rows are RON-priced,
   so the conversion is not a rounding detail.
""".strip())

    print(f"\nAll tables written to {CACHE_DIR}/")


if __name__ == "__main__":
    main()
