"""
scripts/backfill_embeddings.py
───────────────────────────────
Backfills the `embedding` column in Supabase for all listings where it is NULL.

Uses the same model as the main app: paraphrase-multilingual-MiniLM-L12-v2
Embeds: description (primary) falling back to title if empty.

Run from the project root:
    python scripts/backfill_embeddings.py
    python scripts/backfill_embeddings.py --batch-size 64 --dry-run

Progress is printed per batch; safe to Ctrl-C and re-run (already-embedded
rows are skipped because the IS NULL filter won't return them again).
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db_utils import get_client


def _load_model(model_name: str):
    from sentence_transformers import SentenceTransformer
    print(f"Loading model: {model_name} …")
    return SentenceTransformer(model_name)


def _fmt(vec) -> str:
    """Convert a numpy array or list to the pgvector text input format: [x,y,z,...]"""
    if hasattr(vec, "tolist"):
        vec = vec.tolist()
    return "[" + ",".join(str(float(v)) for v in vec) + "]"


def _update_embedding(client, url: str, embedding_str: str) -> bool:
    """UPDATE listings SET embedding = ? WHERE url = ? and return True on success."""
    try:
        resp = (
            client.table("listings")
            .update({"embedding": embedding_str})
            .eq("url", url)
            .execute()
        )
        # resp.data is a list of updated rows — empty means nothing matched
        if resp.data:
            return True
        print(f"    ? no rows updated for {url[:70]}")
        return False
    except Exception as e:
        print(f"    ✗ {url[:70]}: {e}")
        return False


def run_backfill(batch_size: int = 64, dry_run: bool = False) -> None:
    MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
    model = _load_model(MODEL_NAME)
    client = get_client()

    # Total rows that still need an embedding
    count_resp = (
        client.table("listings")
        .select("url", count="exact")
        .is_("embedding", "null")
        .limit(1)
        .execute()
    )
    total = count_resp.count or 0
    print(f"\n{total:,} rows need embedding.\n")
    if total == 0:
        print("Nothing to do.")
        return

    processed = 0
    skipped   = 0
    failed    = 0
    last_url  = ""  # cursor for stable forward pagination

    while True:
        # Fetch next batch — ORDER BY url so cursor is stable
        resp = (
            client.table("listings")
            .select("url, title, description")
            .is_("embedding", "null")
            .gt("url", last_url)
            .order("url")
            .limit(batch_size)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            break

        last_url = rows[-1]["url"]

        # Build (row, text) pairs — skip rows with no usable text
        pairs = [
            (r, (r.get("description") or r.get("title") or "").strip())
            for r in rows
        ]
        valid = [(r, t) for r, t in pairs if t]
        skipped += len(rows) - len(valid)

        if not valid:
            continue

        valid_rows  = [r for r, _ in valid]
        valid_texts = [t for _, t in valid]

        embeddings = model.encode(
            valid_texts, normalize_embeddings=True, show_progress_bar=False
        )

        if not dry_run:
            for row, emb in zip(valid_rows, embeddings):
                if _update_embedding(client, row["url"], _fmt(emb)):
                    processed += 1
                else:
                    failed += 1
        else:
            processed += len(valid)

        pct = processed / total * 100
        print(
            f"  [{pct:5.1f}%]  embedded {processed:,} / {total:,}"
            + (f"  |  skipped (no text): {skipped}" if skipped else "")
            + (f"  |  failed: {failed}" if failed else "")
        )

        time.sleep(0.05)

    tag = " (DRY RUN)" if dry_run else ""
    print(
        f"\n✅ Backfill done{tag}.\n"
        f"   Embedded : {processed:,}\n"
        f"   No text  : {skipped:,}\n"
        f"   Failed   : {failed:,}"
    )


def main():
    parser = argparse.ArgumentParser(description="Backfill embedding column in Supabase")
    parser.add_argument("--batch-size", type=int, default=64,
                        help="Rows per batch (default: 64)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Embed but do not write to Supabase")
    args = parser.parse_args()
    run_backfill(batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
