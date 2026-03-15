import streamlit as st
import pandas as pd
from utils import safe_str, apply_vibe

def render_results():
    params = st.session_state.search_params
    df: pd.DataFrame = st.session_state.get("df", pd.DataFrame())

    # ── Top bar ──
    col_back, col_logo, col_vibe = st.columns([0.8, 1, 4])
    with col_back:
        if st.button("← Back"):
            st.session_state.page = "home"
            st.rerun()
    with col_logo:
        st.markdown('<div style="color:#a78bfa;font-weight:700;padding-top:0.5rem;">🏠 Explorer</div>', unsafe_allow_html=True)
    with col_vibe:
        vibe_text = params.get("vibe", "").strip()
        if vibe_text:
            st.markdown(f'<div class="vibe-pill">✨ "{vibe_text}"</div>', unsafe_allow_html=True)

    st.markdown("---")

    # ── Parsed vibe JSON expander ──
    parsed = params.get("parsed_params")
    parse_err = params.get("parse_error")
    if parsed:
        with st.expander("🧠 How Ollama understood your vibe", expanded=True):
            st.json(parsed)
    elif parse_err:
        with st.expander("⚠️ Ollama parsing note", expanded=True):
            st.warning(parse_err)
            st.caption("Search is still running using your raw text as keyword filter.")

    if df.empty:
        st.warning("No data loaded. Go back and try again.")
        st.stop()

    # ── Apply filters ──
    df_f = df.copy()

    # Price filter
    max_price = params.get("max_price", 0)
    if max_price and max_price > 0:
        has_price = df_f["_price_num"].notna()
        under = df_f["_price_num"] <= max_price
        df_f = df_f[~has_price | under]

    # Rooms filter
    sel_rooms = params.get("rooms", "Any")
    if sel_rooms != "Any":
        target = 4 if sel_rooms == "4+" else int(sel_rooms)
        has_rooms = df_f["_rooms_num"].notna()
        if sel_rooms == "4+":
            matches = df_f["_rooms_num"] >= 4
        else:
            matches = df_f["_rooms_num"] == target
        df_f = df_f[~has_rooms | matches]

    # Vibe filter - Disabled as per user request to rely on smart URLs only
    # df_f = apply_vibe(df_f, params.get("vibe", ""))

    # ── Count ──
    total, shown = len(df), len(df_f)
    st.markdown(
        f'<div class="result-count"><span>{shown}</span> listings match your search &nbsp;·&nbsp; {total} total</div>',
        unsafe_allow_html=True,
    )

    render_property_cards(df_f)

def render_property_cards(df_f):
    if df_f.empty:
        st.markdown("""
        <div class="no-results">
            <span>🔍</span>
            No listings match your criteria.<br>Try broadening the vibe or removing filters.
        </div>
        """, unsafe_allow_html=True)
    else:
        left, right = st.columns(2)

        for i, (_, row) in enumerate(df_f.iterrows()):
            col = left if i % 2 == 0 else right
            with col:
                title      = safe_str(row.get("title", "")) or "Untitled listing"
                price_disp = safe_str(row.get("rent", row.get("price", ""))) or "—"
                district   = safe_str(row.get("district", ""))
                location   = safe_str(row.get("location_full_name", ""))
                rooms_val  = safe_str(row.get("rooms", ""))
                sqm        = safe_str(row.get("m", ""))
                desc       = safe_str(row.get("description", ""))
                url        = safe_str(row.get("url", ""))
                platform   = safe_str(row.get("platform", "Storia"))

                chips = ""
                if rooms_val: chips += f'<span class="meta-chip">🛏 {rooms_val}</span>'
                if sqm:       chips += f'<span class="meta-chip">📐 {sqm}</span>'
                loc_label = district or location[:30]
                if loc_label: chips += f'<span class="meta-chip">📍 {loc_label}</span>'

                plat_class = "olx" if "olx" in platform.lower() else ""
                link_html  = f'<a class="card-link" href="{url}" target="_blank">View listing →</a>' if url else ""
                desc_html  = desc[:400].replace("<", "&lt;").replace(">", "&gt;")

                st.markdown(f"""
                <div class="prop-card">
                    <div class="card-platform {plat_class}">{platform}</div>
                    <div class="card-title">{title}</div>
                    <div class="card-price">{price_disp}</div>
                    <div class="card-meta">{chips}</div>
                    <div class="card-desc">{desc_html}</div>
                    {link_html}
                </div>
                """, unsafe_allow_html=True)
