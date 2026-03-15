import streamlit as st
import pandas as pd
import re
import os
from ollama_parser import parse_vibe, check_server, DEFAULT_SERVER_URL

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
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: #0d0f1a; }
#MainMenu, footer, header { visibility: hidden; }

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


# ─────────────────────────────────────────────
#  Data helpers
# ─────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "..")

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

# ─────────────────────────────────────────────
#  Session state init
# ─────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "home"
if "search_params" not in st.session_state:
    st.session_state.search_params = {}


# ═══════════════════════════════════════════════════════════
#  PAGE: HOME
# ═══════════════════════════════════════════════════════════
if st.session_state.page == "home":

    # Hero
    st.markdown("""
    <div class="home-hero">
        <div class="badge">🏠 Real Estate Explorer</div>
        <h1>Find your<br>perfect place</h1>
        <p>Describe what you're looking for in plain language — we'll search through the scraped listings and surface the best matches.</p>
    </div>
    """, unsafe_allow_html=True)

    # Search card
    with st.container():
        _, center, _ = st.columns([1, 2.5, 1])
        with center:

            # ── Vibe ──
            st.markdown('<div class="vibe-label">✨ What\'s the vibe you\'re after?</div>', unsafe_allow_html=True)
            st.markdown('<div class="vibe-hint">Describe in your own words — keywords, feelings, must-haves. e.g. <em>"bright, modern, quiet street near metro"</em></div>', unsafe_allow_html=True)
            vibe = st.text_area(
                label="vibe",
                placeholder="e.g. modern kitchen, quiet, close to a park, renovated, good light...",
                height=110,
                label_visibility="collapsed",
            )

            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

            # ── Quick filters ──
            st.markdown('<div class="section-label">Quick filters</div>', unsafe_allow_html=True)

            c1, c2 = st.columns(2)
            with c1:
                max_price = st.number_input("Max price (€/month)", min_value=0, max_value=10000, value=0, step=50, help="Leave at 0 to skip")
            with c2:
                rooms = st.selectbox("Rooms", ["Any", "1", "2", "3", "4+"])

            # Data source
            st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
            st.markdown('<div class="section-label">Data source</div>', unsafe_allow_html=True)

            src_tab, scrape_tab = st.tabs(["📂 Use existing CSV", "🕷️ Scrape fresh data"])

            uploaded = None
            scrape_config = None

            with src_tab:
                default_csv = os.path.join(DATA_DIR, "Date Storia Procesate.csv")
                uploaded = st.file_uploader("Upload a CSV", type=["csv"], label_visibility="collapsed")
                if not uploaded and os.path.exists(default_csv):
                    st.caption(f"📂 No upload? Will use default dataset (`Date Storia Procesate.csv`)")

            with scrape_tab:
                sc1, sc2 = st.columns(2)
                with sc1:
                    olx_pages = st.number_input("OLX pages", min_value=1, max_value=20, value=1)
                with sc2:
                    storia_pages = st.number_input("Storia pages", min_value=1, max_value=20, value=1)
                
                # Hardcoded URLs as requested
                olx_url = "https://www.olx.ro/imobiliare/apartamente-garsoniere-de-inchiriat/bucuresti/?currency=EUR"
                storia_url = "https://www.storia.ro/ro/rezultate/inchiriere/apartament/bucuresti?ownerTypeSingleSelect=ALL"
                
                scrape_config = {"olx_url": olx_url, "storia_url": storia_url,
                                 "olx_pages": olx_pages, "storia_pages": storia_pages}
                st.caption("⚠️ Scraping runs while you wait — 1 page takes ~1–2 min.")

            # ── Colab server URL (Hardcoded) ──
            server_url = DEFAULT_SERVER_URL
            is_online = check_server(server_url)
            if is_online:
                st.caption("✅ Server is reachable")
            else:
                st.caption("⚠️ Server not reachable — make sure Colab is running and DEFAULT_SERVER_URL in ollama_parser.py is currently updated.")

            st.markdown('<br>', unsafe_allow_html=True)

            # ── CTA ──
            _, btn_col, _ = st.columns([1, 2, 1])
            with btn_col:
                search_clicked = st.button("🔍  Search listings", use_container_width=True)

            st.markdown('</div>', unsafe_allow_html=True)

        parsed_params = None
        parse_error   = None
        if vibe.strip():
            with st.spinner("Extraing keywords from your prompt"):
                parsed_params, parse_error = parse_vibe(vibe, server_url=server_url)
        
    # Handle search
    if search_clicked:
        # ── Decide data source ──
        df = None
        if uploaded:
            import io
            df = pd.read_csv(uploaded)
            df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
            price_col = "rent" if "rent" in df.columns else "price" if "price" in df.columns else None
            df["_price_num"] = df[price_col].apply(parse_price) if price_col else None
            df["_rooms_num"] = df["rooms"].apply(parse_rooms) if "rooms" in df.columns else None
            df["platform"] = "Storia"
        elif scrape_config and scrape_config.get("olx_url"):
            import sys
            sys.path.insert(0, DATA_DIR)
            from extractor import run_pipeline
            
            final_olx_url = scrape_config["olx_url"]
            if parsed_params and isinstance(parsed_params, dict):
                amenities = parsed_params.get("amenities", [])
                if amenities:
                    # Filter out empty amenities and format: q-KEYWORD_1-KEYWORD_2...
                    valid_keywords = [k.strip().replace(" ", "-") for k in amenities if k.strip()]
                    if valid_keywords:
                        q_string = "-".join(["q"] + valid_keywords)
                        # The URL format: .../bucuresti/q-keyword1-keyword2/?currency=EUR
                        # We need to insert the q_string right before the query parameters
                        if "?" in final_olx_url:
                            base, query_str = final_olx_url.split("?", 1)
                            # Ensure trailing slash on base before appending q_string
                            base = base if base.endswith("/") else base + "/"
                            # If there's already a q- parameter or other path elements we might need to be careful,
                            # but normally it ends in /bucuresti/
                            final_olx_url = f"{base}{q_string}/?{query_str}"
                        else:
                            base = final_olx_url if final_olx_url.endswith("/") else final_olx_url + "/"
                            final_olx_url = f"{base}{q_string}/"
            
            with st.spinner(f"Scraping results from the web"):
                df = run_pipeline(
                    olx_url=final_olx_url,
                    storia_url=scrape_config["storia_url"],
                    olx_pages=int(scrape_config["olx_pages"]),
                    storia_pages=int(scrape_config["storia_pages"]),
                    out_csv="results.csv",
                )
            price_col = "rent" if "rent" in df.columns else "price" if "price" in df.columns else None
            df["_price_num"] = df[price_col].apply(parse_price) if price_col else None
            df["_rooms_num"] = df["rooms"].apply(parse_rooms) if "rooms" in df.columns else None
        elif os.path.exists(default_csv):
            df = load_csv(default_csv)
        else:
            st.error("No data source found. Upload a CSV or configure scraping.")
            st.stop()

        # ── Ollama vibe parsing ──
      

        st.session_state.search_params = {
            "vibe":          vibe,
            "max_price":     max_price,
            "rooms":         rooms,
            "parsed_params": parsed_params,
            "parse_error":   parse_error,
        }
        st.session_state.df = df
        st.session_state.page = "results"
        st.rerun()


