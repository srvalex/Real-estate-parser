import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.join(_HERE, "..")          # streamlit_interface/
_ROOT = os.path.join(_APP_DIR, "..")          # project root (db_utils.py, etc.)

for _p in (_ROOT, _APP_DIR,
           os.path.join(_APP_DIR, "embedders"),
           os.path.join(_APP_DIR, "pipeline"),
           os.path.join(_APP_DIR, "static")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st
from styles import inject_custom_css
from components.analytics import render_analytics

st.set_page_config(
    page_title="Market Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()
render_analytics()
