"""
pipeline_core.py
─────────────────
Streamlit-free search pipeline logic, shared by streamlit_interface/pipeline/utils.py
(which wraps these with @st.cache_data/@st.cache_resource and its own embed_query
import) and api/main.py (which calls these directly, uncached, per MIGRATION_PLAN.md
Phase 1/3).

Relocated from streamlit_interface/pipeline/utils.py — same logic, same
rationale in the docstrings, not a rewrite. Two functions took a small,
deliberate signature change as part of the move, both purely additive
(no existing caller breaks):

  - apply_ai_scores: the embedding function is now an injected parameter
    (`embed_query`) instead of a module-level import, so this module never
    has to decide *how* text gets embedded (Streamlit's cached local model
    vs. the API's own loader) — each caller supplies its own. Also drops
    `server_url`, `skip_embed`, `spacy_filters` — confirmed unused inside
    the function body (see BUGS.md "Lower priority": dead parameter
    candidates). streamlit_interface/pipeline/utils.py's wrapper keeps
    accepting all of these for its own external callers (home.py) and
    simply doesn't forward the unused ones down.
  - apply_price_fairness: `price_stats` is now a required parameter instead
    of being fetched internally via a module-level @st.cache_data-wrapped
    function — the caller decides its own caching strategy (or none, for
    the API).
"""
import re

import db_utils
from rrf import rrf_fuse


