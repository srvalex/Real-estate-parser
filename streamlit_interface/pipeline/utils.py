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

from local_embedder import embed_query

_PROJECT_ROOT = os.path.join(_HERE, "..", "..")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

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
    if "price_numeric" in df.columns:
        df["_price_num"] = pd.to_numeric(df["price_numeric"], errors="coerce")
    else:
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

def apply_filters(
    df: pd.DataFrame,
    max_price: int,
    sel_rooms: str,
    min_sqm: int = 0,
    max_sqm: int = 0,
    property_types: list[str] | None = None,
) -> pd.DataFrame:
    """Apply price, room count, area and property-type filters."""
    if df.empty:
        return df

    if max_price and max_price > 0 and "_price_num" in df.columns:
        has_price = df["_price_num"].notna()
        df = df[~has_price | (df["_price_num"] <= max_price)]

    if sel_rooms != "Any" and "_rooms_num" in df.columns:
        has_rooms = df["_rooms_num"].notna()
        if sel_rooms == "5+":
            df = df[~has_rooms | (df["_rooms_num"] >= 5)]
        else:
            df = df[~has_rooms | (df["_rooms_num"] == int(sel_rooms))]

    if (min_sqm or max_sqm) and "area_sqm" in df.columns:
        sqm = pd.to_numeric(df["area_sqm"], errors="coerce")
        has_sqm = sqm.notna()
        if min_sqm and min_sqm > 0:
            df = df[~has_sqm | (sqm >= min_sqm)]
        if max_sqm and max_sqm > 0:
            df = df[~has_sqm | (sqm <= max_sqm)]

    if property_types and "property_type" in df.columns:
        known = df["property_type"].notna()
        df = df[~known | df["property_type"].isin(property_types)]

    return df

