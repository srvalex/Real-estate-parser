"""
ollama_parser.py
────────────────
Sends the user's free-text "vibe" to the remote Colab/Ollama FastAPI server
and returns a structured JSON object used to filter real-estate listings.

The remote server exposes:
    POST /process-search  → extract hard/soft filters from free text
    POST /embed           → store listing embeddings in ChromaDB
    POST /search-listings → rank listings by cosine similarity to vibe

Set DEFAULT_SERVER_URL to the current ngrok tunnel URL from Colab.
"""

import json
import requests
from typing import Optional, List, Dict

# Default placeholder — overridden at runtime by the Streamlit URL input
DEFAULT_SERVER_URL = "https://josue-unbiddable-unreproachably.ngrok-free.dev"
ENDPOINT_PATH      = "/process-search"


def parse_vibe(
    vibe_text: str,
    server_url: str = DEFAULT_SERVER_URL,
    timeout: int = 120,
) -> tuple[Optional[dict], Optional[str]]:
    """
    Send vibe text to the remote Colab server and return structured JSON.

    Args:
        vibe_text:  The user's natural-language property description.
        server_url: The base public ngrok URL (e.g. https://abc123.ngrok-free.app).
        timeout:    Request timeout in seconds (LLM inference can be slow).

    Returns:
        (parsed_dict, error_string)
        On success:  (dict, None)
        On failure:  (None, error_message)
    """
    if not vibe_text.strip():
        return None, "Empty vibe — nothing to parse."

    endpoint = server_url.rstrip("/") + ENDPOINT_PATH

    try:
        response = requests.post(
            endpoint,
            json={"text": vibe_text},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json(), None

    except requests.exceptions.ConnectionError:
        return None, (
            f"Could not connect to the Colab server at `{endpoint}`.\n"
            "Make sure the Colab notebook is running and the ngrok URL is correct."
        )
    except requests.exceptions.Timeout:
        return None, f"Request timed out after {timeout}s. The model may still be loading."
    except requests.exceptions.HTTPError as e:
        return None, f"Server returned HTTP {e.response.status_code}: {e.response.text[:300]}"
    except (json.JSONDecodeError, ValueError) as e:
        return None, f"Could not parse server response as JSON: {e}"
    except Exception as e:
        return None, f"Unexpected error: {e}"


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
    vibe_terms: List[str],
    limit: int = 50,
    server_url: str = DEFAULT_SERVER_URL,
    timeout: int = 30,
) -> tuple[List[Dict], Optional[str]]:
    """
    Query ChromaDB via the Colab server for listings ranked by cosine similarity
    to the user's vibe (soft-filter terms). Returns pure semantic ranking —
    no metadata where-clause, to avoid ChromaDB $and filter issues.

    Returns:
        (matches_list, error_string) — error_string is None on success.
    """
    if not vibe_terms:
        return [], None

    endpoint = server_url.rstrip("/") + "/search-listings"

    try:
        resp = requests.post(
            endpoint,
            json={
                "vibe_terms":  vibe_terms,
                "url_filters": [],      # no metadata filter — pure semantic ranking
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
