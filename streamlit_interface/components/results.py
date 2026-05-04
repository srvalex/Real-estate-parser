import streamlit as st
import pandas as pd
import sys
import importlib
import json
from utils import safe_str, apply_filters, prepare_dataframe, apply_ai_scores, apply_price_fairness
from image_embedder import embed_all_photos
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
                render_property_cards(apply_filters(
                    df_running,
                    params.get("max_price", 0),
                    params.get("rooms", "Any"),
                    params.get("min_sqm", 0),
                    params.get("max_sqm", 0),
                    params.get("property_types"),
                ))
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

    # ── Embed all photos into image ChromaDB collection ──────────────────────
    image_server_url = params.get("image_server_url", "")
    if not df_new_only.empty and "image_urls" in df_new_only.columns and image_server_url:
        with st.spinner(f"Embedding photos for {len(df_new_only)} new listings…"):
            n_embedded, img_err = embed_all_photos(df_new_only, image_server_url)
        if img_err:
            st.warning(f"Image embedding: {img_err}")

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
    if embed_error and not params.get("embedding_sorted", False):
        st.warning(f"AI ranking unavailable: {embed_error}", icon="⚠️")

    if df.empty and not pending_scrape:
        st.warning("No data loaded. Go back and try again.")
        st.stop()

    # ── Scrape-only: skip the empty card view, go straight to live scraping ──
    if pending_scrape and df.empty:
        _load_more(params, is_initial=True)
        return

    # ── Apply filters ──
    df_f = apply_filters(
        df,
        params.get("max_price", 0),
        params.get("rooms", "Any"),
        params.get("min_sqm", 0),
        params.get("max_sqm", 0),
        params.get("property_types"),
    )
    df_f = apply_price_fairness(df_f)

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
                    image_embedding=params.get("image_embedding"),
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

