"""
embed_job.py
────────────
Batch embedding job. Processes all unembedded listings and exits.
Triggered as a Cloud Run Job by the crawler after each crawl session.

Text:  SentenceTransformer paraphrase-multilingual-MiniLM-L12-v2 (384-dim)
Image: CLIP ViT-B/32, cover photo per listing (512-dim)

Both models are baked into the Docker image at build time (HF_HUB_OFFLINE=1
at runtime) so there are no network calls on startup.
"""

import gc
import io
import json
import os

# Must be set before any torch import to prevent silent hangs in container sandboxes
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
import torch.nn.functional as F
import requests as _req
from PIL import Image
from sentence_transformers import SentenceTransformer
from transformers import CLIPModel, CLIPProcessor

from db_utils import (
    get_client,
    get_listings_missing_text_embedding,
    get_listings_missing_image_embedding,
    update_image_embedding,
)


def _text_backfill(st_model: SentenceTransformer) -> int:
    client = get_client()
    total = 0
    while True:
        rows = get_listings_missing_text_embedding(limit=64)
        if not rows:
            break
        texts = [f"{r.get('title', '')} {r.get('description', '')}".strip() for r in rows]
        urls  = [r["url"] for r in rows]
        embs  = st_model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        for url, emb in zip(urls, embs):
            vec = "[" + ",".join(str(float(v)) for v in emb.tolist()) + "]"
            try:
                client.table("listings").update({"embedding": vec}).eq("url", url).execute()
                total += 1
            except Exception as e:
                print(f"  [text] skip {url}: {e}", flush=True)
    return total


def _image_backfill(clip_model: CLIPModel, clip_proc: CLIPProcessor) -> int:
    total = 0
    BATCH = 10
    seen_urls: set[str] = set()  # prevent infinite loop when image URLs return 404
    while True:
        rows = get_listings_missing_image_embedding(limit=50)
        if not rows:
            break

        # Stop if every row in this page has already been attempted this run
        new_rows = [r for r in rows if r["url"] not in seen_urls]
        if not new_rows:
            break
        rows = new_rows
        seen_urls.update(r["url"] for r in rows)

        to_embed: list[tuple[str, str]] = []
        for row in rows:
            imgs = row.get("image_urls") or []
            if isinstance(imgs, str):
                try:
                    imgs = json.loads(imgs)
                except Exception:
                    continue
            if not imgs:
                continue
            cover = (
                imgs[0].get("medium") or imgs[0].get("small")
                or imgs[0].get("large") or imgs[0].get("thumbnail") or ""
            )
            if cover:
                to_embed.append((row["url"], cover))

        if not to_embed:
            break

        for i in range(0, len(to_embed), BATCH):
            for listing_url, img_url in to_embed[i : i + BATCH]:
                try:
                    r = _req.get(img_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                    r.raise_for_status()
                    buf    = io.BytesIO(r.content)
                    img    = Image.open(buf).convert("RGB")
                    inputs = clip_proc(images=img, return_tensors="pt")
                    img.close()
                    buf.close()

                    with torch.inference_mode():
                        vision_out = clip_model.vision_model(pixel_values=inputs["pixel_values"])
                        feat = F.normalize(
                            clip_model.visual_projection(vision_out.pooler_output), dim=-1
                        )

                    if update_image_embedding(listing_url, feat[0].tolist()):
                        total += 1
                    del inputs, vision_out, feat
                    gc.collect()
                except Exception as e:
                    print(f"  [image] skip {listing_url}: {e}", flush=True)

        if total > 0 and total % 50 == 0:
            print(f"  [image] {total} embedded so far…", flush=True)

    return total


def main() -> None:
    print("[embed-job] Loading models…", flush=True)

    st_model   = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    clip_proc  = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    clip_model.eval()

    print("[embed-job] Models loaded. Starting backfill…", flush=True)

    n_text = _text_backfill(st_model)
    print(f"[embed-job] text: {n_text} filled.", flush=True)

    n_img = _image_backfill(clip_model, clip_proc)
    print(f"[embed-job] image: {n_img} filled.", flush=True)

    print(f"[embed-job] Done — text={n_text} image={n_img}", flush=True)


if __name__ == "__main__":
    main()
