"""
api/template_photos.py
─────────────────
The 4 curated "visual style" reference photos (streamlit_interface/template_photos/)
used for photo-similarity search — relocation of
streamlit_interface/components/home.py's template-photo picker logic
(labels, cache-then-embed lookup, multi-select averaging), Streamlit-free.

Embeddings are computed once per process and held in memory: 4 photos,
never change at runtime, no reason to recompute per request. Prefers the
precomputed streamlit_interface/template_photos/embeddings.json cache
(verified live against a fresh CLIP run, cosine similarity 1.000000);
falls back to embedding via CLIP directly (image_embedding.embed_image) for
any photo not already in that cache, exactly like the Streamlit picker did.
"""
import json
import os
from functools import lru_cache

from image_embedding import embed_image

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "streamlit_interface", "template_photos")
_CACHE_PATH = os.path.join(_TEMPLATE_DIR, "embeddings.json")
_SUPPORTED_EXT = (".png", ".jpg", ".jpeg", ".webp")

# Order matches the original Streamlit picker (streamlit_interface/components/home.py).
TEMPLATE_LABELS = {
    "template_1": "Mobilat modern",
    "template_2": "Clasic, luxos",
    "template_3": "Primitor",
    "template_4": "Bloc comunist",
}


def _find_file(photo_id: str) -> str | None:
    for ext in _SUPPORTED_EXT:
        fpath = os.path.join(_TEMPLATE_DIR, f"{photo_id}{ext}")
        if os.path.exists(fpath):
            return fpath
    return None


@lru_cache(maxsize=1)
def _embeddings() -> dict:
    """{photo_id: 512-dim embedding}, computed once per process."""
    cache = {}
    if os.path.exists(_CACHE_PATH):
        with open(_CACHE_PATH) as f:
            cache = json.load(f)

    result: dict[str, list] = {}
    for photo_id in TEMPLATE_LABELS:
        fpath = _find_file(photo_id)
        if not fpath:
            continue
        vec = cache.get(os.path.basename(fpath))
        if vec is None:
            vec = embed_image(fpath)
        if vec is not None:
            result[photo_id] = vec
    return result


def list_template_photos() -> list[dict]:
    return [{"id": pid, "label": label} for pid, label in TEMPLATE_LABELS.items()]


def get_combined_embedding(photo_ids: list) -> list | None:
    """Single photo -> its embedding as-is. Multiple -> normalised average,
    same as the original picker (components/home.py) so selecting several
    "vibes" blends them into one query point instead of only matching the
    last one picked."""
    embeddings = [_embeddings()[pid] for pid in photo_ids if pid in _embeddings()]
    if not embeddings:
        return None
    if len(embeddings) == 1:
        return embeddings[0]

    import numpy as np
    arr = np.array(embeddings)
    avg = arr.mean(axis=0)
    norm = np.linalg.norm(avg)
    return (avg / norm if norm > 0 else avg).tolist()
