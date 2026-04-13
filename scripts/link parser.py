import streamlit as st
import json
import pandas as pd
import sqlite3

# --- LOAD DATA ---
def load_data():
    with open('districts.json', 'r', encoding='utf-8') as f:
        districts = json.load(f)
    with open('proximity.json', 'r', encoding='utf-8') as f:
        proximity = json.load(f)
    return districts, proximity

districts, proximity = load_data()


# --- Helpers ---
def to_storia_slug(text):
    return text.lower().replace(" ", "-").replace("ă", "a").replace("î", "i").replace("â", "a").replace("ș", "s").replace("ț", "t")

def to_olx_slug(text):
    # OLX specifically uses q-name for keyword search
    # We keep spaces as hyphens
    clean_name = text.lower().replace(" ", "-").replace("ă", "a").replace("î", "i").replace("â", "a").replace("ș", "s").replace("ț", "t")
    return f"q-{clean_name}"

# Using sets to ensure we don't have duplicates
storia_urls = set()
olx_urls = set()
final_selection = []

# --- THE UI TREE ---
with st.expander("📍 Alege zona", expanded=True):
    for district_name, neighborhoods in districts.items():
        sector_num = int(district_name.split(" ")[1])
        
        with st.container(border=True):
            cols = st.columns([1, 4])
            with cols[0]:
                select_all = st.checkbox(f"Tot {district_name}", key=f"all_{district_name}")
            with cols[1]:
                selected_in_district = st.multiselect(
                    f"Selecție manuală {district_name}",
                    options=neighborhoods,
                    default=neighborhoods if select_all else [],
                    key=f"select_{district_name}",
                    label_visibility="collapsed"
                )
                final_selection.extend(selected_in_district)

        # --- REFINED GENERATION LOGIC ---
        if select_all:
            # 1. Sector-level Search (Broad)
            olx_id = (sector_num * 2) - 1
            olx_urls.add(f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/?currency=EUR&search%5Bdistrict_id%5D={olx_id}")
            storia_urls.add(f"https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti/sectorul-{sector_num}?ownerTypeSingleSelect=ALL&limit=48")
            
        elif selected_in_district:
            # 2. Neighborhood-level Search (Specific)
            for neighborhood in selected_in_district:
                # Storia
                st_slug = to_storia_slug(neighborhood)
                storia_urls.add(f"https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti/sectorul-{sector_num}/{st_slug}?ownerTypeSingleSelect=ALL&limit=48")
                
                # ADVANCED OLX Logic
                ox_slug = to_olx_slug(neighborhood)
                olx_id = (sector_num * 2) - 1
                # Structure: .../bucuresti/{q-slug}/?currency=EUR&search[district_id]={id}
                olx_urls.add(f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/{ox_slug}/?currency=EUR&search%5Bdistrict_id%5D={olx_id}")

# --- Proximity Logic (updated to use advanced OLX) ---
# --- Proximity Toggle ---
st.divider()
use_proximity = st.toggle("🔍 Activare Proximity Search", value=False)


if use_proximity and final_selection:
    for area in final_selection:
        neighbors = proximity.get(area, [])
        for n in neighbors:
            for d_name, d_list in districts.items():
                if n in d_list:
                    s_num = int(d_name.split(" ")[1])
                    o_id = (s_num * 2) - 1
                    # Use Advanced Slug for proximity as well
                    olx_urls.add(f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/{to_olx_slug(n)}/?currency=EUR&search%5Bdistrict_id%5D={o_id}")
                    storia_urls.add(f"https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti/sectorul-{s_num}/{to_storia_slug(n)}?ownerTypeSingleSelect=ALL&limit=48")

if use_proximity and final_selection:
    for area in final_selection:
        neighbors = proximity.get(area, [])
        for n in neighbors:
            for d_name, d_list in districts.items():
                if n in d_list:
                    s_num = int(d_name.split(" ")[1])
                    storia_urls.add(f"https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti/sectorul-{s_num}/{to_slug(n)}?ownerTypeSingleSelect=ALL&limit=48")
                    olx_urls.add(f"https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/?search%5Bdistrict_id%5D={(s_num * 2) - 1}&currency=EUR")

# --- DEBUG & RUN ---
if st.button("🚀 Pornire Extracție", use_container_width=True):
    # Convert sets back to lists for processing
    storia_final = list(storia_urls)
    olx_final = list(olx_urls)

    # --- THE DEBUG BLOCK ---
    print("\n" + "="*50)
    print("🛠️  DEBUG: TARGET SEARCH URLS")
    print(f"📅 Timestamp: {pd.Timestamp.now()}")
    print("-" * 50)
    print(f"🔷 STORIA ({len(storia_final)}):")
    for url in storia_final: print(f"  > {url}")
    print(f"\n🔶 OLX ({len(olx_final)}):")
    for url in olx_final: print(f"  > {url}")
    print("="*50 + "\n")


    # Ready for pipeline:
    # run_pipeline(storia_urls=storia_final, olx_urls=olx_final)
