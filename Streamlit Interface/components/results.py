import streamlit as st
import pandas as pd
from utils import safe_str

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

    # ── spaCy filters expander ──
    spacy_filters = params.get("spacy_filters", {})
    if spacy_filters:
        LABEL_MAP = {
            "ROOM_COUNT":           ("🛌", "camere"),
            "LOCATION_SECTOR":      ("📍", "sector"),
            "HAS_METRO":            ("🚇", "metrou"),
            "HAS_PARKING":          ("🚗", "parcare"),
            "PET_FRIENDLY":         ("🐾", "pet-friendly"),
            "HAS_HEATING_UNIT":     ("🔥", "centrală"),
            "HAS_BALCONY":          ("🌿", "balcon"),
            "CONDITION_RENOVATED":  ("✨", "renovat"),
            "STYLE_MODERN":         ("🏠", "modern"),
            "FURNISHED":            ("🛋️", "mobilat"),
            "FEAT_BRIGHT":          ("☀️", "luminos"),
            "FEAT_QUIET":           ("🤫", "liniștit"),
        }
        with st.expander("🧠 Filters detected from your prompt", expanded=True):
            pills = ""
            for key, val in spacy_filters.items():
                icon, label = LABEL_MAP.get(key, ("🔖", key))
                display = f"{val}" if not isinstance(val, bool) else label
                pills += (
                    f'<span style="display:inline-block;background:#7c3aed22;color:#a78bfa;'
                    f'border:1px solid #7c3aed55;border-radius:20px;padding:3px 12px;'
                    f'margin:3px;font-size:0.82rem;">'
                    f'{icon} {display}</span>'
                )
            st.markdown(pills, unsafe_allow_html=True)

    # ── Embedding error notice ──
    embed_error = params.get("embed_error")
    if embed_error:
        st.warning(f"⚠️ AI ranking unavailable: {embed_error}", icon="⚠️")

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

    # ── AI-sorted banner ────────────────────────────────────────────────
    embedding_sorted = params.get("embedding_sorted", False)
    if embedding_sorted:
        st.markdown(
            '<div style="background:linear-gradient(90deg,#7c3aed22,#a78bfa11);'
            'border:1px solid #7c3aed55;border-radius:10px;padding:0.6rem 1rem;'
            'margin-bottom:0.8rem;font-size:0.85rem;color:#a78bfa;">'
            '🧠 Results ranked by <strong>AI similarity</strong> to your vibe — closest match first.'
            '</div>',
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
        has_scores = "_similarity_score" in df_f.columns

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

                # ── Similarity score badge ───────────────────────────────
                score_badge = ""
                if has_scores:
                    raw_dist = row.get("_similarity_score")
                    if raw_dist is not None and str(raw_dist) != "nan":
                        # Cosine distance ∈ [0, 2]; convert to a 0–100 % match
                        match_pct = max(0, round((1 - float(raw_dist) / 2) * 100))
                        # Colour: green ≥ 70%, yellow ≥ 40%, muted otherwise
                        if match_pct >= 70:
                            colour = "#4ade80"   # green
                        elif match_pct >= 40:
                            colour = "#facc15"   # yellow
                        else:
                            colour = "#94a3b8"   # slate
                        score_badge = (
                            f'<span style="display:inline-block;vertical-align:middle;'
                            f'background:{colour}22;color:{colour};'
                            f'border:1px solid {colour}55;border-radius:6px;'
                            f'padding:2px 10px;font-size:0.75rem;font-weight:600;">'
                            f'🎯 {match_pct}% match</span>'
                        )

                plat_class = "olx" if "olx" in platform.lower() else ""
                link_html  = f'<a class="card-link" href="{url}" target="_blank">View listing →</a>' if url else ""
                desc_html  = desc[:400].replace("<", "&lt;").replace(">", "&gt;")

                st.markdown(f"""
                <div class="prop-card">
                    <div class="card-platform {plat_class}">{platform}</div>
                    <div class="card-title">{title}</div>
                    <div class="card-price">{price_disp}&nbsp;&nbsp;{score_badge}</div>
                    <div class="card-meta">{chips}</div>
                    <div class="card-desc">{desc_html}</div>
                    {link_html}
                </div>
                """, unsafe_allow_html=True)
