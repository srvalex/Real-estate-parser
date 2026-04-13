import streamlit as st
import os
import pandas as pd
import time
from utils import prepare_dataframe, apply_filters, apply_ai_scores
from components.results import render_property_cards
from nlp_filters import extract_filters, get_olx_keywords, apply_description_filters
from scrapers import SCRAPERS

def _inject_olx_keywords(urls: list[str], keywords: list[str]) -> list[str]:
    """Insert a /q-keyword1-keyword2/ path segment into each OLX URL."""
    if not keywords:
        return urls
    q_string = "q-" + "-".join(k.strip() for k in keywords if k.strip())
    new_urls = []
    for url in urls:
        if "?" in url:
            base, query_str = url.split("?", 1)
            base = base if base.endswith("/") else base + "/"
            new_urls.append(f"{base}{q_string}/?{query_str}")
        else:
            base = url if url.endswith("/") else url + "/"
            new_urls.append(f"{base}{q_string}/")
    return new_urls



def render_home(districts, proximity, server_url, data_dir):
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

            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

            # ── Quick filters ──
            st.markdown('<div class="section-label">Filtre</div>', unsafe_allow_html=True)

            max_price = st.number_input("Preț maxim (€/luna)", min_value=0, max_value=10000, value=0, step=50, help="Leave at 0 to skip")
            rooms = "Any"

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
            pages = st.number_input("Pages per site", min_value=1, max_value=5, value=1)

            # ── Build search URLs via scraper registry ────────────────────────
            scrape_jobs = []
            for scraper in SCRAPERS.values():
                urls = set(scraper.build_search_urls(final_selection, districts, max_price, full_sectors=full_sectors, partial_by_sector=partial_by_sector))
                if proximity_selection:
                    # Proximity neighbours always get per-neighbourhood URLs
                    urls |= set(scraper.build_search_urls(
                        proximity_selection, districts, max_price, per_neighbourhood=True
                    ))
                scrape_jobs.append({
                    "platform_id": scraper.platform_id,
                    "urls":        list(urls),
                    "pages":       pages,
                })
            scrape_config = {"jobs": scrape_jobs, "pages": pages}

            # ── Debug: show generated URLs as toasts ──────────────────────────
            with st.expander("🔗 Generated search URLs", expanded=False):
                for job in scrape_jobs:
                    st.markdown(f"**{job['platform_id'].upper()}** — {len(job['urls'])} URL(s)")
                    for url in job["urls"]:
                        st.code(url, language=None)

            search_mode = st.radio(
                "Search mode",
                options=["⚡ Cached", "🔀 Cached + Scrape", "🕷️ Scrape only"],
                index=0,
                horizontal=True,
                help="Cached = instant results from saved database · Scrape only = live scrape, no cache · Both = combine",
            )
            live_scrape = search_mode != "⚡ Cached"
            scrape_only = search_mode == "🕷️ Scrape only"

            st.caption("✅ Local AI model ready")

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

        import sys
        import importlib
        sys.path.insert(0, data_dir)

        df = None

        # ── Inject OLX keywords into scrape jobs ─────────────────────────────
        if live_scrape:
            url_filters = get_olx_keywords(spacy_filters)
            if url_filters:
                for job in scrape_config.get("jobs", []):
                    if job["platform_id"] == "olx":
                        job["urls"] = _inject_olx_keywords(job["urls"], url_filters)

        # ── Fast path: query Firestore (skipped in scrape-only mode) ─────────
        if not scrape_only:
            with st.spinner("⚡ Loading listings from database…"):
                from firebase_utils import query_listings_by_district
                records = query_listings_by_district(final_selection)

            if records:
                df = prepare_dataframe(pd.DataFrame(records))
                df = apply_filters(df, max_price, rooms)
                st.toast(f"⚡ {len(df)} listings loaded from database", icon="✅")
            else:
                st.warning("No saved listings found for the selected zones. Falling back to live scraping.")

        if not scrape_only and (df is None or df.empty):
            st.error("No listings found. Try different zones or enable live scraping.")
            st.stop()

        embedding_sorted = False
        embed_error      = None

        if scrape_only:
            # Navigate straight to results — scraping and ranking happen there
            st.session_state.search_params = {
                "vibe":             vibe,
                "max_price":        max_price,
                "rooms":            rooms,
                "spacy_filters":    spacy_filters,
                "embedding_sorted": False,
                "embed_error":      None,
                "scrape_config":    scrape_config,
                "pages_scraped":    scrape_config.get("pages", 1) if scrape_config else 0,
                "server_url":       server_url,
                "data_dir":         data_dir,
                "pending_scrape":   True,
            }
            st.session_state.df = pd.DataFrame()
            st.session_state.page = "results"
            st.rerun()

        # ── Cached / Cached+Scrape: show results immediately then rank ────────
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

        if vibe.strip() and url_col:
            df, embedding_sorted, embed_error = apply_ai_scores(df, vibe, server_url, url_col, skip_embed=True, spacy_filters=spacy_filters)

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
            "spacy_filters":    spacy_filters,
            "embedding_sorted": embedding_sorted,
            "embed_error":      embed_error,
            "scrape_config":    scrape_config,
            "pages_scraped":    scrape_config.get("pages", 1) if scrape_config else 0,
            "server_url":       server_url,
            "data_dir":         data_dir,
            "pending_scrape":   live_scrape and bool(scrape_config and any(j["urls"] for j in scrape_config.get("jobs", []))),
        }
        st.session_state.df = df
        st.session_state.page = "results"
        st.rerun()
