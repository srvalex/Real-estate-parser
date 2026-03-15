"""
ollama_parser.py
────────────────
Sends the user's free-text "vibe" to the remote Colab/Ollama FastAPI server
and returns a structured JSON object used to filter real-estate listings.

The remote server exposes:
    POST /extract-keywords
    Body:  { "text": "<Romanian prompt>" }
    Returns: { "amenities": [...], "vibes": [...], "restrictions": [...] }

Set COLAB_SERVER_URL at runtime via the Streamlit sidebar input.
"""

import json
import requests
from typing import Optional

# Default placeholder — overridden at runtime by the Streamlit URL input
DEFAULT_SERVER_URL = "https://josue-unbiddable-unreproachably.ngrok-free.dev"
ENDPOINT_PATH      = "/extract-keywords"


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
