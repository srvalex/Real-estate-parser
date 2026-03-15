import streamlit as st
import pandas as pd
import json
import re

@st.cache_data
def load_geo_data():
    # Adjust paths if files are in a different folder
    with open('districts.json', 'r', encoding='utf-8') as f:
        districts = json.load(f)
    with open('proximity.json', 'r', encoding='utf-8') as f:
        proximity = json.load(f)
    return districts, proximity

def to_storia_slug(text):
    return text.lower().replace(" ", "-").replace("ă", "a").replace("î", "i").replace("â", "a").replace("ș", "s").replace("ț", "t")

def to_olx_slug(text):
    clean = text.lower().replace(" ", "-").replace("ă", "a").replace("î", "i").replace("â", "a").replace("ș", "s").replace("ț", "t")
    return f"q-{clean}"

def parse_price(val):
    if pd.isna(val): return None
    cleaned = re.sub(r"[^\d.]", "", str(val).replace(" ", ""))
    try: return float(cleaned)
    except ValueError: return None

def parse_rooms(val):
    if pd.isna(val): return None
    m = re.search(r"\d+", str(val))
    return int(m.group()) if m else None

def safe_str(val):
    return "" if pd.isna(val) else str(val).strip()

@st.cache_data(show_spinner=False)
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    price_col = "rent" if "rent" in df.columns else "price" if "price" in df.columns else None
    df["_price_num"] = df[price_col].apply(parse_price) if price_col else None
    df["_rooms_num"] = df["rooms"].apply(parse_rooms) if "rooms" in df.columns else None
    df["platform"]   = "Storia"
    return df

def apply_vibe(df: pd.DataFrame, vibe: str) -> pd.DataFrame:
    if not vibe.strip(): return df
    keywords = [k.strip().lower() for k in re.split(r"[\s,;]+", vibe) if k.strip()]
    if not keywords: return df
    text = (
        df.get("title", pd.Series("", index=df.index)).fillna("") + " " +
        df.get("description", pd.Series("", index=df.index)).fillna("") + " " +
        df.get("location_full_name", pd.Series("", index=df.index)).fillna("") + " " +
        df.get("district", pd.Series("", index=df.index)).fillna("")
    ).str.lower()
    mask = pd.Series([True] * len(df), index=df.index)
    for kw in keywords:
        mask &= text.str.contains(kw, na=False)
    return df[mask]