def apply_ai_scores(df: pd.DataFrame, vibe: str, server_url: str, url_col: str, skip_embed: bool = False, spacy_filters: dict = None, image_embedding: list = None):
    """Re-sort df by AI similarity score using Reciprocal Rank Fusion (RRF).

    Two independent search paths are run against Supabase pgvector:
      - Text:  paraphrase-multilingual-MiniLM-L12-v2 (384-dim) → match_listings RPC
      - Image: CLIP ViT-B/32 text tower (512-dim)              → match_listings_by_image RPC

    Because the two models live in different vector spaces with different score
    distributions, their raw cosine similarities cannot be meaningfully averaged.
    RRF fuses them via ordinal rank instead of raw score:

        rrf(url) = W_TEXT  / (K + text_rank(url))
                 + W_IMAGE / (K + image_rank(url))

    K=60 (standard constant) dampens the advantage of rank-1 over rank-2 while
    still strongly preferring anything near the top of either list. URLs absent
    from a ranked list contribute 0 for that component (infinite rank).

    Supports three modes:
      - text only   (image_embedding=None, vibe set)
      - image only  (image_embedding set,  vibe empty)
      - both        (image_embedding set,  vibe set) → RRF fusion
    Returns (df_sorted, embedding_sorted: bool, embed_error: str | None).
    """
    hard_filter_keys = [k for k, v in (spacy_filters or {}).items() if v is True]
    embed_error = None
    has_vibe  = bool(vibe and vibe.strip())
    has_image = bool(image_embedding)

    if not has_vibe and not has_image:
        return df, False, None

    # ── Text search via pgvector (Supabase match_listings RPC) ───────────────
    text_scores: dict = {}
    if has_vibe:
        try:
            q_embedding = embed_query(vibe)
            if q_embedding:
                import db_utils
                text_scores = db_utils.search_by_text_vibe(
                    q_embedding,
                    limit=min(max(len(df) * 3, 200), 1000),
                )
                if not text_scores:
                    embed_error = "No pgvector matches — run scripts/backfill_embeddings.py to populate embeddings"
            else:
                embed_error = "Failed to embed query text"
        except Exception as e:
            embed_error = f"pgvector search error: {e}"

    # ── Image scores via Supabase (image_embedding column) ───────────────────
    # Cover photo CLIP embeddings are stored in listings.image_embedding (512-dim).
    # For template photos: use the pre-computed embedding directly.
    # For text vibe: encode with the local CLIP text tower first.
    image_scores: dict = {}
    img_error = None
    try:
        import db_utils as _db
        limit = min(3000, len(df) * 20)
        clip_emb = None
        if has_image:
            clip_emb = image_embedding
        elif has_vibe:
            from image_embedder import clip_encode_text
            clip_emb = clip_encode_text(vibe)
        if clip_emb:
            image_scores = _db.search_by_image_embedding(clip_emb, limit=limit)
    except Exception as e:
        img_error = str(e)
    if img_error and not embed_error:
        embed_error = img_error

    # ── Bail if we have nothing to rank with ──────────────────────────────────
    if not text_scores and not image_scores:
        return df, False, embed_error

    # ── Reciprocal Rank Fusion ────────────────────────────────────────────────
    # Raw cosine similarities from ST (384-dim) and CLIP (512-dim) are not
    # comparable — different models, different score distributions. RRF fuses
    # them purely by ordinal rank, making the weights scale-independent.
    #
    #   rrf(url) = W_TEXT / (K + text_rank) + W_IMAGE / (K + image_rank)
    #
    # Tune W_TEXT / W_IMAGE to shift emphasis between description semantics
    # and visual appearance. K=60 is the standard dampening constant.
    _K       = 60
    _W_TEXT  = 0.3
    _W_IMAGE = 0.7

    def _rank_map(scores: dict) -> dict:
        return {
            url: rank
            for rank, (url, _) in enumerate(
                sorted(scores.items(), key=lambda x: x[1], reverse=True), start=1
            )
        }

    text_ranks  = _rank_map(text_scores)  if text_scores  else {}
    image_ranks = _rank_map(image_scores) if image_scores else {}

    all_urls = set(df[url_col].dropna())
    final_scores: dict = {}
    for url in all_urls:
        t_rank = text_ranks.get(url)
        i_rank = image_ranks.get(url)
        score  = 0.0
        if t_rank is not None:
            score += _W_TEXT  / (_K + t_rank)
        if i_rank is not None:
            score += _W_IMAGE / (_K + i_rank)
        if score > 0:
            final_scores[url] = score

    if not final_scores:
        return df, False, embed_error

    # Normalise to [0, 1] so the UI percentage is meaningful.
    # RRF raw values are tiny (~0.016 max), so without this the badge always reads "1%".
    # Dividing by the top score makes the best result 100% and others proportional to it.
    _max = max(final_scores.values())
    if _max > 0:
        final_scores = {url: s / _max for url, s in final_scores.items()}

    df["_similarity_score"] = df[url_col].map(final_scores)
    df = df.sort_values("_similarity_score", ascending=False, na_position="last").reset_index(drop=True)
    return df, True, embed_error


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_price_stats() -> dict:
    try:
        import db_utils
        return db_utils.get_price_stats()
    except Exception:
        return {}


def apply_price_fairness(df: pd.DataFrame) -> pd.DataFrame:
    """Add a 'price_fairness' column: '+12% vs avg', '-8% vs avg', or None.

    Labels are suppressed when:
    - district or rooms is missing
    - fewer than 5 comparables exist in that bucket
    - price is within ±5% of the average (too close to call)
    """
    stats = _cached_price_stats()
    df = df.copy()
    if not stats or df.empty:
        df["price_fairness"] = None
        return df

    THRESHOLD = 5.0
    labels = []
    for _, row in df.iterrows():
        district = str(row.get("district") or "").strip()
        rooms    = str(row.get("rooms") or "").strip()
        price    = row.get("price_numeric")

        if not district or not rooms or price is None or str(price) in ("", "nan"):
            labels.append(None)
            continue

        bucket = stats.get((district, rooms))
        if not bucket:
            labels.append(None)
            continue

        try:
            pct = (float(price) - bucket["avg"]) / bucket["avg"] * 100
        except (TypeError, ZeroDivisionError):
            labels.append(None)
            continue

        if abs(pct) < THRESHOLD:
            labels.append(None)
        elif pct > 0:
            labels.append(f"+{pct:.0f}% vs avg")
        else:
            labels.append(f"{pct:.0f}% vs avg")

    df["price_fairness"] = labels
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
