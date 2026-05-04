import json
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sys
import os

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
_HERE = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Plotly dark theme matching the app ───────────────────────────────────────
_BG      = "#0d0f1a"
_PLOT_BG = "#13162a"
_TEXT    = "#cbd5e1"
_GRID    = "#1e2235"
_PURPLE  = "#7c3aed"
_VIOLET  = "#a78bfa"
_TEAL    = "#2dd4bf"
_AMBER   = "#fbbf24"
_ROSE    = "#f87171"
_PALETTE = [_VIOLET, _TEAL, _AMBER, _ROSE, "#60a5fa", "#34d399", "#fb923c"]

_LAYOUT = dict(
    paper_bgcolor=_BG,
    plot_bgcolor=_PLOT_BG,
    font=dict(family="Inter, sans-serif", color=_TEXT, size=12),
    margin=dict(l=16, r=16, t=36, b=16),
    legend=dict(bgcolor="rgba(0,0,0,0)", font_color=_TEXT),
    xaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID, tickfont_color=_TEXT),
    yaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID, tickfont_color=_TEXT),
)


def _apply(fig: go.Figure) -> go.Figure:
    fig.update_layout(**_LAYOUT)
    return fig


# ── Data loading ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def _load_sector_map() -> dict[str, str]:
    """Return {neighbourhood_name: 'Sector N'} from districts.json."""
    districts_path = os.path.join(_HERE, "..", "districts.json")
    try:
        with open(districts_path, encoding="utf-8") as f:
            districts = json.load(f)
        mapping = {}
        for sector_name, neighbourhoods in districts.items():
            for n in neighbourhoods:
                mapping[n] = sector_name
        return mapping
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def _load_data() -> pd.DataFrame:
    import db_utils
    rows = db_utils.fetch_analytics_data()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Parse timestamps
    for col in ("scraped_at", "first_seen_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    # Normalise price
    if "price_numeric" in df.columns:
        df["price_numeric"] = pd.to_numeric(df["price_numeric"], errors="coerce")
        ron_mask = df.get("price_currency", pd.Series("EUR")) == "RON"
        df["price_eur_normalized"] = df["price_numeric"].where(~ron_mask, df["price_numeric"] / 5.1)

    if "area_sqm" in df.columns:
        df["area_sqm"] = pd.to_numeric(df["area_sqm"], errors="coerce")

    # Normalise rooms to clean label
    if "rooms" in df.columns:
        df["rooms"] = df["rooms"].astype(str).str.extract(r"(\d+\+?)")[0]
        df["rooms"] = df["rooms"].where(df["rooms"].notna(), "?")

    # Attach sector label from districts.json
    sector_map = _load_sector_map()
    if sector_map and "district" in df.columns:
        df["sector"] = df["district"].map(sector_map)

    return df


def _eur_df(df: pd.DataFrame) -> pd.DataFrame:
    """Listings with a valid normalised EUR price (data is pre-filtered to available)."""
    if "price_eur_normalized" not in df.columns:
        return df.iloc[0:0]
    mask = (
        df["price_eur_normalized"].notna()
        & (df["price_eur_normalized"] > 50)
        & (df["price_eur_normalized"] < 10000)
    )
    return df[mask]


# ── KPI cards ─────────────────────────────────────────────────────────────────

def _kpi(label: str, value: str, delta: str = "") -> str:
    delta_html = (
        f'<div style="font-size:0.72rem;color:#94a3b8;margin-top:2px;">{delta}</div>'
        if delta else ""
    )
    return (
        f'<div style="background:#13162a;border:1px solid #1e2235;border-radius:12px;'
        f'padding:1rem 1.2rem;text-align:center;">'
        f'<div style="font-size:0.72rem;color:#94a3b8;text-transform:uppercase;'
        f'letter-spacing:0.08em;margin-bottom:4px;">{label}</div>'
        f'<div style="font-size:1.6rem;font-weight:700;color:#e2e8f0;">{value}</div>'
        f'{delta_html}'
        f'</div>'
    )


# ── Individual chart builders ─────────────────────────────────────────────────

def _chart_daily_listings(df: pd.DataFrame) -> go.Figure:
    col = "scraped_at" if df["scraped_at"].notna().sum() > df["first_seen_at"].notna().sum() \
          else "first_seen_at"
    daily = (
        df[df[col].notna()]
        .assign(day=df[col].dt.date)
        .groupby("day")
        .size()
        .reset_index(name="count")
    )
    daily["day"] = pd.to_datetime(daily["day"])
    fig = px.area(
        daily, x="day", y="count",
        title="Listings scraped per day",
        labels={"day": "", "count": "Listings"},
        color_discrete_sequence=[_VIOLET],
    )
    fig.update_traces(line_color=_VIOLET, fillcolor=f"rgba(124,58,237,0.15)")
    return _apply(fig)


def _chart_price_histogram(df: pd.DataFrame) -> go.Figure:
    eur = _eur_df(df)
    fig = px.histogram(
        eur, x="price_eur_normalized",
        nbins=60,
        title="Price distribution — available listings (EUR)",
        labels={"price_eur_normalized": "Monthly rent (€)", "count": "Listings"},
        color_discrete_sequence=[_TEAL],
    )
    fig.update_traces(marker_line_width=0)
    return _apply(fig)


def _chart_avg_price_by_sector(df: pd.DataFrame) -> go.Figure:
    eur = _eur_df(df)
    if "sector" not in eur.columns:
        return go.Figure()
    agg = (
        eur[eur["sector"].notna()]
        .groupby("sector")["price_eur_normalized"]
        .agg(avg="mean", count="count", median="median")
        .reset_index()
        .sort_values("sector")
    )
    agg["label"] = agg["sector"].str.replace("Sector ", "S")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=agg["label"], y=agg["avg"],
        name="Avg",
        marker_color=_VIOLET,
        text=agg["avg"].map(lambda v: f"€{v:,.0f}"),
        textposition="outside",
        textfont_size=12,
    ))
    fig.add_trace(go.Scatter(
        x=agg["label"], y=agg["median"],
        name="Median",
        mode="markers+lines",
        marker=dict(color=_TEAL, size=10, symbol="diamond"),
        line=dict(color=_TEAL, width=2, dash="dot"),
    ))
    fig.update_layout(
        title="Avg & median monthly rent by sector",
        xaxis_title="",
        yaxis_title="Monthly rent (€)",
        barmode="group",
        hovermode="x unified",
    )
    return _apply(fig)


