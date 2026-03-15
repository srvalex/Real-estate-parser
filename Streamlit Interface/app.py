import streamlit as st
import os
from utils import load_geo_data
from styles import inject_custom_css
from components.home import render_home
from components.results import render_results
from ollama_parser import DEFAULT_SERVER_URL

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
DATA_DIR = os.path.join(os.path.dirname(__file__), "..")
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
    render_home(districts, proximity, DEFAULT_SERVER_URL, DATA_DIR)
elif st.session_state.page == "results":
    render_results()
