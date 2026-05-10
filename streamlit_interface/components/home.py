import streamlit as st
import os
import pandas as pd
import time
from utils import prepare_dataframe, apply_filters, apply_ai_scores, apply_price_fairness
from components.results import render_property_cards
from nlp_filters import extract_filters, apply_description_filters


def render_home(districts, proximity, server_url):

    # ── Nav bar ──────────────────────────────────────────────────────────────
    _, nav_col, _ = st.columns([3, 1, 3])
    with nav_col:
        if st.button("📊 Market Analytics", use_container_width=True):
            st.session_state.page = "analytics"
            st.rerun()

    # Hero
    st.markdown("""
    <div class="home-hero">
        <div class="badge">🏠 Real Estate Explorer</div>
        <h1>Find your<br>perfect place</h1>
        <p>Describe what you're looking for in plain language — we'll search through the scraped listings and surface the best matches.</p>
    </div>
    """, unsafe_allow_html=True)

    # Search card
    with st.container():
        _, center, _ = st.columns([1, 2.5, 1])
        with center:

            # ── Vibe ──
            st.markdown('<div class="vibe-label">✨ What\'s the vibe you\'re after?</div>', unsafe_allow_html=True)
            st.markdown('<div class="vibe-hint">Describe in your own words — keywords, feelings, must-haves. e.g. <em>"bright, modern, quiet street near metro"</em></div>', unsafe_allow_html=True)
            vibe = st.text_area(
                label="vibe",
                placeholder="e.g. modern kitchen, quiet, close to a park, renovated, good light...",
                height=110,
                label_visibility="collapsed",
            )

            # ── Template photo picker ─────────────────────────────────────────
            _TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "template_photos")
            _SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
            _template_files = sorted([
                f for f in os.listdir(_TEMPLATE_DIR)
                if os.path.splitext(f)[1].lower() in _SUPPORTED_EXT
            ]) if os.path.isdir(_TEMPLATE_DIR) else []

            selected_templates = []
            if _template_files:
                st.markdown('<div class="section-label">🖼️ Visual vibe (optional)</div>', unsafe_allow_html=True)
                st.caption("Select reference photos — results will be ranked by visual similarity.")
                cols = st.columns(2)
                for i, fname in enumerate(_template_files):
                    fpath = os.path.join(_TEMPLATE_DIR, fname)
                    label = os.path.splitext(fname)[0].replace("_", " ").replace("-", " ").title()
                    with cols[i % 2]:
                        st.image(fpath, use_container_width=True)
                        if st.checkbox(label, key=f"tpl_{fname}"):
                            selected_templates.append(fpath)

            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

            # ── Quick filters ──
            st.markdown('<div class="section-label">Filtre</div>', unsafe_allow_html=True)

            max_price = st.number_input("Preț maxim (€/luna)", min_value=0, max_value=10000, value=0, step=50, help="Leave at 0 to skip")

            fcol1, fcol2 = st.columns(2)
            with fcol1:
                rooms = st.selectbox(
                    "Număr camere",
                    options=["Any", "1", "2", "3", "4", "5+"],
                    index=0,
                    help="Filtrează după numărul de camere",
                )
            with fcol2:
                property_types_opts = ["Apartament", "Garsoniera", "Studio", "Casa/Vila"]
                property_types = st.multiselect(
                    "Tip proprietate",
                    options=property_types_opts,
                    default=property_types_opts,
                    help="Lasă gol sau selectează toate pentru orice tip",
                )

            sqm_col1, sqm_col2 = st.columns(2)
            with sqm_col1:
                min_sqm = st.number_input("Suprafață min (m²)", min_value=0, max_value=500, value=0, step=5, help="0 = fără limită")
            with sqm_col2:
                max_sqm = st.number_input("Suprafață max (m²)", min_value=0, max_value=500, value=0, step=5, help="0 = fără limită")

            # ── Zone selector ──
            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
            st.markdown('<div class="section-label">Select Locations</div>', unsafe_allow_html=True)

            final_selection = []
            full_sectors = []          # district names where "select all" was checked
            partial_by_sector = {}     # district_name → [selected neighbourhoods]

            for district_name, neighborhoods in districts.items():
                sector_num = int(district_name.split(" ")[1])
                with st.container(border=True):
                    cols = st.columns([1, 4])
                    with cols[0]:
                        select_all = st.checkbox(f"Tot S{sector_num}", key=f"all_{district_name}")
                    with cols[1]:
                        selected_in_district = st.multiselect(
                            f"Cartiere {district_name}",
                            options=neighborhoods,
                            key=f"select_{district_name}",
                            label_visibility="collapsed"
                        )

                if select_all:
                    full_sectors.append(district_name)
                    final_selection.extend(neighborhoods)
                elif selected_in_district:
                    partial_by_sector[district_name] = selected_in_district
                    final_selection.extend(selected_in_district)

            # ── Proximity ──
            use_proximity = st.toggle("🔍 Activare Proximity Search", value=False)
            proximity_selection = []
            if use_proximity and final_selection:
                for area in final_selection:
                    for neighbor in proximity.get(area, []):
                        if neighbor not in final_selection and neighbor not in proximity_selection:
                            proximity_selection.append(neighbor)

            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

            st.caption("✅ Supabase + pgvector search ready")

            st.markdown('<br>', unsafe_allow_html=True)

            # ── CTA ──
            _, btn_col, _ = st.columns([1, 2, 1])
            with btn_col:
                search_clicked = st.button("🔍  Search listings", use_container_width=True)

            st.markdown('</div>', unsafe_allow_html=True)

        # ── Instant local NLP extraction (no network call) ──
        spacy_filters = {}
        if vibe.strip():
            spacy_filters = extract_filters(vibe)
        
    # Handle search
    if search_clicked:
        if not final_selection:
            st.error("Please select at least one location to search.")
            st.stop()

        df = None

        # ── NLP auto-fill: use detected values for any field left at default ──
        # Form always wins; NLP only fills in fields the user didn't touch.
        _ALL_PTYPES = ["Apartament", "Garsoniera", "Studio", "Casa/Vila"]
        _nlp_filled = []

        if rooms == "Any" and spacy_filters.get("ROOM_COUNT"):
            _r = str(spacy_filters["ROOM_COUNT"])
            try:
                if int(_r) >= 5:
                    _r = "5+"
            except ValueError:
                pass
            if _r in ["1", "2", "3", "4", "5+"]:
                rooms = _r
                _nlp_filled.append(f"camere: {rooms}")

        if (not property_types or set(property_types) == set(_ALL_PTYPES)) \
                and spacy_filters.get("PROPERTY_TYPE") in _ALL_PTYPES:
            property_types = [spacy_filters["PROPERTY_TYPE"]]
            _nlp_filled.append(f"tip: {property_types[0]}")

        if max_price == 0 and spacy_filters.get("PRICE_MAX"):
            max_price = int(spacy_filters["PRICE_MAX"])
            _nlp_filled.append(f"preț ≤ {max_price} €")

        if min_sqm == 0 and spacy_filters.get("AREA_MIN"):
            min_sqm = int(spacy_filters["AREA_MIN"])
            _nlp_filled.append(f"suprafață ≥ {min_sqm} m²")

        if max_sqm == 0 and spacy_filters.get("AREA_MAX"):
            max_sqm = int(spacy_filters["AREA_MAX"])
            _nlp_filled.append(f"suprafață ≤ {max_sqm} m²")

        if _nlp_filled:
            st.toast(f"🤖 NLP completat: {', '.join(_nlp_filled)}", icon="🤖")

        # ── Query database ─────────────────────────────────────────────────────
        with st.spinner("⚡ Loading listings from database…"):
            from db_utils import query_listings_by_district
            records = query_listings_by_district(final_selection)

        if records:
            df = prepare_dataframe(pd.DataFrame(records))
            df = apply_filters(df, max_price, rooms, min_sqm, max_sqm, property_types or None)
            df = apply_price_fairness(df)
            st.toast(f"⚡ {len(df)} listings loaded from database", icon="✅")
        else:
            st.warning("No saved listings found for the selected zones.")

        if df is None or df.empty:
            st.error("No listings found. Try different zones.")
            st.stop()

        embedding_sorted = False
        embed_error      = None

        # ── Embed selected template photos ────────────────────────────────────
        image_embedding = None
        if selected_templates:
            import json as _json
            _cache_path = os.path.join(_TEMPLATE_DIR, "embeddings.json")
            _cache = {}
            if os.path.exists(_cache_path):
                with open(_cache_path) as _f:
                    _cache = _json.load(_f)

            embeddings = []
            missing = []
            for p in selected_templates:
                vec = _cache.get(os.path.basename(p))
                if vec is not None:
                    embeddings.append(vec)
                else:
                    missing.append(p)

            if missing:
                from image_embedder import embed_local_image
                with st.spinner(f"Embedding {len(missing)} new photo(s)…"):
                    for p in missing:
                        e = embed_local_image(p)
                        if e is not None:
                            embeddings.append(e)

            if embeddings:
                if len(embeddings) == 1:
                    image_embedding = embeddings[0]
                else:
                    # Average multiple photo embeddings
                    import numpy as np
                    arr = np.array(embeddings)
                    avg = arr.mean(axis=0)
                    norm = np.linalg.norm(avg)
                    image_embedding = (avg / norm if norm > 0 else avg).tolist()
                st.toast(f"🖼️ {len(embeddings)} template photo(s) ready", icon="✅")
            else:
                st.toast("⚠️ Could not load template photo embeddings — falling back to text search", icon="⚠️")

        if spacy_filters:
            df, excluded_count, exclusion_summary = apply_description_filters(df, spacy_filters)
            if excluded_count:
                labels = {"PET_FRIENDLY": "nu acceptă animale", "HAS_PARKING": "fără parcare",
                          "HAS_BALCONY": "fără balcon", "FURNISHED": "nemobilat",
                          "HAS_HEATING_UNIT": "fără centrală"}
                reasons = ", ".join(labels.get(k, k) for k in exclusion_summary)
                st.toast(f"🚫 {excluded_count} listings removed ({reasons})", icon="🚫")

        url_col = "url" if "url" in df.columns else ("link" if "link" in df.columns else None)

        live_status = st.empty()
        live_cards  = st.empty()

        live_status.info(f"⚡ Found **{len(df)}** listings — running AI ranking…")
        with live_cards.container():
            render_property_cards(df)

        if (vibe.strip() or image_embedding) and url_col:
            df, embedding_sorted, embed_error = apply_ai_scores(
                df, vibe, server_url, url_col,
                skip_embed=True,
                spacy_filters=spacy_filters,
                image_embedding=image_embedding,
            )

            if embedding_sorted:
                live_status.success(f"🎯 AI ranked **{len(df)}** listings — navigating to results…")
                with live_cards.container():
                    render_property_cards(df)
                time.sleep(1.5)
            elif embed_error:
                st.toast(f"⚠️ AI ranking skipped: {embed_error}", icon="⚠️")
                live_status.warning("⚠️ AI ranking unavailable — showing unscored results.")
            else:
                live_status.warning("⚠️ No AI scores returned — showing unordered results.")

        st.session_state.search_params = {
            "vibe":             vibe,
            "max_price":        max_price,
            "rooms":            rooms,
            "min_sqm":          min_sqm,
            "max_sqm":          max_sqm,
            "property_types":   property_types or None,
            "spacy_filters":    spacy_filters,
            "embedding_sorted": embedding_sorted,
            "embed_error":      embed_error,
            "server_url":       server_url,
            "image_embedding":  image_embedding,
        }
        st.session_state.df = df
        st.session_state.page = "results"
        st.rerun()
