import streamlit as st

def inject_custom_css():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* ── App background (dark neutral grey) ── */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
section[data-testid="stMain"] { background: #1a1f26 !important; }

/* ── Hide unwanted Streamlit chrome ── */
#MainMenu, footer { visibility: hidden; }
[data-testid="stToolbarActions"],
[data-testid="stStatusWidget"],
.stDeployButton { visibility: hidden; }
[data-testid="stHeader"] {
    background: #1a1f26 !important;
    border-bottom: 1px solid #2d3440 !important;
}

/* ── Prevent Streamlit's running-state fade ── */
[data-stale="true"], .stStale { opacity: 1 !important; transition: none !important; }
.stSpinner > div { background: transparent !important; }
.stApp > div { opacity: 1 !important; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #1e2430 !important;
    border-right: 1px solid #2d3440 !important;
}
[data-testid="stSidebar"] * { color: #b0c4be !important; }

/* ── Buttons ── */
.stButton > button {
    background: linear-gradient(135deg, #059669, #0d9488) !important;
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
.stTextInput input, .stTextArea textarea {
    background: #232830 !important;
    border: 1px solid #2d3440 !important;
    border-radius: 10px !important;
    color: #e0f0eb !important;
    font-family: 'Inter', sans-serif !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: #10b981 !important;
    box-shadow: 0 0 0 3px rgba(16,185,129,0.15) !important;
}
.stNumberInput input {
    background: #232830 !important;
    color: #e0f0eb !important;
    border: 1px solid #2d3440 !important;
    border-radius: 10px !important;
}
.stSelectbox div[data-baseweb="select"],
[data-baseweb="select"] {
    background: #232830 !important;
    border: 1px solid #2d3440 !important;
    border-radius: 10px !important;
    color: #e0f0eb !important;
}
.stSlider [data-baseweb="slider"] { padding: 0.25rem 0 !important; }
/* Slider track accent */
[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
    background: #10b981 !important;
    border-color: #10b981 !important;
}

/* ── Checkboxes — emerald ── */
.stCheckbox [data-baseweb="checkbox"] [data-checked="true"],
.stCheckbox [aria-checked="true"] {
    background-color: #10b981 !important;
    border-color: #10b981 !important;
}
.stCheckbox label { color: #b0c4be !important; }

/* ── Toggle ── */
.stToggle [data-checked="true"] { background: #10b981 !important; }

/* ── Multiselect tags — emerald ── */
[data-baseweb="tag"] {
    background: rgba(16,185,129,0.18) !important;
    color: #10b981 !important;
    border: 1px solid rgba(16,185,129,0.3) !important;
}
[data-baseweb="multi-select"] {
    background: #232830 !important;
    border: 1px solid #2d3440 !important;
    border-radius: 10px !important;
}
/* Multiselect dropdown list */
[data-baseweb="popover"] { background: #232830 !important; border: 1px solid #2d3440 !important; }
[data-baseweb="menu"] { background: #232830 !important; }
[data-baseweb="menu"] li { color: #e0f0eb !important; }
[data-baseweb="menu"] li:hover { background: rgba(16,185,129,0.12) !important; }

/* ── Radio buttons — emerald ── */
.stRadio [data-baseweb="radio"] [aria-checked="true"] > div:first-child {
    border-color: #10b981 !important;
    background: #10b981 !important;
}
.stRadio label { color: #b0c4be !important; }

/* ── Labels ── */
label[data-testid="stWidgetLabel"] {
    color: #5a8c84 !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.8px !important;
}

/* ── Containers with border ── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid #2d3440 !important;
    border-radius: 12px !important;
    background: #232830 !important;
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
    background: rgba(16,185,129,0.12);
    color: #10b981;
    border: 1px solid rgba(16,185,129,0.3);
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
    background: linear-gradient(135deg, #e0f0eb 0%, #10b981 55%, #0d9488 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 1rem 0;
    line-height: 1.15;
}
.home-hero p {
    color: #5a8c84;
    font-size: 1.05rem;
    max-width: 520px;
    margin: 0 auto 2.5rem auto;
    line-height: 1.7;
}

.vibe-label {
    font-size: 1rem;
    font-weight: 600;
    color: #10b981;
    margin-bottom: 0.2rem;
}
.vibe-hint {
    font-size: 0.8rem;
    color: #3d6b63;
    margin-bottom: 0.75rem;
    line-height: 1.5;
}

.divider {
    height: 1px;
    background: #2d3440;
    margin: 1.75rem 0;
}
.section-label {
    font-size: 0.72rem;
    font-weight: 700;
    color: #3d6b63;
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
    background: #1e2430;
    border-bottom: 1px solid #2d3440;
    padding: 1.2rem 2rem;
    margin: -1rem -1rem 2rem -1rem;
    gap: 1rem;
}
.results-header .logo {
    font-size: 1.1rem;
    font-weight: 700;
    color: #10b981;
    white-space: nowrap;
}
.vibe-pill {
    background: rgba(16,185,129,0.1);
    border: 1px solid rgba(16,185,129,0.25);
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 0.82rem;
    color: #10b981;
    font-style: italic;
    max-width: 400px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.result-count {
    color: #3d6b63;
    font-size: 0.85rem;
    margin-bottom: 1.5rem;
    font-weight: 500;
}
.result-count span { color: #10b981; font-weight: 700; }

/* Property Cards */
.prop-card {
    background: #232830;
    border: 1px solid #2d3440;
    border-radius: 14px;
    padding: 1.5rem 1.5rem 1.25rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s, transform 0.15s, box-shadow 0.2s;
    position: relative;
    overflow: hidden;
}
.prop-card:hover {
    border-color: #10b981;
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(16,185,129,0.1);
}
.prop-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 4px; height: 100%;
    background: linear-gradient(180deg, #10b981, #0d9488);
    border-radius: 14px 0 0 14px;
}
.card-platform {
    display: inline-block;
    background: rgba(13,148,136,0.12);
    color: #0d9488;
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 2px 8px;
    border-radius: 20px;
    margin-bottom: 0.5rem;
}
.card-platform.olx { background: rgba(245,158,11,0.12); color: #f59e0b; }
.card-title { font-size: 1rem; font-weight: 600; color: #e0f0eb; margin-bottom: 0.45rem; line-height: 1.4; }
.card-price { font-size: 1.35rem; font-weight: 700; color: #10b981; margin-bottom: 0.65rem; }
.card-meta { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 0.85rem; }
.meta-chip {
    background: #1e2430;
    color: #5a8c84;
    border-radius: 7px;
    padding: 3px 9px;
    font-size: 0.76rem;
    font-weight: 500;
}
.card-desc {
    color: #3d6b63;
    font-size: 0.8rem;
    line-height: 1.65;
    border-top: 1px solid #2d3440;
    padding-top: 0.75rem;
    max-height: 72px;
    overflow: hidden;
    -webkit-mask-image: linear-gradient(180deg, #000 50%, transparent);
    mask-image: linear-gradient(180deg, #000 50%, transparent);
}
.card-link { display: inline-block; margin-top: 0.65rem; color: #10b981; font-size: 0.8rem; font-weight: 500; }
.no-results { text-align: center; padding: 5rem 2rem; color: #3d6b63; }
.no-results span { font-size: 3rem; display: block; margin-bottom: 1rem; }
</style>
""", unsafe_allow_html=True)
