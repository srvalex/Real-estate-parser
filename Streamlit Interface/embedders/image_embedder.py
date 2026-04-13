"""
image_embedder.py
─────────────────
Client for the Colab CLIP server (helper notebooks/clip_server.ipynb).

Sends image URLs to the remote server, gets back embeddings + room labels,
and stores them in the local ChromaDB `listing_image_embeddings` collection.
"""

import hashlib
import json
import os
import requests
import streamlit as st

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE           = os.path.dirname(os.path.abspath(__file__))
CHROMA_DB_PATH  = os.path.join(_HERE, "..", "..", "ChromaDB")
COLLECTION_NAME = "listing_image_embeddings"

DEFAULT_IMAGE_SERVER_URL = ""   # filled in from the Streamlit sidebar


@st.cache_resource
def _load_collection():
    """Open (or create) the image embeddings ChromaDB collection."""
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def check_image_server(server_url: str, timeout: int = 5) -> bool:
    """Return True if the Colab CLIP server is reachable."""
    try:
        resp = requests.get(f"{server_url.rstrip('/')}/health", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def _url_to_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def embed_cover_photos(df, server_url: str) -> tuple[int, str | None]:
    """
    Embed the cover photo (position 0) for each listing in df.

    Sends image URLs to the Colab CLIP server in batches.
    Skips listings without image_urls or already embedded ones.

    Returns:
        (num_embedded, error_string)  — error_string is None on success.
    """
    if df.empty or "image_urls" not in df.columns:
        return 0, None

    if not server_url:
        return 0, "No CLIP server URL configured."

    server_url = server_url.rstrip("/")

    try:
        collection = _load_collection()
    except Exception as e:
        return 0, f"ChromaDB error: {e}"

    url_col = "url" if "url" in df.columns else ("link" if "link" in df.columns else None)
    if url_col is None:
        return 0, "No URL column found in dataframe."

    # Build list of (listing_url, cover_image_url) for listings not yet embedded
    to_embed = []
    seen_cover_urls: set[str] = set()   # dedup within this batch
    for _, row in df.iterrows():
        listing_url = str(row.get(url_col) or "").strip()
        raw_images  = row.get("image_urls")
        if not listing_url or not raw_images:
            continue

        if isinstance(raw_images, str):
            try:
                raw_images = json.loads(raw_images)
            except Exception:
                continue

        if not isinstance(raw_images, list) or not raw_images:
            continue

        cover_url = raw_images[0].get("medium") or raw_images[0].get("small") or ""
        if not cover_url or cover_url in seen_cover_urls:
            continue

        doc_id = _url_to_id(cover_url)
        existing = collection.get(ids=[doc_id])
        if existing["ids"]:
            continue  # already embedded

        seen_cover_urls.add(cover_url)
        to_embed.append((listing_url, cover_url))

    if not to_embed:
        return 0, None

    # Send to Colab server in batches of 10
    BATCH_SIZE = 10
    embedded = 0

    for i in range(0, len(to_embed), BATCH_SIZE):
        batch = to_embed[i:i + BATCH_SIZE]
        image_urls = [cover_url for _, cover_url in batch]
        listing_map = {cover_url: listing_url for listing_url, cover_url in batch}

        try:
            resp = requests.post(
                f"{server_url}/embed",
                json={"urls": image_urls},
                timeout=120,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except Exception as e:
            return embedded, f"Server error on batch {i // BATCH_SIZE + 1}: {e}"

        ids, embeddings, metadatas, documents = [], [], [], []
        for r in results:
            if "error" in r or "embedding" not in r:
                continue
            cover_url   = r["url"]
            listing_url = listing_map.get(cover_url, "")
            doc_id      = _url_to_id(cover_url)

            ids.append(doc_id)
            embeddings.append(r["embedding"])
            metadatas.append({
                "listing_url": listing_url,
                "image_url":   cover_url,
                "room_labels": ", ".join(r.get("labels", ["other"])),
                "position":    0,
            })
            documents.append(cover_url)

        if ids:
            collection.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
            embedded += len(ids)

    return embedded, None


def embed_all_photos(df, server_url: str) -> tuple[int, str | None]:
    """
    Embed ALL photos for each listing in df (every position, not just cover).
    Used by the batch job. For the live scraping flow, use embed_cover_photos.

    Returns:
        (num_embedded, error_string)
    """
    if df.empty or "image_urls" not in df.columns:
        return 0, None

    if not server_url:
        return 0, "No CLIP server URL configured."

    server_url = server_url.rstrip("/")

    try:
        collection = _load_collection()
    except Exception as e:
        return 0, f"ChromaDB error: {e}"

    url_col = "url" if "url" in df.columns else ("link" if "link" in df.columns else None)
    if url_col is None:
        return 0, "No URL column found in dataframe."

    # Build list of (listing_url, photo_url, position) not yet embedded
    to_embed: list[tuple[str, str, int]] = []
    seen_photo_urls: set[str] = set()   # dedup within this batch
    for _, row in df.iterrows():
        listing_url = str(row.get(url_col) or "").strip()
        raw_images  = row.get("image_urls")
        if not listing_url or not raw_images:
            continue

        if isinstance(raw_images, str):
            try:
                raw_images = json.loads(raw_images)
            except Exception:
                continue

        if not isinstance(raw_images, list) or not raw_images:
            continue

        for pos, img in enumerate(raw_images):
            photo_url = img.get("medium") or img.get("small") or img.get("thumbnail") or ""
            if not photo_url or photo_url in seen_photo_urls:
                continue
            doc_id = _url_to_id(photo_url)
            existing = collection.get(ids=[doc_id])
            if existing["ids"]:
                continue  # already embedded
            seen_photo_urls.add(photo_url)
            to_embed.append((listing_url, photo_url, pos))

    if not to_embed:
        return 0, None

    BATCH_SIZE = 10
    embedded = 0

    for i in range(0, len(to_embed), BATCH_SIZE):
        batch      = to_embed[i:i + BATCH_SIZE]
        photo_urls = [photo_url for _, photo_url, _ in batch]
        meta_map   = {photo_url: (listing_url, pos) for listing_url, photo_url, pos in batch}

        try:
            resp = requests.post(
                f"{server_url}/embed",
                json={"urls": photo_urls},
                timeout=120,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except Exception as e:
            return embedded, f"Server error on batch {i // BATCH_SIZE + 1}: {e}"

        ids, embeddings, metadatas, documents = [], [], [], []
        for r in results:
            if "error" in r or "embedding" not in r:
                continue
            photo_url               = r["url"]
            listing_url, pos        = meta_map.get(photo_url, ("", 0))
            doc_id                  = _url_to_id(photo_url)

            ids.append(doc_id)
            embeddings.append(r["embedding"])
            metadatas.append({
                "listing_url": listing_url,
                "image_url":   photo_url,
                "room_labels": ", ".join(r.get("labels", ["other"])),
                "position":    pos,
            })
            documents.append(photo_url)

        if ids:
            collection.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
            embedded += len(ids)

    return embedded, None


@st.cache_resource(show_spinner=False)
def _load_clip_vision_model():
    """
    Load the CLIP vision tower (CLIPVisionModelWithProjection, ~300 MB).
    Used to embed local template photos into the same 512-dim space as the
    image embeddings stored in ChromaDB.
    Cached once per Streamlit server process.
    """
    from transformers import CLIPVisionModelWithProjection, CLIPProcessor
    MODEL_NAME = "openai/clip-vit-base-patch32"
    processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    model     = CLIPVisionModelWithProjection.from_pretrained(MODEL_NAME)
    model.eval()
    return model, processor


def embed_local_image(image_path: str) -> list[float] | None:
    """
    Encode a local image file with the CLIP vision tower.
    Returns a 512-dim embedding list, or None on failure.
    """
    try:
        import torch
        from PIL import Image
        model, processor = _load_clip_vision_model()
        image  = Image.open(image_path).convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
        with torch.no_grad():
            outputs   = model(**inputs)
            embedding = outputs.image_embeds[0].cpu().numpy().tolist()
        return embedding
    except Exception:
        return None


def search_by_image_embedding(embedding: list[float], limit: int = 3000) -> tuple[dict, str | None]:
    """
    Query the image ChromaDB collection with a pre-computed 512-dim CLIP embedding.
    Works for both image→image and text→image queries as long as the vector is in
    CLIP's shared embedding space.

    Groups results by listing_url and returns the best (min distance) score per listing.

    Returns:
        ({listing_url: similarity_score_0_to_1}, error_string | None)
    """
    try:
        collection = _load_collection()
        if collection.count() == 0:
            return {}, None
    except Exception:
        return {}, None

    try:
        count   = collection.count()
        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(limit, count),
            include=["metadatas", "distances"],
        )
    except Exception as e:
        return {}, f"ChromaDB image query error: {e}"

    listing_distances: dict[str, float] = {}
    for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
        listing_url = meta.get("listing_url", "")
        if not listing_url:
            continue
        if listing_url not in listing_distances or dist < listing_distances[listing_url]:
            listing_distances[listing_url] = dist

    if not listing_distances:
        return {}, None

    dists   = list(listing_distances.values())
    min_d   = min(dists)
    max_d   = max(dists)
    d_range = (max_d - min_d) if max_d > min_d else 1.0
    score_map = {url: 1.0 - (d - min_d) / d_range for url, d in listing_distances.items()}
    return score_map, None


@st.cache_resource(show_spinner=False)
def _load_clip_text_model():
    """
    Load only the CLIP text tower (CLIPTextModelWithProjection, ~125 MB).
    Runs entirely on CPU — fast enough for a single query embedding at search time.
    Cached once per Streamlit server process.
    """
    from transformers import CLIPTextModelWithProjection, CLIPTokenizer
    MODEL_NAME = "openai/clip-vit-base-patch32"
    tokenizer = CLIPTokenizer.from_pretrained(MODEL_NAME)
    model     = CLIPTextModelWithProjection.from_pretrained(MODEL_NAME)
    model.eval()
    return model, tokenizer


def search_by_text_vibe(vibe: str, limit: int = 500) -> tuple[dict, str | None]:
    """
    Encode the user's vibe text with a LOCAL CLIP text encoder, then query the
    image embeddings ChromaDB collection for visually matching listings.

    No Colab server required — only the text tower of CLIP is loaded locally.
    The image embeddings were created by the Colab server's CLIP image encoder,
    both in the same 512-dim space, so cosine similarity works across modalities.

    Groups results by listing_url and returns the best (max similarity) score
    per listing — a listing with any strongly matching photo ranks highly.

    Returns:
        ({listing_url: similarity_score_0_to_1}, error_string | None)
    """
    if not vibe.strip():
        return {}, None

    # ── Quick check: skip if no image embeddings exist yet ───────────────────
    try:
        collection = _load_collection()
        if collection.count() == 0:
            return {}, None
    except Exception:
        return {}, None

    # ── Encode vibe text locally with CLIP text tower ─────────────────────────
    try:
        import torch
        model, tokenizer = _load_clip_text_model()
        inputs = tokenizer(
            [vibe],
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=77,          # CLIP's context window
        )
        with torch.no_grad():
            outputs        = model(**inputs)
            text_embedding = outputs.text_embeds[0].cpu().numpy().tolist()
    except Exception as e:
        return {}, f"Local CLIP text encoding error: {e}"

    # ── Query image ChromaDB ──────────────────────────────────────────────────
    try:
        count   = collection.count()
        results = collection.query(
            query_embeddings=[text_embedding],
            n_results=min(limit, count),
            include=["metadatas", "distances"],
        )
    except Exception as e:
        return {}, f"ChromaDB image query error: {e}"

    # ── Group by listing_url, keep best (min distance) per listing ────────────
    listing_distances: dict[str, float] = {}
    for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
        listing_url = meta.get("listing_url", "")
        if not listing_url:
            continue
        if listing_url not in listing_distances or dist < listing_distances[listing_url]:
            listing_distances[listing_url] = dist

    if not listing_distances:
        return {}, None

    # ── Normalise distances → [0, 1] similarity ───────────────────────────────
    dists   = list(listing_distances.values())
    min_d   = min(dists)
    max_d   = max(dists)
    d_range = (max_d - min_d) if max_d > min_d else 1.0
    score_map = {url: 1.0 - (d - min_d) / d_range for url, d in listing_distances.items()}

    return score_map, None