# ═══════════════════════════════════════════════════════════
#  PAGE: RESULTS
# ═══════════════════════════════════════════════════════════
elif st.session_state.page == "results":

    params = st.session_state.search_params
    df: pd.DataFrame = st.session_state.get("df", pd.DataFrame())

    # ── Top bar ──
    col_back, col_logo, col_vibe = st.columns([0.8, 1, 4])
    with col_back:
        if st.button("← Back"):
            st.session_state.page = "home"
            st.rerun()
    with col_logo:
        st.markdown('<div style="color:#a78bfa;font-weight:700;padding-top:0.5rem;">🏠 Explorer</div>', unsafe_allow_html=True)
    with col_vibe:
        vibe_text = params.get("vibe", "").strip()
        if vibe_text:
            st.markdown(f'<div class="vibe-pill">✨ "{vibe_text}"</div>', unsafe_allow_html=True)

    st.markdown("---")

    # ── Parsed vibe JSON expander ──
    parsed = params.get("parsed_params")
    parse_err = params.get("parse_error")
    if parsed:
        with st.expander("🧠 How Ollama understood your vibe", expanded=True):
            st.json(parsed)
    elif parse_err:
        with st.expander("⚠️ Ollama parsing note", expanded=True):
            st.warning(parse_err)
            st.caption("Search is still running using your raw text as keyword filter.")

    if df.empty:
        st.warning("No data loaded. Go back and try again.")
        st.stop()

    # ── Apply filters ──
    df_f = df.copy()

    # Price filter
    max_price = params.get("max_price", 0)
    if max_price and max_price > 0:
        has_price = df_f["_price_num"].notna()
        under = df_f["_price_num"] <= max_price
        df_f = df_f[~has_price | under]

    # Rooms filter
    sel_rooms = params.get("rooms", "Any")
    if sel_rooms != "Any":
        target = 4 if sel_rooms == "4+" else int(sel_rooms)
        has_rooms = df_f["_rooms_num"].notna()
        if sel_rooms == "4+":
            matches = df_f["_rooms_num"] >= 4
        else:
            matches = df_f["_rooms_num"] == target
        df_f = df_f[~has_rooms | matches]

    # Vibe filter - Disabled as per user request to rely on smart URLs only
    # df_f = apply_vibe(df_f, params.get("vibe", ""))

    # ── Count ──
    total, shown = len(df), len(df_f)
    st.markdown(
        f'<div class="result-count"><span>{shown}</span> listings match your search &nbsp;·&nbsp; {total} total</div>',
        unsafe_allow_html=True,
    )

    # ── Cards ──
    if df_f.empty:
        st.markdown("""
        <div class="no-results">
            <span>🔍</span>
            No listings match your criteria.<br>Try broadening the vibe or removing filters.
        </div>
        """, unsafe_allow_html=True)
    else:
        left, right = st.columns(2)

        for i, (_, row) in enumerate(df_f.iterrows()):
            col = left if i % 2 == 0 else right
            with col:
                title      = safe_str(row.get("title", "")) or "Untitled listing"
                price_disp = safe_str(row.get("rent", row.get("price", ""))) or "—"
                district   = safe_str(row.get("district", ""))
                location   = safe_str(row.get("location_full_name", ""))
                rooms_val  = safe_str(row.get("rooms", ""))
                sqm        = safe_str(row.get("m", ""))
                desc       = safe_str(row.get("description", ""))
                url        = safe_str(row.get("url", ""))
                platform   = safe_str(row.get("platform", "Storia"))

                chips = ""
                if rooms_val: chips += f'<span class="meta-chip">🛏 {rooms_val}</span>'
                if sqm:       chips += f'<span class="meta-chip">📐 {sqm}</span>'
                loc_label = district or location[:30]
                if loc_label: chips += f'<span class="meta-chip">📍 {loc_label}</span>'

                plat_class = "olx" if "olx" in platform.lower() else ""
                link_html  = f'<a class="card-link" href="{url}" target="_blank">View listing →</a>' if url else ""
                desc_html  = desc[:400].replace("<", "&lt;").replace(">", "&gt;")

                st.markdown(f"""
                <div class="prop-card">
                    <div class="card-platform {plat_class}">{platform}</div>
                    <div class="card-title">{title}</div>
                    <div class="card-price">{price_disp}</div>
                    <div class="card-meta">{chips}</div>
                    <div class="card-desc">{desc_html}</div>
                    {link_html}
                </div>
                """, unsafe_allow_html=True)
