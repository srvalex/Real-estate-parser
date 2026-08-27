"""
embedding.py
─────────────
Streamlit-free query-text embedding for pipeline_core.apply_ai_scores.

Ported from streamlit_interface/embedders/local_embedder.py::embed_query,
minus the `streamlit` import and @st.cache_resource decorator (replaced with
functools.lru_cache, which needs no running Streamlit session to work) and
minus the Cloud Run embedding-service remote fallback — that service is
dead code, superseded by embed_job.py (a plain batch script, no HTTP
server); see MIGRATION_PLAN.md / Roadmap.md tech debt notes. This module
only ever loads the local SentenceTransformer model.

Same model as local_embedder.py, so query embeddings stay compatible with
whatever populated listings.embedding (also paraphrase-multilingual-MiniLM-L12-v2).
"""
from functools import lru_cache

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=1)
def _get_model():
    """Load SentenceTransformer once per process."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


def embed_query(text: str) -> list | None:
    """Embed a single query string. Returns None on empty input or model error."""
    if not text or not text.strip():
        return None
    try:
        return _get_model().encode(text, normalize_embeddings=True).tolist()
    except Exception as e:
        print(f"  [embedding] local model error: {e}")
        return None
