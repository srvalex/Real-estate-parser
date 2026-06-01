import streamlit as st
import os
import pandas as pd
import time
from utils import prepare_dataframe, apply_filters, apply_ai_scores, apply_price_fairness
from components.results import render_property_cards
from nlp_filters import extract_filters, apply_description_filters


def render_home(districts, proximity, server_url):

    # Hero
    st.markdown("""
    <div class="home-hero">
        <h1>Agentul tău imobiliar inteligent</h1>
        <p>Doar spune-i ce cauti la o locuință, iar el îți va găsi cele mai potrivite anunțuri</p>
    </div>
    """, unsafe_allow_html=True)

    # Search card
    with st.container():
        _, center, _ = st.columns([1, 2.5, 1])
        with center:

            # ── Vibe ──
            st.markdown('<div class="vibe-label"> Ce fel de locuință cauți?</div>', unsafe_allow_html=True)
            st.markdown('<div class="vibe-hint">Descrie cu cuvintele tale — dotări, atmosferă, preferințe. ex. <em>"bucătărie mare, liniștit, aproape de metrou, renovat"</em></div>', unsafe_allow_html=True)
            vibe = st.text_area(
                label="vibe",
                placeholder="ex. apartament luminos, bucătărie modernă, liniștit, parc în apropiere, renovat recent...",
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
            _TEMPLATE_LABELS = {
                "template_1": "Mobilat modern",
                "template_2": "Clasic, luxos",
                "template_3": "Primitor",
                "template_4": "Bloc comunist",
            }
            if _template_files:
                with st.expander("🖼️ Aspect vizual (opțional)", expanded=False):
                    st.caption("Selectează fotografii de referință — rezultatele vor fi ordonate după similaritate vizuală.")
                    cols = st.columns(2)
                    for i, fname in enumerate(_template_files):
                        fpath = os.path.join(_TEMPLATE_DIR, fname)
                        stem = os.path.splitext(fname)[0]
                        label = _TEMPLATE_LABELS.get(stem, stem.replace("_", " ").replace("-", " ").title())
                        with cols[i % 2]:
                            st.image(fpath, use_container_width=True)
                            if st.checkbox(label, key=f"tpl_{fname}"):
                                selected_templates.append(fpath)

            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

            # ── Quick filters ──
            st.markdown('<div class="section-label">Filtre</div>', unsafe_allow_html=True)

            max_price = st.number_input("Preț maxim (€/lună)", min_value=0, max_value=10000, value=0, step=50, help="Lasă 0 pentru fără limită")

            fcol1, fcol2 = st.columns(2)
            with fcol1:
                rooms = st.selectbox(
                    "Număr camere",
                    options=["Orice", "1", "2", "3", "4", "5+"],
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
            st.markdown('<div class="section-label">Zonă de căutare</div>', unsafe_allow_html=True)

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
            use_proximity = st.toggle("🔍 Include cartiere vecine", value=False)
            proximity_selection = []
            if use_proximity and final_selection:
                for area in final_selection:
                    for neighbor in proximity.get(area, []):
                        if neighbor not in final_selection and neighbor not in proximity_selection:
                            proximity_selection.append(neighbor)

            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)


            st.markdown('<br>', unsafe_allow_html=True)

            # ── CTA ──
            _, btn_col, _ = st.columns([1, 2, 1])
            with btn_col:
                search_clicked = st.button("🔍  Caută locuințe", use_container_width=True)

            st.markdown('</div>', unsafe_allow_html=True)

        # ── Instant local NLP extraction (no network call) ──
        spacy_filters = {}
        if vibe.strip():
            spacy_filters = extract_filters(vibe)
        
    # Handle search
    if search_clicked:
        if not final_selection:
            st.error("Te rugăm să selectezi cel puțin o zonă de căutare.")
            st.stop()

        df = None

        # ── NLP auto-fill: use detected values for any field left at default ──
        # Form always wins; NLP only fills in fields the user didn't touch.
        _ALL_PTYPES = ["Apartament", "Garsoniera", "Studio", "Casa/Vila"]
        _nlp_filled = []

        if rooms == "Orice" and spacy_filters.get("ROOM_COUNT"):
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
        all_districts = final_selection + proximity_selection
        with st.spinner("⚡ Se încarcă anunțurile..."):
            from db_utils import query_listings_by_district
            records = query_listings_by_district(all_districts)

        if proximity_selection:
            st.toast(f"🔍 S-au adăugat {len(proximity_selection)} cartiere învecinate", icon="🔍")

        if records:
            df = prepare_dataframe(pd.DataFrame(records))
            df = apply_filters(df, max_price, rooms, min_sqm, max_sqm, property_types or None)
            df = apply_price_fairness(df)
            st.toast(f"⚡ {len(df)} anunțuri încărcate", icon="✅")
        else:
            st.warning("Nu s-au găsit anunțuri salvate pentru zonele selectate.")

        if df is None or df.empty:
            st.error("Nu s-au găsit anunțuri. Încearcă alte zone.")
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
                with st.spinner(f"Se procesează {len(missing)} fotografii noi..."):
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
                st.toast(f"🖼️ {len(embeddings)} fotografii de referință procesate", icon="✅")
            else:
                st.toast("⚠️ Nu s-au putut procesa fotografiile — se folosește doar căutarea textuală", icon="⚠️")

        if spacy_filters:
            df, excluded_count, exclusion_summary = apply_description_filters(df, spacy_filters)
            if excluded_count:
                labels = {"PET_FRIENDLY": "nu acceptă animale", "HAS_PARKING": "fără parcare",
                          "HAS_BALCONY": "fără balcon", "FURNISHED": "nemobilat",
                          "HAS_HEATING_UNIT": "fără centrală"}
                reasons = ", ".join(labels.get(k, k) for k in exclusion_summary)
                st.toast(f"🚫 {excluded_count} anunțuri eliminate ({reasons})", icon="🚫")

        url_col = "url" if "url" in df.columns else ("link" if "link" in df.columns else None)

        live_status = st.empty()
        live_cards  = st.empty()

        live_status.info(f"⚡ S-au găsit **{len(df)}** anunțuri — se aplică scorul AI…")
        _prox_set = set(proximity_selection) or None
        with live_cards.container():
            render_property_cards(df, proximity_districts=_prox_set)

        if (vibe.strip() or image_embedding) and url_col:
            df, embedding_sorted, embed_error = apply_ai_scores(
                df, vibe, server_url, url_col,
                skip_embed=True,
                spacy_filters=spacy_filters,
                image_embedding=image_embedding,
            )

            if embedding_sorted:
                live_status.success(f"🎯 AI a ordonat **{len(df)}** anunțuri — se navighează la rezultate…")
                with live_cards.container():
                    render_property_cards(df, proximity_districts=_prox_set)
                time.sleep(1.5)
            elif embed_error:
                st.toast(f"⚠️ Scorul AI a fost omis: {embed_error}", icon="⚠️")
                live_status.warning("⚠️ Scorul AI nu este disponibil — se afișează rezultate neordonate.")
            else:
                live_status.warning("⚠️ Nu s-au obținut scoruri AI — se afișează rezultate neordonate.")

        st.session_state.search_params = {
            "vibe":                vibe,
            "max_price":           max_price,
            "rooms":               rooms,
            "min_sqm":             min_sqm,
            "max_sqm":             max_sqm,
            "property_types":      property_types or None,
            "spacy_filters":       spacy_filters,
            "embedding_sorted":    embedding_sorted,
            "embed_error":         embed_error,
            "server_url":          server_url,
            "image_embedding":     image_embedding,
            "proximity_selection": proximity_selection,
        }
        st.session_state.df = df
        st.session_state.page = "results"
        st.rerun()
