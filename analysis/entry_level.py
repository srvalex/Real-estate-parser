"""
analysis/entry_level.py
─────────────────
The narrowed cut: 1-room vs 2-room rentals, Apartament + Garsoniera only.

Population, in the order the filters must be applied:

  1. property_type IS NOT NULL   — applied BEFORE reclassification. Under the
     `rooms = '1' -> Garsoniera` rule a NULL-typed 1-room listing would come
     out labelled "Garsoniera" despite the platform never having said what
     it is; that invents a category out of a missing value.
  2. reclassify: 1 room -> Garsoniera; "Garsoniera" with >1 room -> Apartament
  3. keep property_type_norm in {Apartament, Garsoniera}  — drops Casa/Vila
     and multi-room Studio
  4. keep rooms in {1, 2}

After step 2 the two labels are collinear with room count by construction
(every 1-room is a Garsoniera, every 2-room here is an Apartament), so this
is a clean studio-vs-two-room comparison and the property_type column
carries no extra information. That is the point of the cut, but it means
"Garsoniera rents less than Apartament" is a tautology, not a finding — the
findings have to come from the spread, the per-m² rate and the turnover.

Reads analysis/cache/ only. No network.
"""
import os

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_HERE, "cache")
RAW_CSV = os.path.join(CACHE_DIR, "listings_since_2026-08-01.csv")

MIN_EUR, MAX_EUR = 50, 10_000
MIN_SAMPLE = 30
AS_OF = "2026-09-08"   # pull date; listing age is measured from this
AGE_BANDS = ["1-7d", "8-14d", "15-21d", "22d+"]
KEEP_TYPES = ("Apartament", "Garsoniera")
SEGMENTS = ["1 cameră (garsonieră)", "2 camere (apartament)"]


def _save(df: pd.DataFrame, name: str) -> pd.DataFrame:
    df.to_csv(os.path.join(CACHE_DIR, f"{name}.csv"), index=False)
    return df


