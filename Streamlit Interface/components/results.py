import streamlit as st
import pandas as pd
import sys
import importlib
from utils import safe_str, apply_filters, prepare_dataframe, apply_ai_scores
from local_embedder import embed_listings
from nlp_filters import apply_description_filters

# Static mapping from spaCy filter key → (icon, Romanian label)
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


def _render_filter_pills(spacy_filters: dict):
    """Render the detected-filter pills inside an expander."""
    if not spacy_filters:
        return
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


def _load_more(params: dict, is_initial: bool = False):
    """Re-run the scrape pipeline and update session state.
    is_initial=True uses the user's original page selection;
    is_initial=False (load-more button) adds 2 pages on top of what was scraped.
    """
    scrape_config = params["scrape_config"]
    pages_scraped = params.get("pages_scraped", 1)
    new_pages = scrape_config.get("pages", 1) if is_initial else pages_scraped + 2
    data_dir = params.get("data_dir", "")

    sys.path.insert(0, data_dir)
    import extractor
    importlib.reload(extractor)
    from extractor import run_pipeline

    # Build jobs with updated page count
    jobs = [
        {**job, "pages": new_pages}
        for job in scrape_config.get("jobs", [])
    ]

    status_box = st.empty()
    cards_box  = st.empty()
    df_running = pd.DataFrame()
    df_final   = pd.DataFrame()

    for status, partial_df in run_pipeline(
        jobs=jobs,
        out_csv="results.csv",
    ):
        if status in ("db_cache", "progress") and not partial_df.empty:
            df_running = pd.concat([df_running, prepare_dataframe(partial_df)], ignore_index=True)
            status_box.info(f"🕷️ {len(df_running)} listings found so far…")
            with cards_box.container():
                render_property_cards(apply_filters(df_running, params.get("max_price", 0), params.get("rooms", "Any")))
        elif status == "done":
            df_final = partial_df

    if df_final.empty:
        status_box.warning("No new results found.")
        return

    df_final = prepare_dataframe(df_final)

    # ── Merge with cached results (Firestore) ────────────────────────────────
    cached_df = st.session_state.get("df", pd.DataFrame())
    new_count = 0
    url_col_new = "url" if "url" in df_final.columns else ("link" if "link" in df_final.columns else None)

    if not cached_df.empty:
        url_col_cached = "url" if "url" in cached_df.columns else ("link" if "link" in cached_df.columns else None)
        if url_col_cached and url_col_new and url_col_cached == url_col_new:
            # Cached rows take priority; drop scraped duplicates
            existing_urls = set(cached_df[url_col_cached].dropna())
            df_new_only = df_final[~df_final[url_col_new].isin(existing_urls)]
            df_final = pd.concat([cached_df, df_new_only], ignore_index=True)
        else:
            df_new_only = df_final
            df_final = pd.concat([cached_df, df_final], ignore_index=True)

        new_count = len(df_new_only)
        status_box.info(f"🔀 Combined: {len(cached_df)} cached + {new_count} new = {len(df_final)} total")
    else:
        df_new_only = df_final

    # ── Embed newly scraped listings into ChromaDB ───────────────────────────
    if url_col_new and not df_new_only.empty and "description" in df_new_only.columns:
        embed_payload = [
            {
                "description": str(row.get("description", "") or ""),
                "url":         str(row.get(url_col_new, "") or ""),
                "hard_filters": [],
                "soft_filters": [],
            }
            for _, row in df_new_only[[url_col_new, "description"]].fillna("").iterrows()
            if str(row.get("description", "")).strip() and str(row.get(url_col_new, "")).strip()
        ]
        if embed_payload:
            with st.spinner(f"Embedding {len(embed_payload)} new listings into ChromaDB…"):
                embed_listings(embed_payload)

    spacy_filters = params.get("spacy_filters", {})
    if spacy_filters:
        df_final, _, _ = apply_description_filters(df_final, spacy_filters)

    # Save merged (unranked) results and come back to rank on the next render
    # so the user sees all listings before the AI re-ordering happens.
    params["pages_scraped"] = new_pages
    params["embedding_sorted"] = False
    params["embed_error"] = None
    params["_pending_rerank"] = True
    st.session_state.search_params = params
    st.session_state.df = df_final
    if new_count > 0:
        st.session_state["_scrape_toast"] = f"✅ Scraping done — {new_count} new listings added"
    else:
        st.session_state["_scrape_toast"] = "ℹ️ Scraping done — no new listings found"
    st.rerun()


def render_results():
    params = st.session_state.search_params
    df: pd.DataFrame = st.session_state.get("df", pd.DataFrame())

    # ── Show scrape-done notification if set by _load_more ───────────────────
    toast_msg = st.session_state.pop("_scrape_toast", None)
    if toast_msg:
        st.toast(toast_msg)

    # Consume the flag early so it doesn't re-trigger on the next rerun,
    # but remember it so we can start the scrape at the bottom of the page.
    pending_scrape = params.get("pending_scrape", False)
    if pending_scrape:
        params["pending_scrape"] = False
        st.session_state.search_params = params

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

    _render_filter_pills(params.get("spacy_filters", {}))

    embed_error = params.get("embed_error")
    if embed_error:
        st.warning(f"AI ranking unavailable: {embed_error}", icon="⚠️")

    if df.empty and not pending_scrape:
        st.warning("No data loaded. Go back and try again.")
        st.stop()

    # ── Scrape-only: skip the empty card view, go straight to live scraping ──
    if pending_scrape and df.empty:
        _load_more(params, is_initial=True)
        return

    # ── Apply filters ──
    df_f = apply_filters(df, params.get("max_price", 0), params.get("rooms", "Any"))

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

    # ── Cached+Scrape: show cached cards first, then trigger live scraping ────
    if pending_scrape:
        st.markdown("---")
        _load_more(params, is_initial=True)
        return

    # ── Re-rank with AI after all results are visible ────────────────────────
    if params.get("_pending_rerank") and params.get("vibe", "").strip():
        params["_pending_rerank"] = False
        st.session_state.search_params = params
        vibe = params.get("vibe", "")
        server_url = params.get("server_url", "")
        url_col = "url" if "url" in df.columns else ("link" if "link" in df.columns else None)
        if url_col:
            with st.spinner("🧠 Re-ranking results by AI similarity…"):
                df_ranked, embedding_sorted, embed_error = apply_ai_scores(
                    df, vibe, server_url, url_col,
                    skip_embed=True,
                    spacy_filters=params.get("spacy_filters"),
                )
            params["embedding_sorted"] = embedding_sorted
            params["embed_error"] = embed_error
            st.session_state.search_params = params
            st.session_state.df = df_ranked
            st.rerun()

    # ── Load more ──────────────────────────────────────────────────────────────
    scrape_config = params.get("scrape_config")
    if scrape_config and scrape_config.get("olx_urls"):
        pages_scraped = params.get("pages_scraped", 1)
        st.markdown("---")
        st.markdown(
            f'<div style="text-align:center;color:#94a3b8;font-size:0.85rem;margin-bottom:0.5rem;">'
            f'Showing results from page 1–{pages_scraped}. Want more?'
            f'</div>',
            unsafe_allow_html=True,
        )
        _, btn_col, _ = st.columns([1, 2, 1])
        with btn_col:
            if st.button(f"🔄 Search pages {pages_scraped + 1}–{pages_scraped + 2}", use_container_width=True):
                _load_more(params)

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
                        # _similarity_score is 0–1 (1 = best match)
                        match_pct = round(float(raw_dist) * 100)
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
