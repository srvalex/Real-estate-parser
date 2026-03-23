import streamlit as st
import os
import pandas as pd
from utils import load_csv, to_storia_slug, to_olx_slug, parse_price, parse_rooms
from components.results import render_property_cards
from ollama_parser import check_server, embed_listings, search_by_vibe
from nlp_filters import extract_filters, get_olx_keywords

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
            st.markdown('<div class="section-label">Quick filters</div>', unsafe_allow_html=True)

            c1, c2 = st.columns(2)
            with c1:
                max_price = st.number_input("Max price (€/month)", min_value=0, max_value=10000, value=0, step=50, help="Leave at 0 to skip")
            with c2:
                rooms = st.selectbox("Rooms", ["Any", "1", "2", "3", "4+"])

            # Data source
            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
            st.markdown('<div class="section-label">Data source</div>', unsafe_allow_html=True)

            default_csv = os.path.join(data_dir, "Date Storia Procesate.csv")
            src_tab, scrape_tab = st.tabs(["📂 Use existing CSV", "🕷️ Scrape fresh data"])

            uploaded = None
            scrape_config = None

            with src_tab:
                uploaded = st.file_uploader("Upload a CSV", type=["csv"], label_visibility="collapsed")
                if not uploaded and os.path.exists(default_csv):
                    st.caption(f"📂 No upload? Will use default dataset (`Date Storia Procesate.csv`)")

            with scrape_tab:
                # 1. Hierarchical Neighborhood Selector
                st.markdown('<div class="section-label">Select Locations</div>', unsafe_allow_html=True)
                
                storia_urls = set()
                olx_urls = set()
                final_selection = []

                with st.expander("📍 Alege zona (București)", expanded=False):
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
                                    default=neighborhoods if select_all else [],
                                    key=f"select_{district_name}",
                                    label_visibility="collapsed"
                                )
                                final_selection.extend(selected_in_district)

                        # URL Logic Generation
                        if select_all:
                            olx_id = (sector_num * 2) - 1
                            olx_urls.add(f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/?currency=EUR&search%5Bdistrict_id%5D={olx_id}")
                            storia_urls.add(f"https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti/sectorul-{sector_num}?ownerTypeSingleSelect=ALL&limit=48")
                        elif selected_in_district:
                            for n in selected_in_district:
                                storia_urls.add(f"https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti/sectorul-{sector_num}/{to_storia_slug(n)}?ownerTypeSingleSelect=ALL&limit=48")
                                olx_urls.add(f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/{to_olx_slug(n)}/?currency=EUR&search%5Bdistrict_id%5D={(sector_num * 2) - 1}")

                # 2. Proximity & Page Config
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
                    olx_pages = st.number_input("OLX pages/link", min_value=1, max_value=5, value=1)
                with sc2:
                    storia_pages = st.number_input("Storia pages/link", min_value=1, max_value=5, value=1)

                # Store the generated sets in a dictionary for the search handler
                scrape_config = {
                    "storia_urls": list(storia_urls),
                    "olx_urls": list(olx_urls),
                    "olx_pages": olx_pages,
                    "storia_pages": storia_pages
                }

            # ── Colab server URL (Hardcoded) ──
            is_online = check_server(server_url)
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
        # ── Decide data source ──
        df = None
        if uploaded:
            import io
            df = pd.read_csv(uploaded)
            df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
            price_col = "rent" if "rent" in df.columns else "price" if "price" in df.columns else None
            df["_price_num"] = df[price_col].apply(parse_price) if price_col else None
            df["_rooms_num"] = df["rooms"].apply(parse_rooms) if "rooms" in df.columns else None
            df["platform"] = "Storia"
        elif scrape_config and scrape_config.get("olx_urls"):
            import sys
            import importlib
            sys.path.insert(0, data_dir)
            import extractor
            importlib.reload(extractor)
            from extractor import run_pipeline
            
            url_filters = get_olx_keywords(spacy_filters)

            if url_filters:
                # Build q-keyword1-keyword2 path segment for OLX URL
                q_string = "q-" + "-".join(k.strip() for k in url_filters if k.strip())
                new_olx_urls = []
                for url in scrape_config["olx_urls"]:
                    if "?" in url:
                        base, query_str = url.split("?", 1)
                        base = base if base.endswith("/") else base + "/"
                        new_olx_urls.append(f"{base}{q_string}/?{query_str}")
                    else:
                        base = url if url.endswith("/") else url + "/"
                        new_olx_urls.append(f"{base}{q_string}/")
                scrape_config["olx_urls"] = new_olx_urls
            
            final_olx_url = scrape_config["olx_urls"][0] if scrape_config["olx_urls"] else ""
            
            with st.spinner(f"Scraping results from the web"):
                storia_url = scrape_config["storia_urls"][0] if scrape_config["storia_urls"] else ""
                
                # Placeholder for intermediate UI
                status_container = st.empty()
                cache_preview = st.empty()

                for status, partial_df in run_pipeline(
                    olx_url=final_olx_url,
                    storia_url=storia_url,
                    olx_pages=int(scrape_config["olx_pages"]),
                    storia_pages=int(scrape_config["storia_pages"]),
                    out_csv="results.csv",
                ):
                    if status == "db_cache":
                        status_container.info(f"⚡ Found {len(partial_df)} matching properties in local cache! Scraping new ones in background...")
                        if not partial_df.empty:
                            df = partial_df
                            with cache_preview.container():
                                render_property_cards(partial_df)

                    elif status == "progress":
                        # Append the new records to our running dataframe
                        if df is None:
                            df = partial_df
                        else:
                            df = pd.concat([df, partial_df], ignore_index=True)
                        
                        status_container.info(f"⏳ Dynamic scraping... Extracted {len(df)} listings so far.")
                        with cache_preview.container():
                            render_property_cards(df)
                    
                    elif status == "done":
                        # Use the final combined dataframe directly
                        df = partial_df
                        status_container.success(f"✅ Scraping completed! Total results: {len(df)}")
                        cache_preview.empty() # Clear preview since we move to results page

            price_col = "rent" if "rent" in df.columns else "price" if "price" in df.columns else None
            df["_price_num"] = df[price_col].apply(parse_price) if price_col else None
            df["_rooms_num"] = df["rooms"].apply(parse_rooms) if "rooms" in df.columns else None
        elif os.path.exists(default_csv):
            df = load_csv(default_csv)
        else:
            st.error("No data source found. Upload a CSV or configure scraping.")
            st.stop()

        # ── Show results immediately, then rank with AI ────────────────────────
        embedding_sorted = False
        embed_error      = None
        matches          = []
        url_col          = "url" if "url" in df.columns else ("link" if "link" in df.columns else None)

        # Step 1 — render unscored cards right away so user isn't staring at a spinner
        live_status = st.empty()
        live_cards  = st.empty()

        live_status.info(f"⚡ Found **{len(df)}** listings — running AI ranking…")
        with live_cards.container():
            render_property_cards(df)

        # Step 2 — embed + search (Colab call, may take a few seconds)
        if vibe.strip() and url_col:
            rows_payload = [
                {
                    "description":  str(row.get("description", "") or ""),
                    "url":          str(row.get(url_col, "") or ""),
                    "hard_filters": [],
                    "soft_filters": [],
                }
                for _, row in df[[url_col, "description"]].fillna("").iterrows()
                if str(row.get("description", "")).strip()
            ]

            _, embed_error = embed_listings(rows_payload, server_url=server_url)

            safe_limit = max(1, len(rows_payload))
            matches, search_error = search_by_vibe(
                query=vibe,
                limit=safe_limit,
                server_url=server_url,
            )
            if search_error and not embed_error:
                embed_error = search_error

            # Step 3 — scores arrived: re-sort and update the live card grid
            if matches:
                score_map = {m["url"]: m["distance"] for m in matches}
                df["_similarity_score"] = df[url_col].map(score_map)
                df = df.sort_values(
                    "_similarity_score",
                    ascending=True,
                    na_position="last",
                ).reset_index(drop=True)
                embedding_sorted = True

                live_status.success(f"🎯 AI ranked **{len(matches)}** listings — navigating to results…")
                with live_cards.container():
                    render_property_cards(df)
                import time; time.sleep(1.5)   # let user see ranked cards briefly

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
        }
        st.session_state.df = df
        st.session_state.page = "results"
        st.rerun()
