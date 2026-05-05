import streamlit as st
import os
import sys
_HERE = os.path.dirname(os.path.abspath(__file__))

# Project root (scrapers/, extractor.py, db_utils.py)
DATA_DIR = os.path.join(_HERE, "..")
if DATA_DIR not in sys.path:
    sys.path.insert(0, DATA_DIR)

# Streamlit Interface subfolders
for _sub in ("embedders", "pipeline", "static"):
    _p = os.path.join(_HERE, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils import load_geo_data
from styles import inject_custom_css
from components.home import render_home
from components.results import render_results
from components.analytics import render_analytics
from local_embedder import DEFAULT_SERVER_URL

# ─────────────────────────────────────────────
#  Page config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Property Explorer",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────
#  Shared CSS
# ─────────────────────────────────────────────
inject_custom_css()

# ─────────────────────────────────────────────
#  Data helpers
# ─────────────────────────────────────────────

districts, proximity = load_geo_data()

# ─────────────────────────────────────────────
#  Session state init
# ─────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "home"
if "search_params" not in st.session_state:
    st.session_state.search_params = {}

# ─────────────────────────────────────────────
#  Routing
# ─────────────────────────────────────────────
if st.session_state.page == "home":
    render_home(districts, proximity, DEFAULT_SERVER_URL)
elif st.session_state.page == "results":
    render_results()
elif st.session_state.page == "analytics":
    render_analytics()
