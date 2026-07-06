"""
Precompute CLIP embeddings for all images in template_photos/ and write
them to template_photos/embeddings.json  ({filename: [512 floats]}).

Run once (or whenever new template photos are added):
    python scripts/precompute_template_embeddings.py
"""

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_DIR = os.path.join(_ROOT, "Streamlit Interface", "template_photos")
_OUT = os.path.join(_TEMPLATE_DIR, "embeddings.json")

sys.path.insert(0, os.path.join(_ROOT, "Streamlit Interface", "embedders"))

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}


def main():
    from image_embedder import embed_local_image

    existing: dict = {}
    if os.path.exists(_OUT):
        with open(_OUT) as f:
            existing = json.load(f)
        print(f"Loaded {len(existing)} existing embedding(s) from cache.")

    photos = [
        f for f in os.listdir(_TEMPLATE_DIR)
        if os.path.splitext(f)[1].lower() in SUPPORTED
    ]

    updated = 0
    for fname in sorted(photos):
        if fname in existing:
            print(f"  skip  {fname}  (already cached)")
            continue
        path = os.path.join(_TEMPLATE_DIR, fname)
        print(f"  embed {fname}…", end=" ", flush=True)
        vec = embed_local_image(path)
        if vec is None:
            print("FAILED")
            continue
        existing[fname] = vec
        updated += 1
        print(f"ok  ({len(vec)}-dim)")

    with open(_OUT, "w") as f:
        json.dump(existing, f)

    print(f"\nDone. {updated} new embedding(s) written to {_OUT}")


if __name__ == "__main__":
    main()
