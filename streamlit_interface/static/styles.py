import streamlit as st

def inject_custom_css():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: #0d0f1a; }
#MainMenu, footer { visibility: hidden; }
/* Hide Streamlit's top toolbar chrome without touching the header element itself,
   so the sidebar expand/collapse control is never accidentally hidden. */
[data-testid="stToolbarActions"],
[data-testid="stStatusWidget"],
.stDeployButton { visibility: hidden; }
/* Match header background to app so any remaining chrome is invisible */
[data-testid="stHeader"] { background: #0d0f1a !important; border-bottom: 1px solid #1e2235 !important; }

/* ── Prevent Streamlit's running-state fade ── */
[data-stale="true"], .stStale { opacity: 1 !important; transition: none !important; }
.stSpinner > div { background: transparent !important; }
.stApp > div { opacity: 1 !important; }

/* ── Buttons ── */
.stButton > button {
    background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
    color: white !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 0.75rem 2.5rem !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.3px !important;
    transition: opacity 0.2s, transform 0.15s !important;
    cursor: pointer !important;
}
.stButton > button:hover {
    opacity: 0.9 !important;
    transform: translateY(-1px) !important;
}

/* ── Inputs & Textareas ── */
.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
    background: #1a1d2e !important;
    border: 1px solid #2d3047 !important;
    border-radius: 10px !important;
    color: #e2e8f0 !important;
    font-family: 'Inter', sans-serif !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.15) !important;
}
.stSlider [data-baseweb="slider"] { padding: 0.25rem 0 !important; }

/* ── Labels ── */
label[data-testid="stWidgetLabel"] {
    color: #94a3b8 !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.8px !important;
}

/* ═══════════════════════════════
   HOME PAGE
   ═══════════════════════════════ */
.home-hero {
    text-align: center;
    padding: 4rem 1rem 2rem;
}
.home-hero .badge {
    display: inline-block;
    background: rgba(99,102,241,0.15);
    color: #a78bfa;
    border: 1px solid rgba(99,102,241,0.3);
    border-radius: 20px;
    padding: 4px 16px;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 1.5rem;
}
.home-hero h1 {
    font-size: 3.2rem;
    font-weight: 800;
    background: linear-gradient(135deg, #e2e8f0 0%, #a78bfa 60%, #ec4899 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 1rem 0;
    line-height: 1.15;
}
.home-hero p {
    color: #64748b;
    font-size: 1.05rem;
    max-width: 520px;
    margin: 0 auto 2.5rem auto;
    line-height: 1.7;
}

.vibe-label {
    font-size: 1rem;
    font-weight: 600;
    color: #c4b5fd;
    margin-bottom: 0.2rem;
}
.vibe-hint {
    font-size: 0.8rem;
    color: #475569;
    margin-bottom: 0.75rem;
    line-height: 1.5;
}

.divider {
    height: 1px;
    background: #2d3047;
    margin: 1.75rem 0;
}
.section-label {
    font-size: 0.72rem;
    font-weight: 700;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    margin-bottom: 1rem;
}

/* ═══════════════════════════════
   RESULTS PAGE
   ═══════════════════════════════ */
.results-header {
    display: flex;
    align-items: center;
    background: #151724;
    border-bottom: 1px solid #2d3047;
    padding: 1.2rem 2rem;
    margin: -1rem -1rem 2rem -1rem;
    gap: 1rem;
}
.results-header .logo {
    font-size: 1.1rem;
    font-weight: 700;
    color: #a78bfa;
    white-space: nowrap;
}
.vibe-pill {
    background: rgba(99,102,241,0.12);
    border: 1px solid rgba(99,102,241,0.25);
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 0.82rem;
    color: #a78bfa;
    font-style: italic;
    max-width: 400px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.result-count {
    color: #475569;
    font-size: 0.85rem;
    margin-bottom: 1.5rem;
    font-weight: 500;
}
.result-count span { color: #a78bfa; font-weight: 700; }

/* Property Cards */
.prop-card {
    background: #151724;
    border: 1px solid #2d3047;
    border-radius: 14px;
    padding: 1.5rem 1.5rem 1.25rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s, transform 0.15s;
    position: relative;
    overflow: hidden;
}
.prop-card:hover { border-color: #6366f1; transform: translateY(-2px); }
.prop-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 4px; height: 100%;
    background: linear-gradient(180deg, #6366f1, #ec4899);
    border-radius: 14px 0 0 14px;
}
.card-platform {
    display: inline-block;
    background: rgba(236,72,153,0.12);
    color: #f472b6;
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 2px 8px;
    border-radius: 20px;
    margin-bottom: 0.5rem;
}
.card-platform.olx { background: rgba(234,179,8,0.12); color: #fbbf24; }
.card-title { font-size: 1rem; font-weight: 600; color: #e2e8f0; margin-bottom: 0.45rem; line-height: 1.4; }
.card-price { font-size: 1.35rem; font-weight: 700; color: #a78bfa; margin-bottom: 0.65rem; }
.card-meta { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 0.85rem; }
.meta-chip {
    background: #1e2130;
    color: #64748b;
    border-radius: 7px;
    padding: 3px 9px;
    font-size: 0.76rem;
    font-weight: 500;
}
.card-desc {
    color: #475569;
    font-size: 0.8rem;
    line-height: 1.65;
    border-top: 1px solid #1e2130;
    padding-top: 0.75rem;
    max-height: 72px;
    overflow: hidden;
    -webkit-mask-image: linear-gradient(180deg, #000 50%, transparent);
    mask-image: linear-gradient(180deg, #000 50%, transparent);
}
.card-link { display: inline-block; margin-top: 0.65rem; color: #6366f1; font-size: 0.8rem; font-weight: 500; }
.no-results { text-align: center; padding: 5rem 2rem; color: #475569; }
.no-results span { font-size: 3rem; display: block; margin-bottom: 1rem; }
</style>
""", unsafe_allow_html=True)