def _hdr(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def load() -> tuple[pd.DataFrame, list[str]]:
    df = pd.read_csv(RAW_CSV)
    trail = [f"all rows first_seen_at >= 2026-08-01: {len(df):,}"]

    df = df[df["property_type"].notna()]
    trail.append(f"property_type not null:              {len(df):,}")

    df = df[df["property_type_norm"].isin(KEEP_TYPES)]
    trail.append(f"Apartament / Garsoniera only:        {len(df):,}")

    df = df[df["rooms_norm"].isin(["1", "2"])]
    trail.append(f"1 or 2 rooms:                        {len(df):,}")

    df = df[df["price_eur"].between(MIN_EUR, MAX_EUR)]
    trail.append(f"priced within EUR{MIN_EUR}-{MAX_EUR}:            {len(df):,}")

    df = df.copy()
    df["segment"] = df["rooms_norm"].map({"1": SEGMENTS[0], "2": SEGMENTS[1]})
    return df, trail


def headline(df: pd.DataFrame) -> pd.DataFrame:
    out = (
        df.groupby(["city", "segment"])
        .agg(
            listings=("url", "nunique"),
            median_rent=("price_eur", "median"),
            p25=("price_eur", lambda s: s.quantile(0.25)),
            p75=("price_eur", lambda s: s.quantile(0.75)),
            median_sqm=("area_sqm", "median"),
            median_eur_per_sqm=("price_per_sqm", "median"),
        )
        .round(2)
        .reset_index()
    )
    return _save(out, "el_headline_by_city")


def second_room_premium(df: pd.DataFrame) -> pd.DataFrame:
    """What the second room costs, in € and %, and whether it is cheaper or
    dearer per square metre than the first."""
    rows = []
    for city, g in df.groupby("city"):
        one = g[g["rooms_norm"] == "1"]
        two = g[g["rooms_norm"] == "2"]
        if len(one) < MIN_SAMPLE or len(two) < MIN_SAMPLE:
            continue
        m1, m2 = one["price_eur"].median(), two["price_eur"].median()
        s1, s2 = one["price_per_sqm"].median(), two["price_per_sqm"].median()
        rows.append({
            "city": city,
            "n_1room": len(one), "n_2room": len(two),
            "median_1room": round(m1), "median_2room": round(m2),
            "premium_eur": round(m2 - m1),
            "premium_pct": round((m2 / m1 - 1) * 100, 1),
            "eur_sqm_1room": round(s1, 2), "eur_sqm_2room": round(s2, 2),
            "sqm_premium_pct": round((s1 / s2 - 1) * 100, 1),  # studio vs 2-room rate
        })
    return _save(pd.DataFrame(rows).sort_values("premium_pct", ascending=False), "el_second_room_premium")


def overlap(df: pd.DataFrame) -> pd.DataFrame:
    """How much the two price distributions overlap.

    The headline stat candidate: the share of 2-room flats asking less than
    the median studio. A big number says the segments are not really priced
    as separate tiers — location dominates room count.
    """
    rows = []
    for city, g in df.groupby("city"):
        one = g[g["rooms_norm"] == "1"]["price_eur"]
        two = g[g["rooms_norm"] == "2"]["price_eur"]
        if len(one) < MIN_SAMPLE or len(two) < MIN_SAMPLE:
            continue
        rows.append({
            "city": city,
            "median_1room": round(one.median()),
            "pct_2room_below_median_1room": round((two < one.median()).mean() * 100, 1),
            "median_2room": round(two.median()),
            "pct_1room_above_median_2room": round((one > two.median()).mean() * 100, 1),
        })
    return _save(pd.DataFrame(rows), "el_overlap")


def by_sector(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["city"].eq("Bucuresti") & df["sector"].notna() & df["sector"].ne("")]
    med = d.pivot_table(index="sector", columns="rooms_norm", values="price_eur", aggfunc="median")
    sqm = d.pivot_table(index="sector", columns="rooms_norm", values="price_per_sqm", aggfunc="median")
    cnt = d.pivot_table(index="sector", columns="rooms_norm", values="url", aggfunc="count")

    out = pd.DataFrame({
        "sector": med.index,
        "n_1room": cnt.get("1"), "n_2room": cnt.get("2"),
        "median_1room": med.get("1").round(0), "median_2room": med.get("2").round(0),
        "eur_sqm_1room": sqm.get("1").round(2), "eur_sqm_2room": sqm.get("2").round(2),
    }).reset_index(drop=True)
    out["premium_pct"] = ((out["median_2room"] / out["median_1room"] - 1) * 100).round(1)
    # Blank any cell backed by too few listings to quote.
    thin = (out["n_1room"] < MIN_SAMPLE) | (out["n_2room"] < MIN_SAMPLE)
    out.loc[thin, ["premium_pct"]] = None
    return _save(out.sort_values("eur_sqm_2room", ascending=False), "el_by_sector")


def supply_mix(df: pd.DataFrame) -> pd.DataFrame:
    """Which sectors are studio-heavy — a supply-side story rather than a
    price one, and the one least affected by the asking-price caveat."""
    d = df[df["city"].eq("Bucuresti") & df["sector"].notna() & df["sector"].ne("")]
    out = (
        d.groupby("sector")["rooms_norm"]
        .value_counts(normalize=True)
        .unstack()
        .mul(100)
        .round(1)
        .rename(columns={"1": "pct_1room", "2": "pct_2room"})
        .reset_index()
    )
    totals = d.groupby("sector")["url"].nunique().rename("listings").reset_index()
    return _save(out.merge(totals, on="sector").sort_values("pct_1room", ascending=False), "el_supply_mix")


def turnover(df: pd.DataFrame) -> pd.DataFrame:
    """Share already delisted, by segment and price band. Listing turnover,
    NOT confirmed lets — see the caveats in explore.py."""
    d = df[df["city"].eq("Bucuresti")].copy()
    d["band"] = pd.cut(
        d["price_eur"], bins=[0, 300, 400, 500, 650, 850, 10_000],
        labels=["<€300", "€300-400", "€400-500", "€500-650", "€650-850", "€850+"],
    )
    out = (
        d.groupby(["segment", "band"], observed=True)
        .agg(listings=("url", "nunique"), still_listed=("is_available", "mean"))
        .reset_index()
    )
    out["pct_gone"] = ((1 - out["still_listed"]) * 100).round(1)
    out = out.drop(columns="still_listed")
    out = out[out["listings"] >= MIN_SAMPLE]
    return _save(out, "el_turnover")


def _with_age(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    seen = pd.to_datetime(d["first_seen_at"], errors="coerce", utc=True)
    d["age_days"] = (pd.Timestamp(AS_OF, tz="UTC") - seen).dt.days
    d["age_band"] = pd.cut(d["age_days"], [-1, 7, 14, 21, 60],
                           labels=["0-7d", "8-14d", "15-21d", "22d+"])
    return d


def city_turnover_is_confounded(df: pd.DataFrame) -> pd.DataFrame:
    """Why the raw city turnover comparison must NOT be published.

    Cluj and Iași only entered the crawler around 24 Aug, so their listings
    have had a quarter as long to disappear as Bucharest's (median age 4
    days vs 16). Raw turnover therefore reads ~40-50% for Bucharest against
    ~9-15% for the others — almost entirely observation window, not market
    heat. Comparing within an age band shrinks the gap to a few points.
    """
    d = _with_age(df)
    out = d.pivot_table(index="age_band", columns="city", values="is_available",
                        aggfunc=lambda s: round((1 - s.mean()) * 100, 1), observed=True)
    return _save(out.reset_index(), "el_city_turnover_confound")


def turnover_controlled(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The key test: does the studio/2-room turnover gap survive controls?

    Against AGE it survives — studios clear roughly twice as fast in every
    age band. Against PRICE it vanishes: inside a single price band the two
    segments clear at the same rate. So the driver is the asking price, and
    room count is only a proxy for it (studios cluster in the cheap bands).
    Publishing "studios rent faster" would be reporting the confounder.
    """
    d = _with_age(df[df["city"].eq("Bucuresti")])
    d["seg"] = d["rooms_norm"].map({"1": "1-room", "2": "2-room"})

    by_age = d.pivot_table(index="age_band", columns="seg", values="is_available",
                           aggfunc=lambda s: round((1 - s.mean()) * 100, 1), observed=True)
    by_age["n_1room"] = d[d.seg.eq("1-room")].groupby("age_band", observed=True).size()
    by_age["n_2room"] = d[d.seg.eq("2-room")].groupby("age_band", observed=True).size()

    d["band"] = pd.cut(d["price_eur"], [0, 350, 450, 550, 700, 10_000],
                       labels=["<€350", "€350-450", "€450-550", "€550-700", "€700+"])
    by_price = d.pivot_table(index="band", columns="seg", values="is_available",
                             aggfunc=lambda s: round((1 - s.mean()) * 100, 1), observed=True)
    by_price["n_1room"] = d[d.seg.eq("1-room")].groupby("band", observed=True).size()
    by_price["n_2room"] = d[d.seg.eq("2-room")].groupby("band", observed=True).size()

    return (_save(by_age.reset_index(), "el_turnover_by_age"),
            _save(by_price.reset_index(), "el_turnover_by_price_controlled"))


def strict_population(df: pd.DataFrame) -> pd.DataFrame:
    """Garsonieră vs 2-room Apartament, using the platform's OWN label.

    Stricter than the rest of this module, which goes through
    property_type_norm and therefore sweeps Studio-, Apartament- and
    Casa/Vila-labelled 1-room listings into "Garsoniera". Here a listing
    counts only if the platform itself called it what we are counting it as:

        Garsonieră          = property_type "Garsoniera"  AND 1 room
        Apartament 2 camere = property_type "Apartament"   AND 2 rooms

    So no Studio rows survive in either bucket, and the two groups are
    genuine like-for-like typologies rather than a room-count relabelling.
    """
    d = df[df["price_eur"].between(MIN_EUR, MAX_EUR)].copy()
    is_gars = d["property_type"].eq("Garsoniera") & d["rooms_norm"].eq("1")
    is_apt2 = d["property_type"].eq("Apartament") & d["rooms_norm"].eq("2")
    d = d[is_gars | is_apt2]
    d["seg"] = d["property_type"].map({"Garsoniera": "Garsonieră",
                                       "Apartament": "Apartament 2 cam."})
    return d


def strict_turnover(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The age and price tables again, on the strict Garsonieră/2-room
    population, Bucharest only."""
    d = _with_age(strict_population(df))
    d = d[d["city"].eq("Bucuresti")]

    def _table(index_col):
        pct = d.pivot_table(index=index_col, columns="seg", values="is_available",
                            aggfunc=lambda s: round((1 - s.mean()) * 100, 1), observed=True)
        n = d.pivot_table(index=index_col, columns="seg", values="url",
                          aggfunc="count", observed=True)
        n.columns = [f"n_{c}" for c in n.columns]
        return pct.join(n).reset_index()

    d["band"] = pd.cut(d["price_eur"], [0, 350, 450, 550, 700, 10_000],
                       labels=["<€350", "€350-450", "€450-550", "€550-700", "€700+"])

    counts = (
        d.groupby("seg")
        .agg(listings=("url", "nunique"), median_rent=("price_eur", "median"),
             median_sqm=("area_sqm", "median"), pct_gone=("is_available",
                                                          lambda s: round((1 - s.mean()) * 100, 1)))
        .reset_index()
    )
    return (_save(counts, "el_strict_summary"),
            _save(_table("age_band"), "el_strict_turnover_by_age"),
            _save(_table("band"), "el_strict_turnover_by_price"))


def age_cohort_pivot(df: pd.DataFrame) -> pd.DataFrame:
    """Age-band pivot with the SEGMENT population as the denominator.

    Two different questions get confused here, so both columns are reported:

      pct_of_segment — gone in this band / ALL listings of that segment.
                       Decomposes the segment's total loss across bands, so
                       this column SUMS to the segment's overall % gone.
      pct_of_band    — gone in this band / listings in that band. A per-cohort
                       survival rate; does not sum to anything meaningful.

    The age bands are disjoint cohorts — a listing sits in exactly one. They
    are not cumulative. The rate still climbs with age simply because an
    older listing has had longer to disappear.

    Age is clipped at a minimum of 1 day: a handful of rows carry a
    first_seen_at a few hours in the future (timezone rounding at the crawl
    boundary), which would otherwise land in a negative-age band.
    """
    d = strict_population(df)
    d = d[d["city"].eq("Bucuresti")].copy()

    seen = pd.to_datetime(d["first_seen_at"], errors="coerce", utc=True)
    d["age_days"] = ((pd.Timestamp(AS_OF, tz="UTC") - seen).dt.days).clip(lower=1)
    d["age_band"] = pd.cut(d["age_days"], [0, 7, 14, 21, 10_000], labels=AGE_BANDS)
    d["gone"] = d["is_available"].eq(0)

    totals = d.groupby("seg")["url"].count()
    rows = []
    for (band, seg), g in d.groupby(["age_band", "seg"], observed=True):
        rows.append({
            "age_band": band,
            "segment": seg,
            "listings_in_band": len(g),
            "gone_in_band": int(g["gone"].sum()),
            "pct_of_segment": round(g["gone"].sum() / totals[seg] * 100, 1),
            "pct_of_band": round(g["gone"].mean() * 100, 1),
            "avg_rent": round(g["price_eur"].mean()),
            "median_rent": round(g["price_eur"].median()),
        })
    out = pd.DataFrame(rows)
    # Rebuild the ordered categorical: constructing the frame from dicts
    # drops it, and a plain string index sorts "22d+" before "8-14d".
    out["age_band"] = pd.Categorical(out["age_band"], categories=AGE_BANDS, ordered=True)
    out = out.sort_values(["age_band", "segment"])
    return _save(out, "el_age_cohort_pivot")


def age_cohort_wide(long: pd.DataFrame) -> pd.DataFrame:
    """The same table laid out as the requested pivot: age bands down,
    segments across."""
    wide = long.pivot(index="age_band", columns="segment",
                      values=["pct_of_segment", "avg_rent"])
    wide.columns = [f"{seg} · {'% of all' if m == 'pct_of_segment' else 'avg rent'}"
                    for m, seg in wide.columns]
    return _save(wide.reset_index(), "el_age_cohort_wide")


def segment_turnover(df: pd.DataFrame) -> pd.DataFrame:
    out = (
        df.groupby(["city", "segment"])
        .agg(listings=("url", "nunique"), still_listed=("is_available", "mean"))
        .reset_index()
    )
    out["pct_gone"] = ((1 - out["still_listed"]) * 100).round(1)
    return _save(out.drop(columns="still_listed"), "el_segment_turnover")


def main() -> None:
    pd.set_option("display.width", 150)
    df, trail = load()

    _hdr("0 · Population — what each filter removed")
    for line in trail:
        print("  " + line)
    print(f"\n  segments: {df['segment'].value_counts().to_dict()}")
    print(f"  cities  : {df['city'].value_counts().to_dict()}")

    _hdr("1 · Headline by city and segment")
    print(headline(df).to_string(index=False))

    _hdr("2 · What the second room costs")
    print(second_room_premium(df).to_string(index=False))

    _hdr("3 · Distribution overlap")
    print(overlap(df).to_string(index=False))

    _hdr("4 · Bucharest by sector")
    print(by_sector(df).to_string(index=False))

    _hdr("5 · Supply mix — share of entry-level stock that is a studio")
    print(supply_mix(df).to_string(index=False))

    _hdr("6 · Turnover by segment")
    print(segment_turnover(df).to_string(index=False))

    _hdr("7 · Turnover by segment × price band (Bucharest)")
    print(turnover(df).to_string(index=False))

    _hdr("8 · CONTROL — is the city turnover gap real? (pct gone, by listing age)")
    print(city_turnover_is_confounded(df).to_string(index=False))
    print("\n  -> Cluj/Iasi entered the crawler ~24 Aug. Raw city turnover compares")
    print("     observation windows, not markets. Do not publish the raw version.")

    _hdr("9 · CONTROL — does the studio turnover gap survive? (Bucharest, pct gone)")
    by_age, by_price = turnover_controlled(df)
    print("Controlling for listing AGE — gap SURVIVES:")
    print(by_age.to_string(index=False))
    print("\nControlling for PRICE BAND — gap DISAPPEARS:")
    print(by_price.to_string(index=False))
    print("\n  -> Price is the driver. Room count is a proxy for price, not an")
    print("     independent cause. (The EUR700+ studio cell is n=40 — ignore it.)")

    _hdr("10 · STRICT — Garsoniera vs 2-room Apartament (platform label, no Studio)")
    summary, by_age, by_price = strict_turnover(df)
    print(summary.to_string(index=False))
    print("\nBy listing age (pct gone):")
    print(by_age.to_string(index=False))
    print("\nBy asking price (pct gone):")
    print(by_price.to_string(index=False))

    _hdr("11 · AGE COHORT PIVOT — denominator = the whole segment")
    long = age_cohort_pivot(df)
    print(age_cohort_wide(long).to_string(index=False))
    print("\nFull detail (both denominators side by side):")
    print(long.to_string(index=False))
    tot = long.groupby("segment")["pct_of_segment"].sum().round(1)
    print("\nColumn check — '% of all' sums to the segment's overall % gone:")
    print(tot.to_string())

    print(f"\nTables written to {CACHE_DIR}/el_*.csv")


if __name__ == "__main__":
    main()