def _chart_avg_price_neighbourhood(df: pd.DataFrame, sector: str) -> go.Figure:
    eur = _eur_df(df)
    if "sector" not in eur.columns:
        return go.Figure()
    subset = eur[eur["sector"] == sector]
    agg = (
        subset.groupby("district")["price_eur_normalized"]
        .agg(avg="mean", count="count")
        .reset_index()
        .query("count >= 3")
        .sort_values("avg", ascending=True)
    )
    if agg.empty:
        return go.Figure()
    fig = px.bar(
        agg, x="avg", y="district",
        orientation="h",
        title=f"Avg monthly rent — {sector} neighbourhoods (≥3 listings)",
        labels={"avg": "Avg rent (€)", "district": ""},
        color="avg",
        color_continuous_scale=[[0, "#2dd4bf"], [1, "#a78bfa"]],
        text=agg["avg"].map(lambda v: f"€{v:,.0f}"),
        hover_data={"count": True},
    )
    fig.update_traces(textposition="outside", textfont_size=10)
    fig.update_coloraxes(showscale=False)
    layout_h = max(300, len(agg) * 28)
    fig.update_layout(height=layout_h)
    return _apply(fig)


def _chart_platform_breakdown(df: pd.DataFrame) -> go.Figure:
    counts = df["platform_id"].value_counts().reset_index()
    counts.columns = ["platform", "count"]
    fig = px.pie(
        counts, names="platform", values="count",
        title="Listings by platform",
        color_discrete_sequence=_PALETTE,
        hole=0.55,
    )
    fig.update_traces(textposition="outside", textinfo="percent+label")
    return _apply(fig)


