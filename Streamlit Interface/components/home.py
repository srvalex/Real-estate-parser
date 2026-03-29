import streamlit as st
import os
import pandas as pd
import time
from utils import prepare_dataframe, apply_filters, to_storia_slug, to_olx_slug, apply_ai_scores
from components.results import render_property_cards
from ollama_parser import check_server
from nlp_filters import extract_filters, get_olx_keywords, apply_description_filters

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

            c1, c2 = st.columns(2)
            with c1:
                max_price = st.number_input("Preț maxim (€/luna)", min_value=0, max_value=10000, value=0, step=50, help="Leave at 0 to skip")
            with c2:
                rooms = st.selectbox("Număr de camere", ["Any", "1", "2", "3", "4+"])

            # ── Zone selector ──
            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
            st.markdown('<div class="section-label">Select Locations</div>', unsafe_allow_html=True)

            storia_urls = set()
            olx_urls = set()
            final_selection = []

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
                    final_selection.extend(neighborhoods)
                    olx_id = (sector_num * 2) - 1
                    olx_urls.add(f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/?currency=EUR&search%5Bdistrict_id%5D={olx_id}")
                    storia_urls.add(f"https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti/sectorul-{sector_num}?ownerTypeSingleSelect=ALL&limit=48")
                elif selected_in_district:
                    final_selection.extend(selected_in_district)
                    for n in selected_in_district:
                        storia_urls.add(f"https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti/sectorul-{sector_num}/{to_storia_slug(n)}?ownerTypeSingleSelect=ALL&limit=48")
                        olx_urls.add(f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/{to_olx_slug(n)}/?currency=EUR&search%5Bdistrict_id%5D={(sector_num * 2) - 1}")

            # ── Proximity & Page Config ──
            use_proximity = st.toggle("🔍 Activare Proximity Search", value=False)

            if use_proximity and final_selection:
                for area in final_selection:
                    for neighbor in proximity.get(area, []):
                        for d_name, d_list in districts.items():
                            if neighbor in d_list:
                                s_num = int(d_name.split(" ")[1])
                                storia_urls.add(f"https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti/sectorul-{s_num}/{to_storia_slug(neighbor)}?ownerTypeSingleSelect=ALL&limit=48")
                                olx_urls.add(f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/{to_olx_slug(neighbor)}/?currency=EUR&search%5Bdistrict_id%5D={(s_num * 2) - 1}")

            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
            sc1, sc2 = st.columns(2)
            with sc1:
                olx_pages = st.number_input("OLX pages", min_value=1, max_value=5, value=1)
            with sc2:
                storia_pages = st.number_input("Storia pages", min_value=1, max_value=5, value=1)

            if max_price > 0:
                storia_urls = {url + f"&priceMax={max_price}" for url in storia_urls}
                olx_urls = {url + f"&search%5Bfilter_float_price:to%5D={max_price}" for url in olx_urls}

            scrape_config = {
                "storia_urls": list(storia_urls),
                "olx_urls": list(olx_urls),
                "olx_pages": olx_pages,
                "storia_pages": storia_pages
            }

            live_scrape = st.toggle("🕷️ Include live scraping", value=False,
                                    help="Off = instant results from saved database. On = also scrapes the web for new listings.")

            # ── Colab server URL (Hardcoded) ──
            @st.cache_data(ttl=30, show_spinner=False)
            def _check_server_cached(url):
                return check_server(url)

            is_online = _check_server_cached(server_url)
            if is_online:
                st.caption("✅ Server is reachable")
            else:
                st.caption("⚠️ Server not reachable — make sure Colab is running and DEFAULT_SERVER_URL in ollama_parser.py is currently updated.")

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

        # ── Fast path: query Firestore ──────────────────────────────────────
        with st.spinner("⚡ Loading listings from database…"):
            from firebase_utils import query_listings_by_district
            records = query_listings_by_district(final_selection)

        if records:
            df = prepare_dataframe(pd.DataFrame(records))
            df = apply_filters(df, max_price, rooms)
            st.toast(f"⚡ {len(df)} listings loaded from database", icon="✅")
        else:
            st.warning("No saved listings found for the selected zones. Falling back to live scraping.")

        # ── Prepare scrape config with keyword injection (used later if live_scrape) ──
        if live_scrape and scrape_config.get("olx_urls"):
            url_filters = get_olx_keywords(spacy_filters)
            if url_filters:
                scrape_config["olx_urls"] = _inject_olx_keywords(scrape_config["olx_urls"], url_filters)

        if df is None or df.empty:
            st.error("No listings found. Try different zones or enable live scraping.")
            st.stop()

        # ── Description-level hard exclusions ────────────────────────────────
        if spacy_filters:
            df, excluded_count, exclusion_summary = apply_description_filters(df, spacy_filters)
            if excluded_count:
                labels = {"PET_FRIENDLY": "nu acceptă animale", "HAS_PARKING": "fără parcare",
                          "HAS_BALCONY": "fără balcon", "FURNISHED": "nemobilat",
                          "HAS_HEATING_UNIT": "fără centrală"}
                reasons = ", ".join(labels.get(k, k) for k in exclusion_summary)
                st.toast(f"🚫 {excluded_count} listings removed ({reasons})", icon="🚫")

        # ── Show results immediately, then rank with AI ────────────────────────
        embedding_sorted = False
        embed_error      = None
        url_col          = "url" if "url" in df.columns else ("link" if "link" in df.columns else None)

        live_status = st.empty()
        live_cards  = st.empty()

        live_status.info(f"⚡ Found **{len(df)}** listings — running AI ranking…")
        with live_cards.container():
            render_property_cards(df)

        if vibe.strip() and url_col:
            df, embedding_sorted, embed_error = apply_ai_scores(df, vibe, server_url, url_col, skip_embed=not live_scrape, spacy_filters=spacy_filters)

            if embedding_sorted:
                live_status.success(f"🎯 AI ranked **{len(df)}** listings — navigating to results…")
                with live_cards.container():
                    render_property_cards(df)
                time.sleep(1.5)
            elif embed_error:
                st.toast(f"⚠️ AI ranking skipped: {embed_error}", icon="⚠️")
                live_status.warning("⚠️ AI server unreachable — showing unscored results.")
            else:
                st.toast("⚠️ AI server returned no ranked results.", icon="⚠️")
                live_status.warning("⚠️ No AI scores returned — showing unordered results.")

        st.session_state.search_params = {
            "vibe":             vibe,
            "max_price":        max_price,
            "rooms":            rooms,
            "spacy_filters":    spacy_filters,
            "embedding_sorted": embedding_sorted,
            "embed_error":      embed_error,
            "scrape_config":    scrape_config,
            "pages_scraped":    scrape_config.get("olx_pages", 1) if scrape_config else 0,
            "server_url":       server_url,
            "data_dir":         data_dir,
            "pending_scrape":   live_scrape and bool(scrape_config and scrape_config.get("olx_urls")),
        }
        st.session_state.df = df
        st.session_state.page = "results"
        st.rerun()
