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

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))
except ImportError:
    pass

# ── Paths ────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Kept for compatibility with app.py / home.py imports
DEFAULT_SERVER_URL = None


@st.cache_resource(show_spinner="Loading AI model…")
def _get_model():
    """Load SentenceTransformer once per Streamlit server process."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


def _get_id_token(service_url: str) -> str | None:
    """Return a Google ID token for the given Cloud Run service URL.

    Resolves GOOGLE_APPLICATION_CREDENTIALS relative to the project root
    (two levels above this file) so the path works regardless of where
    Streamlit is launched from.
    """
    key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not key_path:
        print("  [embed-service] GOOGLE_APPLICATION_CREDENTIALS not set", flush=True)
        return None
    if not os.path.isabs(key_path):
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        key_path = os.path.join(_root, key_path)
    if not os.path.exists(key_path):
        print(f"  [embed-service] key file not found: {key_path}", flush=True)
        return None
    try:
        from google.oauth2 import service_account
        from google.auth.transport import requests as ga_requests
        creds = service_account.IDTokenCredentials.from_service_account_file(
            key_path, target_audience=service_url
        )
        creds.refresh(ga_requests.Request())
        return creds.token
    except Exception as e:
        print(f"  [embed-service] ID token error: {e}", flush=True)
        return None


def warmup_service(service_url: str) -> None:
    """Fire a /health request so the container wakes up while the user fills the form."""
    import threading
    import requests

    def _ping():
        try:
            headers = {}
            token = _get_id_token(service_url)
            if token:
                headers["Authorization"] = f"Bearer {token}"
            requests.get(f"{service_url.rstrip('/')}/health", headers=headers, timeout=10)
            print("  [embed-service] warmup ping sent", flush=True)
        except Exception:
            pass

    threading.Thread(target=_ping, daemon=True).start()


def _embed_via_service(text: str, service_url: str) -> list | None:
    """Call the Cloud Run embedding service POST /embed/text.
    Retries on 503 (models still loading after cold start) for up to 90 seconds.
    """
    import time
    import requests

    headers: dict = {}
    token = _get_id_token(service_url)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url      = f"{service_url.rstrip('/')}/embed/text"
    deadline = time.time() + 90

    while time.time() < deadline:
        try:
            resp = requests.post(url, json={"text": text}, headers=headers, timeout=20)
            if resp.status_code == 503:
                print("  [embed-service] warming up, retrying in 5s…", flush=True)
                time.sleep(5)
                continue
            resp.raise_for_status()
            return resp.json()["embedding"]
        except requests.exceptions.RequestException as e:
            print(f"  [embed-service] request error: {e}", flush=True)
            return None

    print("  [embed-service] timed out waiting for service to warm up", flush=True)
    return None


def embed_query(text: str) -> list | None:
    """Embed a single query string.

    Calls the Cloud Run embedding service if EMBED_SERVICE_URL is set,
    falls back to the local SentenceTransformer model otherwise.
    """
    if not text or not text.strip():
        return None
    service_url = os.environ.get("EMBED_SERVICE_URL", "").strip()
    if service_url:
        result = _embed_via_service(text, service_url)
        if result is not None:
            return result
    try:
        return _get_model().encode(text, normalize_embeddings=True).tolist()
    except Exception as e:
        print(f"  [embed] local ST fallback failed: {e}", flush=True)
        return None


# ── Public API (same signatures as ollama_parser.py) ─────────────────────────

def check_server(server_url: str = None, timeout: int = 5) -> bool:
    """Local resources disabled — always returns False."""
    return False


def embed_listings(
    listings: List[Dict],
    server_url: str = None,
    timeout: int = 120,
):
    """Local ChromaDB embedding disabled — no-op stub."""
    return None, "Local embedding disabled — use cloud service"


def search_by_vibe(
    query: str,
    limit: int = 50,
    url_filters: List[str] = None,
    server_url: str = None,
    timeout: int = 30,
) -> tuple[List[Dict], Optional[str]]:
    """Local ChromaDB search disabled — no-op stub."""
    return [], "Local search disabled — use cloud service"
