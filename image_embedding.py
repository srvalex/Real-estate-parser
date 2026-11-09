"""
image_embedding.py
─────────────────
Streamlit-free CLIP image embedding for api/template_photos.py — mirrors
streamlit_interface/embedders/image_embedder.py::embed_local_image, minus
the `streamlit` import/@st.cache_resource (replaced with functools.lru_cache,
same pattern as embedding.py). Only the CLIP *vision* tower is loaded; the
rest of image_embedder.py (ChromaDB collection, Colab-server client,
`clip_encode_text`, ChromaDB-backed search) is an older architecture
superseded by the Supabase `image_embedding` column + pgvector
(db_utils.search_by_image_embedding) — not ported here.

Same model as what populated listings.image_embedding
(openai/clip-vit-base-patch32's vision tower), so a photo embedded here
lands in the same 512-dim space and cosine similarity against listing
photos is meaningful. Verified live (2026-08-30): fresh embeddings of the
4 template photos match streamlit_interface/template_photos/embeddings.json
at cosine similarity 1.000000.
"""
from functools import lru_cache

MODEL_NAME = "openai/clip-vit-base-patch32"


@lru_cache(maxsize=1)
def _load_clip_vision_model():
    """Load the CLIP vision tower (~600MB, downloaded from HuggingFace on
    first use) once per process."""
    from transformers import CLIPVisionModelWithProjection, CLIPProcessor
    processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    model = CLIPVisionModelWithProjection.from_pretrained(MODEL_NAME)
    model.eval()
    return model, processor


def embed_image(image_path: str) -> list | None:
    """Encode a local image file with the CLIP vision tower.
    Returns a 512-dim embedding list, or None on failure."""
    try:
        import torch
        from PIL import Image
        model, processor = _load_clip_vision_model()
        image = Image.open(image_path).convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs)
            return outputs.image_embeds[0].cpu().numpy().tolist()
    except Exception as e:
        print(f"  [image_embedding] error embedding {image_path}: {e}")
        return None