def _chart_rooms_distribution(df: pd.DataFrame) -> go.Figure:
    order = [str(i) for i in range(1, 6)] + ["5+", "?"]
    counts = df["rooms"].value_counts().reindex(order, fill_value=0).reset_index()
    counts.columns = ["rooms", "count"]
    fig = px.bar(
        counts, x="rooms", y="count",
        title="Available listings by room count",
        labels={"rooms": "Rooms", "count": "Listings"},
        color_discrete_sequence=[_AMBER],
        text="count",
    )
    fig.update_traces(textposition="outside", textfont_size=11)
    return _apply(fig)


def _chart_price_by_rooms(df: pd.DataFrame) -> go.Figure:
    eur = _eur_df(df)
    eur = eur[eur["rooms"].isin([str(i) for i in range(1, 6)] + ["5+"])]
    fig = px.box(
        eur, x="rooms", y="price_eur_normalized",
        title="Rent distribution by room count (EUR, available)",
        labels={"rooms": "Rooms", "price_eur_normalized": "Monthly rent (€)"},
        color="rooms",
        color_discrete_sequence=_PALETTE,
        category_orders={"rooms": ["1", "2", "3", "4", "5", "5+"]},
    )
    fig.update_traces(marker_outliercolor="#475569")
    return _apply(fig)


def _chart_availability(df: pd.DataFrame) -> go.Figure:
    labels = {1: "Available", 0: "Expired", -1: "Blocked"}
    counts = (
        df["is_available"]
        .map(labels)
        .value_counts()
        .reset_index()
    )
    counts.columns = ["status", "count"]
    fig = px.pie(
        counts, names="status", values="count",
        title="Listing availability",
        color="status",
        color_discrete_map={
            "Available": _TEAL, "Expired": _ROSE, "Blocked": _AMBER
        },
        hole=0.55,
    )
    fig.update_traces(textposition="outside", textinfo="percent+label")
    return _apply(fig)


def _chart_price_vs_area(df: pd.DataFrame) -> go.Figure:
    eur = _eur_df(df)
    eur = eur[eur["area_sqm"].notna() & (eur["area_sqm"] > 10) & (eur["area_sqm"] < 300)]
    # Cap to 2000 points to keep the chart responsive
    sample = eur.sample(min(2000, len(eur)), random_state=42) if len(eur) > 2000 else eur
    fig = px.scatter(
        sample, x="area_sqm", y="price_eur_normalized",
        color="rooms",
        title="Rent vs area (available, EUR, up to 2 000 listings)",
        labels={"area_sqm": "Area (m²)", "price_eur_normalized": "Monthly rent (€)", "rooms": "Rooms"},
        color_discrete_sequence=_PALETTE,
        opacity=0.65,
    )
    return _apply(fig)


# ── Main render ───────────────────────────────────────────────────────────────

