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

from rrf import rrf_fuse

# get_ron_to_eur_rate / price_in_eur live in db_utils.py, not here -- that
# module is the Streamlit-independent, foundational layer (also used by
# crawler.py and, per MIGRATION_PLAN.md, the future API). Defining live-rate
# fetching in this Streamlit-coupled file and having db_utils reach into it
# would tie the crawler and the future API to a Streamlit dependency they
# must never need.
from db_utils import get_ron_to_eur_rate, price_in_eur

# apply_filters / apply_ai_scores / apply_price_fairness now live in
# pipeline_core.py (repo root) — the Streamlit-free version shared with
# api/main.py, per MIGRATION_PLAN.md Phase 1. This module keeps its own
# public apply_filters/apply_ai_scores/apply_price_fairness names (home.py
# imports them from here) as thin wrappers: apply_filters is a pure
# re-export (no Streamlit coupling to begin with); apply_ai_scores and
# apply_price_fairness re-add the Streamlit-specific pieces (the cached
# local embedder, the cached price-stats fetch) that pipeline_core.py
# deliberately takes as injected parameters instead of owning itself.
import pipeline_core

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

def safe_str(val):
    return "" if pd.isna(val) else str(val).strip()

# prepare_dataframe / parse_price / parse_rooms now live in pipeline_core.py —
# no Streamlit coupling in their bodies to begin with, so these are plain
# re-exports (same function objects, same patch targets for existing tests
# that patch db_utils.get_ron_to_eur_rate further down the call chain).
prepare_dataframe = pipeline_core.prepare_dataframe
parse_price = pipeline_core.parse_price
parse_rooms = pipeline_core.parse_rooms

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
    """Apply price, room count, area and property-type filters. See pipeline_core.py."""
    return pipeline_core.apply_filters(df, max_price, sel_rooms, min_sqm, max_sqm, property_types)

def apply_ai_scores(df: pd.DataFrame, vibe: str, server_url: str, url_col: str, skip_embed: bool = False, spacy_filters: dict = None, image_embedding: list = None):
    """Re-sort df by AI similarity score (RRF text+image fusion). See pipeline_core.py.

    server_url/skip_embed/spacy_filters are accepted (unused) only to keep
    this wrapper's external signature identical for existing callers
    (home.py, tests) — pipeline_core.apply_ai_scores doesn't take them,
    confirmed unused inside the function body (BUGS.md "Lower priority").
    embed_query stays a module-level name here (imported above from
    local_embedder) rather than passed in from home.py, so patching it at
    this module (`pipeline_utils.embed_query`) — as the existing ranking
    tests do — still works exactly as before the relocation.
    """
    return pipeline_core.apply_ai_scores(df, vibe, url_col, embed_query=embed_query, image_embedding=image_embedding)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_price_stats() -> dict:
    try:
        import db_utils
        return db_utils.get_price_stats()
    except Exception:
        return {}


def apply_price_fairness(df: pd.DataFrame) -> pd.DataFrame:
    """Add a 'price_fairness' column: '+12% vs avg', '-8% vs avg', or None.
    See pipeline_core.py for the labelling logic; this wrapper only supplies
    the Streamlit-cached price_stats fetch (_cached_price_stats, unchanged).
    """
    return pipeline_core.apply_price_fairness(df, price_stats=_cached_price_stats())


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
