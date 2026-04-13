import os
import sys
import streamlit as st
import pandas as pd
import json
import re

# embedders/ lives one level up from pipeline/
_HERE = os.path.dirname(os.path.abspath(__file__))
_EMBEDDERS = os.path.join(_HERE, "..", "embedders")
if _EMBEDDERS not in sys.path:
    sys.path.insert(0, _EMBEDDERS)

from local_embedder import embed_listings, search_by_vibe

_DATA_DIR = os.path.join(_HERE, "..")   # Streamlit Interface/

@st.cache_data
def load_geo_data():
    with open(os.path.join(_DATA_DIR, 'districts.json'), 'r', encoding='utf-8') as f:
        districts = json.load(f)
    with open(os.path.join(_DATA_DIR, 'proximity.json'), 'r', encoding='utf-8') as f:
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

def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Strip unnamed columns and add numeric helper columns for price and rooms."""
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    price_col = "rent" if "rent" in df.columns else "price" if "price" in df.columns else None
    df["_price_num"] = df[price_col].apply(parse_price) if price_col else None
    rooms_col = "rooms" if "rooms" in df.columns else ("rooms_num" if "rooms_num" in df.columns else None)
    df["_rooms_num"] = df[rooms_col].apply(parse_rooms) if rooms_col else None
    return df

@st.cache_data(show_spinner=False)
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = prepare_dataframe(df)
    df["platform"] = "Storia"
    return df

def apply_filters(df: pd.DataFrame, max_price: int, sel_rooms: str) -> pd.DataFrame:
    """Apply price and room count filters to the listings DataFrame."""
    if df.empty:
        return df

    if max_price and max_price > 0 and "_price_num" in df.columns:
        has_price = df["_price_num"].notna()
        df = df[~has_price | (df["_price_num"] <= max_price)]

    if sel_rooms != "Any" and "_rooms_num" in df.columns:
        has_rooms = df["_rooms_num"].notna()
        if sel_rooms == "4+":
            df = df[~has_rooms | (df["_rooms_num"] >= 4)]
        else:
            df = df[~has_rooms | (df["_rooms_num"] == int(sel_rooms))]

    return df

def apply_ai_scores(df: pd.DataFrame, vibe: str, server_url: str, url_col: str, skip_embed: bool = False, spacy_filters: dict = None, image_embedding: list = None):
    """Re-sort df by AI similarity score.
    Supports three modes:
      - text only (image_embedding=None, vibe set)
      - image only (image_embedding set, vibe empty)
      - both (image_embedding set, vibe set) → weighted fusion
    Returns (df, embedding_sorted, embed_error).
    """
    hard_filter_keys = [k for k, v in (spacy_filters or {}).items() if v is True]
    embed_error = None
    has_vibe  = bool(vibe and vibe.strip())
    has_image = bool(image_embedding)

    if not has_vibe and not has_image:
        return df, False, None

    # ── Text embeddings (only when vibe is present) ───────────────────────────
    text_scores: dict = {}
    if has_vibe:
        rows_payload = [
            {
                "description":  str(row.get("description", "") or ""),
                "url":          str(row.get(url_col, "") or ""),
                "hard_filters": hard_filter_keys,
                "soft_filters": [],
            }
            for _, row in df[[url_col, "description"]].fillna("").iterrows()
            if str(row.get("description", "")).strip()
        ]
        if not skip_embed:
            _, embed_error = embed_listings(rows_payload, server_url=server_url)
        matches, search_error = search_by_vibe(
            query=vibe,
            limit=len(rows_payload) or 1,
            url_filters=hard_filter_keys,
            server_url=server_url,
        )
        if search_error and not embed_error:
            embed_error = search_error
        if matches:
            distances = [m["distance"] for m in matches]
            min_d, max_d = min(distances), max(distances)
            d_range = (max_d - min_d) if max_d > min_d else 1.0
            text_scores = {m["url"]: 1.0 - (m["distance"] - min_d) / d_range for m in matches}

    # ── Image scores ──────────────────────────────────────────────────────────
    image_scores: dict = {}
    img_error = None
    try:
        from image_embedder import search_by_text_vibe, search_by_image_embedding
        limit = min(3000, len(df) * 20)
        if has_image:
            image_scores, img_error = search_by_image_embedding(image_embedding, limit=limit)
        elif has_vibe:
            image_scores, img_error = search_by_text_vibe(vibe, limit=limit)
    except Exception as e:
        img_error = str(e)
    if img_error and not embed_error:
        embed_error = img_error

    # ── Bail if we have nothing to rank with ──────────────────────────────────
    if not text_scores and not image_scores:
        return df, False, embed_error

    # ── Fuse scores ───────────────────────────────────────────────────────────
    # image-only: pure image score
    # text-only:  pure text score
    # both:       20% text + 80% image for listings with image embeddings;
    #             text-only for listings without image embeddings (no penalty)
    all_urls = set(df[url_col].dropna())

    final_scores: dict = {}
    for url in all_urls:
        t = text_scores.get(url)
        i = image_scores.get(url)
        if t is not None and i is not None:
            final_scores[url] = 0.2 * t + 0.8 * i
        elif i is not None:
            final_scores[url] = i
        elif t is not None:
            final_scores[url] = t

    if not final_scores:
        return df, False, embed_error

    df["_similarity_score"] = df[url_col].map(final_scores)
    df = df.sort_values("_similarity_score", ascending=False, na_position="last").reset_index(drop=True)
    return df, True, embed_error


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