def render_analytics():
    # ── Top bar ──────────────────────────────────────────────────────────────
    col_back, col_title, col_refresh = st.columns([0.6, 3, 0.6])
    with col_back:
        if st.button("← Back"):
            st.session_state.page = "home"
            st.rerun()
    with col_title:
        st.markdown(
            '<h2 style="margin:0;color:#e2e8f0;font-size:1.4rem;font-weight:700;">'
            '📊 Market Analytics — Bucharest Rentals</h2>',
            unsafe_allow_html=True,
        )
    with col_refresh:
        if st.button("↻ Refresh"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("---")

    with st.spinner("Loading data…"):
        df = _load_data()

    if df.empty:
        st.error("Could not load data from Supabase.")
        return

    # ── Filters ──────────────────────────────────────────────────────────────
    with st.container():
        st.markdown(
            '<p style="color:#94a3b8;font-size:0.78rem;text-transform:uppercase;'
            'letter-spacing:0.08em;margin-bottom:6px;">Filters</p>',
            unsafe_allow_html=True,
        )
        fcol1, fcol2, fcol3 = st.columns([2, 2, 1])

        all_types = sorted(df["property_type"].dropna().unique().tolist()) \
            if "property_type" in df.columns else []
        all_rooms = [r for r in ["1", "2", "3", "4", "5+", "?"]
                     if r in df.get("rooms", pd.Series()).values]

        # Initialise session state — validate against current options so stale
        # values from a previous render don't break the widget.
        if "analytics_types" not in st.session_state:
            st.session_state["analytics_types"] = all_types
        else:
            st.session_state["analytics_types"] = [
                t for t in st.session_state["analytics_types"] if t in all_types
            ] or all_types

        if "analytics_rooms" not in st.session_state:
            st.session_state["analytics_rooms"] = all_rooms
        else:
            st.session_state["analytics_rooms"] = [
                r for r in st.session_state["analytics_rooms"] if r in all_rooms
            ] or all_rooms

        with fcol1:
            sel_types = st.multiselect(
                "Property type",
                options=all_types,
                key="analytics_types",
            )
        with fcol2:
            sel_rooms = st.multiselect(
                "Rooms",
                options=all_rooms,
                key="analytics_rooms",
            )
        with fcol3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Reset filters", use_container_width=True):
                st.session_state["analytics_types"] = all_types
                st.session_state["analytics_rooms"] = all_rooms
                st.rerun()

    # Apply filters — empty selection = treat as "all"
    if sel_types and len(sel_types) < len(all_types) and "property_type" in df.columns:
        df = df[df["property_type"].isin(sel_types)]
    if sel_rooms and len(sel_rooms) < len(all_rooms) and "rooms" in df.columns:
        df = df[df["rooms"].isin(sel_rooms)]

    if df.empty:
        st.warning("No listings match the selected filters.")
        return

    st.markdown("---")

    eur = _eur_df(df)

    # ── KPI row ──────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    total      = len(df)
    with_price = len(eur)
    avg_price  = eur["price_eur_normalized"].mean() if not eur.empty else 0
    med_price  = eur["price_eur_normalized"].median() if not eur.empty else 0
    avg_area   = eur["area_sqm"].dropna().mean() if "area_sqm" in eur.columns else 0

    with k1: st.markdown(_kpi("Available listings", f"{total:,}"), unsafe_allow_html=True)
    with k2: st.markdown(_kpi("With price", f"{with_price:,}", f"{with_price/total*100:.1f}% of total"), unsafe_allow_html=True)
    with k3: st.markdown(_kpi("Avg rent (EUR)", f"€{avg_price:,.0f}"), unsafe_allow_html=True)
    with k4: st.markdown(_kpi("Median rent (EUR)", f"€{med_price:,.0f}"), unsafe_allow_html=True)
    with k5: st.markdown(_kpi("Avg area", f"{avg_area:.0f} m²" if avg_area else "—"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Row 1: time series (full width) ──────────────────────────────────────
    st.plotly_chart(_chart_daily_listings(df), use_container_width=True)

    # ── Row 2: price histogram + price by rooms ───────────────────────────────
    c1, c2 = st.columns(2)
    with c1: st.plotly_chart(_chart_price_histogram(df), use_container_width=True)
    with c2: st.plotly_chart(_chart_price_by_rooms(df), use_container_width=True)

    # ── Row 3: sector overview + neighbourhood drilldown ─────────────────────
    st.plotly_chart(_chart_avg_price_by_sector(df), use_container_width=True)

    if "sector" in df.columns:
        sectors = sorted(df["sector"].dropna().unique().tolist())
        if sectors:
            if "analytics_sector" not in st.session_state:
                st.session_state["analytics_sector"] = sectors[0]

            st.markdown(
                '<p style="color:#94a3b8;font-size:0.82rem;margin-bottom:4px;">'
                'Drill down — select a sector:</p>',
                unsafe_allow_html=True,
            )
            selected = st.radio(
                "sector_select",
                options=sectors,
                index=sectors.index(st.session_state["analytics_sector"]),
                horizontal=True,
                label_visibility="collapsed",
                key="analytics_sector",
            )
            st.plotly_chart(
                _chart_avg_price_neighbourhood(df, selected),
                use_container_width=True,
            )

    # ── Row 4: scatter + platform + availability ──────────────────────────────
    st.plotly_chart(_chart_price_vs_area(df), use_container_width=True)

    c3, c4, c5 = st.columns(3)
    with c3: st.plotly_chart(_chart_rooms_distribution(df), use_container_width=True)
    with c4: st.plotly_chart(_chart_platform_breakdown(df), use_container_width=True)
    with c5: st.plotly_chart(_chart_availability(df), use_container_width=True)
