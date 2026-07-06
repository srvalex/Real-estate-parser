"""
demo/rrf_fusion_demo.py
────────────────────────
Presentation CLI -- demonstrates how the app fuses two independent similarity
searches (text-embedding + image-embedding) into one ranked result list via
Reciprocal Rank Fusion (RRF), exactly as production does in
streamlit_interface/pipeline/utils.py::apply_ai_scores().

Query-embedding generation is skipped here (hardware limitations on the
presentation machine): a hardcoded prompt and its two precomputed embeddings
(paraphrase-multilingual-MiniLM-L12-v2 text embedding, CLIP ViT-B/32 text-tower
embedding) are loaded from hardcoded_query_embeddings.json instead of being
generated live. See demo/README.md for how that file was produced.

Usage:
    python demo/rrf_fusion_demo.py [top_n]

Output: demo/output/fusion/rrf_demo.md
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

import db_utils
from rrf import rrf_fuse

EMBEDDINGS_FILE = os.path.join(_HERE, "hardcoded_query_embeddings.json")
OUTPUT_DIR = os.path.join(_HERE, "output", "fusion")


def _fetch_listing_meta(urls: list) -> dict:
    """Look up title/platform/price for a set of URLs, for a readable table."""
    if not urls:
        return {}
    client = db_utils.get_client()
    meta: dict = {}
    CHUNK = 40
    for i in range(0, len(urls), CHUNK):
        chunk = urls[i:i + CHUNK]
        resp = (
            client.table("listings")
            .select("url, title, platform, district, price_numeric, price_currency")
            .in_("url", chunk)
            .execute()
        )
        for row in resp.data or []:
            meta[row["url"]] = row
    return meta


def _md_table(rows: list, headers: list) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines) + "\n"


def main():
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    if not os.path.exists(EMBEDDINGS_FILE):
        print(f"Missing {EMBEDDINGS_FILE} -- see demo/README.md to generate it first")
        sys.exit(1)

    with open(EMBEDDINGS_FILE, encoding="utf-8") as f:
        payload = json.load(f)
    prompt         = payload["prompt"]
    text_embedding = payload["text_embedding"]
    clip_embedding = payload["clip_embedding"]

    print(f"Prompt (hardcoded): {prompt!r}")
    print("Querying Supabase pgvector for text + image similarity ...")

    text_scores  = db_utils.search_by_text_vibe(text_embedding, limit=1000)
    image_scores = db_utils.search_by_image_embedding(clip_embedding, limit=1000)

    print(f"  text matches:  {len(text_scores)}")
    print(f"  image matches: {len(image_scores)}")

    all_urls = set(text_scores) | set(image_scores)
    final_scores = rrf_fuse(text_scores, image_scores, all_urls)
    if final_scores:
        _max = max(final_scores.values())
        final_scores = {u: s / _max for u, s in final_scores.items()}

    meta = _fetch_listing_meta(list(all_urls))

    def _title(u: str) -> str:
        t = meta.get(u, {}).get("title") or "(no title)"
        return (t[:45] + "...") if len(t) > 45 else t

    text_ranked  = sorted(text_scores.items(),  key=lambda kv: kv[1], reverse=True)[:top_n]
    image_ranked = sorted(image_scores.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    fused_ranked = sorted(final_scores.items(), key=lambda kv: kv[1], reverse=True)[:top_n]

    text_rank_of = {
        u: r for r, (u, _) in
        enumerate(sorted(text_scores.items(), key=lambda kv: kv[1], reverse=True), start=1)
    }
    image_rank_of = {
        u: r for r, (u, _) in
        enumerate(sorted(image_scores.items(), key=lambda kv: kv[1], reverse=True), start=1)
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "rrf_demo.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# RRF score fusion demo\n\n")
        f.write(f"**Prompt:** {prompt}\n\n")
        f.write(
            "Two independent pgvector searches run against Supabase, then fused by "
            "Reciprocal Rank Fusion -- the exact logic in "
            "`streamlit_interface/pipeline/utils.py::apply_ai_scores()` / `rrf_fuse()`.\n\n"
        )

        f.write(f"## 1. Text-similarity ranking (top {top_n})\n\n")
        f.write("Model: `paraphrase-multilingual-MiniLM-L12-v2` (384-dim) -> `match_listings` RPC\n\n")
        f.write(_md_table(
            [(i + 1, _title(u), f"{s:.4f}", u) for i, (u, s) in enumerate(text_ranked)],
            ["#", "Title", "Similarity", "URL"],
        ))

        f.write(f"\n## 2. Image-similarity ranking (top {top_n})\n\n")
        f.write("Model: CLIP ViT-B/32 text tower (512-dim) -> `match_listings_by_image` RPC\n\n")
        f.write(_md_table(
            [(i + 1, _title(u), f"{s:.4f}", u) for i, (u, s) in enumerate(image_ranked)],
            ["#", "Title", "Similarity", "URL"],
        ))

        f.write(f"\n## 3. Fused ranking -- Reciprocal Rank Fusion (top {top_n})\n\n")
        f.write("`rrf(url) = 0.3 / (60 + text_rank) + 0.7 / (60 + image_rank)`, normalised to [0, 1]\n\n")
        f.write(_md_table(
            [
                (i + 1, _title(u), text_rank_of.get(u, "-"), image_rank_of.get(u, "-"), f"{s:.4f}", u)
                for i, (u, s) in enumerate(fused_ranked)
            ],
            ["#", "Title", "Text rank", "Image rank", "RRF score", "URL"],
        ))

    print(f"\nFusion demo written to {out_path}")


if __name__ == "__main__":
    main()