def parse_price(val):
    import pandas as pd
    if pd.isna(val):
        return None
    cleaned = re.sub(r"[^\d.]", "", str(val).replace(" ", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_rooms(val):
    import pandas as pd
    if pd.isna(val):
        return None
    m = re.search(r"\d+", str(val))
    return int(m.group()) if m else None


def prepare_dataframe(df):
    """Strip unnamed columns and add numeric helper columns for price and rooms.

    _price_num is EUR-normalised, not a raw copy of price_numeric — the
    dataset has both EUR and RON listings (price_currency), and every
    consumer of _price_num (apply_filters' max_price cutoff) treats it as
    a EUR value. Comparing raw price_numeric against a EUR budget without
    converting RON first silently excluded affordable RON listings whose
    raw number just looked "too high" (e.g. 2000 RON ~= 392 EUR, but
    2000 > a 500 EUR max_price cutoff) — the RON listings weren't flagged
    as errors, they just vanished from results with no indication why.
    """
    import pandas as pd
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    if "price_numeric" in df.columns:
        currency = df["price_currency"] if "price_currency" in df.columns else pd.Series("EUR", index=df.index)
        df["_price_num"] = [
            db_utils.price_in_eur(p, c) for p, c in zip(df["price_numeric"], currency)
        ]
    else:
        price_col = "rent" if "rent" in df.columns else "price" if "price" in df.columns else None
        df["_price_num"] = df[price_col].apply(parse_price) if price_col else None
    rooms_col = "rooms" if "rooms" in df.columns else ("rooms_num" if "rooms_num" in df.columns else None)
    df["_rooms_num"] = df[rooms_col].apply(parse_rooms) if rooms_col else None
    return df


def apply_filters(
    df,
    max_price: int,
    sel_rooms: str,
    min_sqm: int = 0,
    max_sqm: int = 0,
    property_types: list[str] | None = None,
):
    """Apply price, room count, area and property-type filters."""
    if df.empty:
        return df

    if max_price and max_price > 0 and "_price_num" in df.columns:
        has_price = df["_price_num"].notna()
        df = df[~has_price | (df["_price_num"] <= max_price)]

    if sel_rooms not in ("Any", "Orice") and "_rooms_num" in df.columns:
        has_rooms = df["_rooms_num"].notna()
        if sel_rooms == "5+":
            df = df[~has_rooms | (df["_rooms_num"] >= 5)]
        else:
            df = df[~has_rooms | (df["_rooms_num"] == int(sel_rooms))]

    if (min_sqm or max_sqm) and "area_sqm" in df.columns:
        import pandas as pd
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


def apply_ai_scores(df, vibe: str, url_col: str, embed_query, image_embedding: list | None = None):
    """Re-sort df by AI similarity score using Reciprocal Rank Fusion (RRF).

    Two independent search paths can feed the fusion:
      - Text:  paraphrase-multilingual-MiniLM-L12-v2 (384-dim) → match_listings RPC.
               Runs whenever the caller supplies vibe text.
      - Image: CLIP ViT-B/32 vision tower (512-dim)            → match_listings_by_image RPC.
               Runs ONLY when the caller supplies a pre-computed image_embedding
               (template photo picker or an uploaded photo) — never derived from
               vibe text. CLIP's text tower is trained on English image captions;
               it has no reliable way to represent non-visual, relational concepts
               ("aproape de metrou", "liniștit") that make up most vibe prompts,
               and it wasn't trained on Romanian. Auto-encoding the vibe text
               through it and fusing at W_IMAGE=0.7 used to silently dominate and
               degrade every plain-text search.

    Because the two models live in different vector spaces with different score
    distributions, their raw cosine similarities cannot be meaningfully averaged.
    RRF fuses them via ordinal rank instead of raw score:

        rrf(url) = W_TEXT  / (K + text_rank(url))
                 + W_IMAGE / (K + image_rank(url))

    K=60 (standard constant) dampens the advantage of rank-1 over rank-2 while
    still strongly preferring anything near the top of either list. URLs absent
    from a ranked list contribute 0 for that component (infinite rank).

    Supports three modes:
      - text only   (image_embedding=None, vibe set)   → pure text_scores
      - image only  (image_embedding set,  vibe empty) → pure image_scores
      - both        (image_embedding set,  vibe set)   → RRF fusion of both
    Returns (df_sorted, embedding_sorted: bool, embed_error: str | None).
    """
    embed_error = None
    has_vibe = bool(vibe and vibe.strip())
    has_image = bool(image_embedding)

    if not has_vibe and not has_image:
        return df, False, None

    # Score every candidate in df (already filtered by district/price/rooms/
    # type before this function runs) rather than hoping it survives some
    # global top-K cutoff on the whole listings table. Without this, a
    # niche-filtered search over a small district could see its actual best
    # matches sit outside the global top-K on a large table and silently
    # get no score at all (sorted last, no error shown). No size cap here —
    # db_utils.search_by_text_vibe/search_by_image_embedding split a large
    # candidate_urls list into bounded RPC batches internally
    # (_RPC_CANDIDATE_CHUNK_SIZE), so scoping stays correct even when every
    # sector is selected at once, instead of silently reverting to an
    # unscoped global search past some threshold (see BUGS.md #7).
    all_candidate_urls = list(df[url_col].dropna().unique())
    scoped_urls = all_candidate_urls

    # ── Text search via pgvector (Supabase match_listings RPC) ───────────────
    text_scores: dict = {}
    if has_vibe:
        try:
            q_embedding = embed_query(vibe)
            if q_embedding:
                text_scores = db_utils.search_by_text_vibe(
                    q_embedding,
                    limit=1000,
                    candidate_urls=scoped_urls,
                )
                if not text_scores:
                    embed_error = "No pgvector matches — run scripts/backfill_embeddings.py to populate embeddings"
            else:
                embed_error = "Failed to embed query text"
        except Exception as e:
            embed_error = f"pgvector search error: {e}"

    # ── Image scores via Supabase (image_embedding column) ────────────────────
    image_scores: dict = {}
    img_error = None
    if has_image:
        try:
            image_scores = db_utils.search_by_image_embedding(
                image_embedding, limit=3000, candidate_urls=scoped_urls,
            )
        except Exception as e:
            img_error = str(e)
    if img_error and not embed_error:
        embed_error = img_error

    # ── Bail if we have nothing to rank with ──────────────────────────────────
    if not text_scores and not image_scores:
        return df, False, embed_error

    # ── Reciprocal Rank Fusion ────────────────────────────────────────────────
    final_scores = rrf_fuse(text_scores, image_scores, all_candidate_urls)

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


def apply_price_fairness(df, price_stats: dict):
    """Add 'price_fairness' (Streamlit's display label, e.g. '+12% vs avg')
    and 'price_fairness_pct' (the same value as a raw signed number, or
    None) columns.

    Labels/values are suppressed when:
    - district or rooms is missing
    - fewer than 5 comparables exist in that bucket
    - price is within ±5% of the average (too close to call)

    price_stats buckets are EUR-only (get_price_stats() filters
    price_currency=EUR before averaging), so a RON-priced row's raw
    price_numeric must be converted to EUR before comparing — otherwise a
    normally-priced RON listing (e.g. 4000 RON ~= 784 EUR) gets compared
    against a EUR average (e.g. 850) as if it were 4000 EUR, producing a
    wildly wrong "+371% vs avg" badge instead of the accurate "-8%".
    """
    df = df.copy()
    if not price_stats or df.empty:
        df["price_fairness"] = None
        df["price_fairness_pct"] = None
        return df

    THRESHOLD = 5.0
    labels = []
    pcts = []
    for _, row in df.iterrows():
        district = str(row.get("district") or "").strip()
        rooms = str(row.get("rooms") or "").strip()
        price_eur = db_utils.price_in_eur(row.get("price_numeric"), row.get("price_currency"))

        if not district or not rooms or price_eur is None:
            labels.append(None)
            pcts.append(None)
            continue

        bucket = price_stats.get((district, rooms))
        if not bucket:
            labels.append(None)
            pcts.append(None)
            continue

        try:
            pct = (price_eur - bucket["avg"]) / bucket["avg"] * 100
        except (TypeError, ZeroDivisionError):
            labels.append(None)
            pcts.append(None)
            continue

        if abs(pct) < THRESHOLD:
            labels.append(None)
            pcts.append(None)
        else:
            rounded = round(pct)
            labels.append(f"+{rounded}% vs avg" if pct > 0 else f"{rounded}% vs avg")
            pcts.append(rounded)

    df["price_fairness"] = labels
    df["price_fairness_pct"] = pcts
    return df