def _parse_image_urls(raw) -> list:
    """Return a list of image dicts from a column value (JSON string or list)."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if isinstance(raw, list):
        return raw
    return []


def _build_image_html(images: list) -> str:
    """Cover photo + scrollable thumbnail strip."""
    if not images:
        return ""

    first = images[0]
    cover_url = (first.get("medium") or first.get("small")
                 or first.get("large") or first.get("thumbnail") or "")
    if not cover_url:
        return ""

    cover_html = (
        f'<img src="{cover_url}" '
        f'style="width:100%;height:200px;object-fit:cover;border-radius:10px 10px 0 0;display:block;" '
        f'loading="lazy"/>'
    )

    if len(images) <= 1:
        return cover_html

    thumbs = ""
    for img in images[1:6]:   # show up to 5 thumbnails
        t = img.get("thumbnail") or img.get("small") or img.get("medium") or ""
        if t:
            thumbs += (
                f'<img src="{t}" '
                f'style="height:54px;width:80px;object-fit:cover;border-radius:4px;flex-shrink:0;" '
                f'loading="lazy"/>'
            )

    strip_html = (
        f'<div style="display:flex;gap:4px;padding:4px 6px;'
        f'overflow-x:auto;background:#0e0e1a;">{thumbs}</div>'
    )
    return cover_html + strip_html


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
                def _esc(s: str) -> str:
                    return (s.replace("&", "&amp;").replace("<", "&lt;")
                             .replace(">", "&gt;").replace('"', "&quot;")
                             .replace("'", "&#39;"))

                title      = _esc(safe_str(row.get("title", "")) or "Untitled listing")

                # Price: prefer numeric + currency (clean, no encoding corruption)
                price_num  = row.get("price_numeric")
                price_cur  = safe_str(row.get("price_currency", "EUR"))
                if price_num is not None and str(price_num) not in ("", "nan"):
                    symbol     = "€" if price_cur == "EUR" else "RON"
                    price_disp = f"{int(float(price_num)):,} {symbol}/lună".replace(",", " ")
                else:
                    price_disp = _esc(safe_str(
                        row.get("price_eur", row.get("rent", row.get("price", "")))
                    ) or "—")

                district   = _esc(safe_str(row.get("district", "")))
                location   = _esc(safe_str(row.get("location_full", row.get("location_full_name", ""))))

                # Rooms: canonical value is already normalised ('1'–'5+')
                rooms_raw  = safe_str(row.get("rooms", "") or row.get("rooms_num", ""))
                rooms_val  = _esc(f"{rooms_raw} cam." if rooms_raw else "")

                # Area: canonical column is a float; format it
                area_raw   = row.get("area_sqm", row.get("m", ""))
                if area_raw is not None and str(area_raw) not in ("", "nan"):
                    try:
                        sqm = _esc(f"{float(area_raw):.0f} m²")
                    except (ValueError, TypeError):
                        sqm = _esc(safe_str(area_raw))
                else:
                    sqm = ""
                desc       = safe_str(row.get("description", ""))
                url        = safe_str(row.get("url", ""))
                platform   = _esc(safe_str(row.get("platform", "Storia")))

                chips = ""
                if rooms_val: chips += f'<span class="meta-chip">🛏 {rooms_val}</span>'
                if sqm:       chips += f'<span class="meta-chip">📐 {sqm}</span>'
                loc_label = district or location[:30]
                if loc_label: chips += f'<span class="meta-chip">📍 {loc_label}</span>'

                # ── Price fairness badge ─────────────────────────────────
                fairness = safe_str(row.get("price_fairness", ""))
                if fairness:
                    clr  = "#4ade80" if fairness.startswith("-") else "#f87171"
                    icon = "📉" if fairness.startswith("-") else "📈"
                    chips += (
                        f'<span style="display:inline-block;background:{clr}22;color:{clr};'
                        f'border:1px solid {clr}55;border-radius:6px;'
                        f'padding:2px 8px;font-size:0.72rem;font-weight:600;margin-left:2px;">'
                        f'{icon} {_esc(fairness)}</span>'
                    )

                # ── Similarity score badge ───────────────────────────────
                score_badge = ""
                if has_scores:
                    raw_dist = row.get("_similarity_score")
                    if raw_dist is not None and str(raw_dist) != "nan":
                        match_pct = round(float(raw_dist) * 100)
                        if match_pct >= 70:
                            colour = "#4ade80"
                        elif match_pct >= 40:
                            colour = "#facc15"
                        else:
                            colour = "#94a3b8"
                        score_badge = (
                            f'<span style="display:inline-block;vertical-align:middle;'
                            f'background:{colour}22;color:{colour};'
                            f'border:1px solid {colour}55;border-radius:6px;'
                            f'padding:2px 10px;font-size:0.75rem;font-weight:600;">'
                            f'🎯 {match_pct}% match</span>'
                        )

                images     = _parse_image_urls(row.get("image_urls"))
                image_html = _build_image_html(images)
                img_count  = f'<span class="meta-chip">📷 {len(images)}</span>' if images else ""

                plat_class = "olx" if "olx" in platform.lower() else ""
                link_html  = f'<a class="card-link" href="{url}" target="_blank">View listing →</a>' if url else ""
                desc_html  = (
                    desc[:400]
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
                    .replace("'", "&#39;")
                    .replace("\n", " ")
                )

                card_html = (
                    f'<div class="prop-card" style="padding:0;overflow:hidden;">'
                    f'{image_html}'
                    f'<div style="padding:16px;">'
                    f'<div class="card-platform {plat_class}">{platform}</div>'
                    f'<div class="card-title">{title}</div>'
                    f'<div class="card-price">{price_disp}&nbsp;&nbsp;{score_badge}</div>'
                    f'<div class="card-meta">{chips}{img_count}</div>'
                    f'<div class="card-desc">{desc_html}</div>'
                    f'{link_html}'
                    f'</div>'
                    f'</div>'
                )
                st.markdown(card_html, unsafe_allow_html=True)
