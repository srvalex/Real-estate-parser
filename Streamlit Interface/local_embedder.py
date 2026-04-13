"""
local_embedder.py
─────────────────
Drop-in replacement for ollama_parser.py that runs entirely on the local machine.
No Colab, no ngrok, no HTTP calls.

Model and ChromaDB client are loaded once on first use (module-level globals).
Function signatures are identical to ollama_parser.py.
"""

import os
from typing import Optional, List, Dict
import streamlit as st

# ── Paths ────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
CHROMA_DB_PATH = os.path.join(_HERE, "..", "ChromaDB")
COLLECTION_NAME = "web_archive"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Kept for compatibility with app.py / home.py imports
DEFAULT_SERVER_URL = None


@st.cache_resource(show_spinner="Loading AI model…")
def _load_resources():
    """Load model and ChromaDB collection once per Streamlit server process."""
    from sentence_transformers import SentenceTransformer
    import chromadb
    model = SentenceTransformer(MODEL_NAME)
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return model, collection


# ── Public API (same signatures as ollama_parser.py) ─────────────────────────

def check_server(server_url: str = None, timeout: int = 5) -> bool:
    """Always returns True — the model runs locally, no server needed."""
    try:
        _load_resources()
        return True
    except Exception:
        return False


def embed_listings(
    listings: List[Dict],
    server_url: str = None,
    timeout: int = 120,
):
    """
    Embed listings into the local ChromaDB collection.

    Args:
        listings:   List of dicts with keys: description, url, hard_filters, soft_filters.
        server_url: Ignored (kept for API compatibility).

    Returns:
        (success_message, error_string) — error_string is None on success.
    """
    if not listings:
        return "Nothing to embed.", None

    try:
        model, collection = _load_resources()

        # Filter out entries without a URL or description, then deduplicate by URL.
        # ChromaDB raises if the same ID appears twice in one upsert call.
        seen_urls = set()
        valid = []
        for l in listings:
            url = (l.get("url") or l.get("link") or "").strip()
            desc = (l.get("description") or "").strip()
            if url and desc and url not in seen_urls:
                seen_urls.add(url)
                valid.append(l)

        if not valid:
            return "No valid listings to embed.", None

        descriptions = [l.get("description", "") for l in valid]
        urls = [l.get("url", "") or l.get("link", "") for l in valid]

        embeddings = model.encode(descriptions, show_progress_bar=False).tolist()

        metadatas = []
        for l in valid:
            meta = {"url": l.get("url", "") or l.get("link", "")}
            for hf in l.get("hard_filters", []):
                meta[f"filter_{hf.lower()}"] = True
            metadatas.append(meta)

        collection.upsert(
            documents=descriptions,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=urls,
        )

        return f"Stored {len(urls)} listings successfully.", None

    except Exception as e:
        return None, f"Local embed error: {e}"


def search_by_vibe(
    query: str,
    limit: int = 50,
    url_filters: List[str] = None,
    server_url: str = None,
    timeout: int = 30,
) -> tuple[List[Dict], Optional[str]]:
    """
    Query the local ChromaDB for listings ranked by cosine similarity.

    Args:
        query:       Raw user prompt string.
        limit:       Max number of results to return.
        url_filters: Hard feature-flag keys (e.g. ['HAS_METRO']).
        server_url:  Ignored (kept for API compatibility).

    Returns:
        (matches_list, error_string) — error_string is None on success.
    """
    if not query or not query.strip():
        return [], None

    try:
        model, collection = _load_resources()

        total = collection.count()
        if total == 0:
            return [], "ChromaDB collection is empty."

        # Safe limit — ChromaDB raises if n_results > collection.count()
        safe_limit = min(limit, total)

        query_embedding = model.encode([query], show_progress_bar=False).tolist()[0]

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=safe_limit,
        )

        matches = []
        for i in range(len(results["ids"][0])):
            matches.append({
                "url":         results["ids"][0][i],
                "description": results["documents"][0][i],
                "distance":    results["distances"][0][i],
                "metadata":    results["metadatas"][0][i],
            })

        return matches, None

    except Exception as e:
        return [], f"Local search error: {e}"
