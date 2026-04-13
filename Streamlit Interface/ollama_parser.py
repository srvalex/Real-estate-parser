"""
ollama_parser.py
────────────────
Handles communication with the remote Colab/Ollama FastAPI server for
semantic embedding and similarity search.

Keyword extraction is now done locally via nlp_filters.py (spaCy).

The remote server exposes:
    POST /embed           → store listing embeddings in ChromaDB
    POST /search-listings → rank listings by cosine similarity to vibe

Set DEFAULT_SERVER_URL to the current ngrok tunnel URL from Colab.
"""

import requests
from typing import Optional, List, Dict

# Default placeholder — overridden at runtime by the Streamlit URL input
DEFAULT_SERVER_URL = "https://josue-unbiddable-unreproachably.ngrok-free.dev"



def check_server(server_url: str, timeout: int = 5) -> bool:
    """
    Quick health-check — returns True if the server is reachable.
    FastAPI exposes /docs by default; we just need a 200-ish response.
    """
    try:
        r = requests.get(server_url.rstrip("/") + "/docs", timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def embed_listings(
    listings: List[Dict],
    server_url: str = DEFAULT_SERVER_URL,
    timeout: int = 120,
) -> Optional[str]:
    """
    Push a list of listings to the Colab server's /embed endpoint so their
    descriptions are stored as vector embeddings in ChromaDB.

    Args:
        listings:   List of dicts, each with keys:
                    'description', 'url', 'hard_filters' (list), 'soft_filters' (list).
        server_url: Base ngrok URL of the Colab server.
        timeout:    Request timeout (encoding many listings can be slow).

    Returns:
        Success message string on success, or None on failure.
    """
    if not listings:
        return None

    endpoint = server_url.rstrip("/") + "/embed"

    # Normalise: make sure hard_filters / soft_filters are lists
    payload = []
    for l in listings:
        payload.append({
            "description": l.get("description", "") or "",
            "url":         l.get("url", "") or l.get("link", ""),
            "hard_filters": l.get("hard_filters", []) or [],
            "soft_filters": l.get("soft_filters", []) or [],
        })

    try:
        resp = requests.post(endpoint, json={"listings": payload}, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("message", "Embedded successfully."), None
    except requests.exceptions.ConnectionError:
        return None, "Could not connect to embedding server."
    except requests.exceptions.Timeout:
        return None, "Embedding request timed out."
    except Exception as e:
        return None, f"Embed error: {e}"


def search_by_vibe(
    query: str,
    limit: int = 50,
    url_filters: List[str] = None,
    server_url: str = DEFAULT_SERVER_URL,
    timeout: int = 30,
) -> tuple[List[Dict], Optional[str]]:
    """
    Query ChromaDB via the Colab server for listings ranked by cosine similarity
    to the user's full prompt. Returns pure semantic ranking.

    Args:
        query:       The complete raw user prompt string.
        limit:       Max number of results to return.
        url_filters: If provided, restrict the search to only these URLs.
                     Pass the current zone's URLs so every listing gets a score.
        server_url:  Base ngrok URL of the Colab server.

    Returns:
        (matches_list, error_string) — error_string is None on success.
    """
    if not query or not query.strip():
        return [], None

    endpoint = server_url.rstrip("/") + "/search-listings"

    try:
        resp = requests.post(
            endpoint,
            json={
                "vibe_terms":  [query],
                "url_filters": url_filters or [],
                "limit":       limit,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("matches", []), None
    except requests.exceptions.ConnectionError:
        return [], "Could not connect to embedding server."
    except requests.exceptions.Timeout:
        return [], "Search request timed out."
    except Exception as e:
        return [], f"Search error: {e}"
