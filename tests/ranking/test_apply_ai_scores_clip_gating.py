"""
Regression tests for the apply_ai_scores() CLIP-gating bug.

Bug: a plain text "vibe" search (no template photo / uploaded photo) was
silently also encoded through CLIP's text tower and fused into the ranking
at W_IMAGE=0.7 — dominating the semantic text-similarity signal with a
model that isn't trained on Romanian and can't represent non-visual,
relational concepts ("aproape de metrou", "liniștit"). Fixed by gating the
image/CLIP search path strictly on `has_image` (an actual image_embedding
was supplied), never as a fallback for vibe text.

These tests load streamlit_interface/pipeline/utils.py directly via
importlib (rather than sys.path + `import utils`) to avoid polluting the
test process with a generic top-level "utils" module name.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

# repo_root/tests/ranking/test_apply_ai_scores_clip_gating.py -> repo_root is 2 levels up.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_UTILS_PATH = _REPO_ROOT / "streamlit_interface" / "pipeline" / "utils.py"


def _load_pipeline_utils():
    spec = importlib.util.spec_from_file_location("pipeline_utils_under_test", _UTILS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # runs the module's own sys.path setup as a side effect
    return module


putils = _load_pipeline_utils()

# `putils` module-level code already inserted streamlit_interface/embedders/
# onto sys.path, so image_embedder is importable for patching by string target.
import db_utils  # noqa: E402  (import after sys.path is primed by putils load)


def _sample_df():
    return pd.DataFrame({
        "url": ["https://a", "https://b", "https://c"],
        "title": ["Apartament A", "Apartament B", "Apartament C"],
    })


class ClipGatingTests(unittest.TestCase):
    def test_text_only_vibe_never_touches_clip_or_image_search(self):
        df = _sample_df()

        with patch.object(putils, "embed_query", return_value=[0.1] * 384) as mock_embed_query, \
             patch.object(db_utils, "search_by_text_vibe", return_value={"https://a": 0.9, "https://b": 0.4}) as mock_text_search, \
             patch.object(db_utils, "search_by_image_embedding") as mock_image_search, \
             patch("image_embedder.clip_encode_text") as mock_clip_encode:

            result_df, sorted_flag, err = putils.apply_ai_scores(
                df, vibe="apartament liniștit, aproape de metrou",
                server_url=None, url_col="url",
                image_embedding=None,
            )

        mock_embed_query.assert_called_once()
        mock_text_search.assert_called_once()
        mock_clip_encode.assert_not_called()
        mock_image_search.assert_not_called()

        self.assertTrue(sorted_flag)
        self.assertIsNone(err)
        # Ranked purely by the text score: "a" (0.9) must outrank "b" (0.4).
        ranked_urls = result_df["url"].tolist()
        self.assertLess(ranked_urls.index("https://a"), ranked_urls.index("https://b"))

    def test_image_only_uses_provided_embedding_without_text_search(self):
        df = _sample_df()
        provided_embedding = [0.2] * 512

        with patch.object(putils, "embed_query") as mock_embed_query, \
             patch.object(db_utils, "search_by_text_vibe") as mock_text_search, \
             patch.object(db_utils, "search_by_image_embedding", return_value={"https://b": 0.8}) as mock_image_search, \
             patch("image_embedder.clip_encode_text") as mock_clip_encode:

            result_df, sorted_flag, err = putils.apply_ai_scores(
                df, vibe="", server_url=None, url_col="url",
                image_embedding=provided_embedding,
            )

        mock_embed_query.assert_not_called()
        mock_text_search.assert_not_called()
        mock_clip_encode.assert_not_called()
        mock_image_search.assert_called_once()
        # The embedding passed to the image search must be exactly what the
        # caller supplied — never something derived from vibe text.
        called_embedding = mock_image_search.call_args.args[0]
        self.assertEqual(called_embedding, provided_embedding)

        self.assertTrue(sorted_flag)
        self.assertIsNone(err)

    def test_both_vibe_and_image_fuses_without_ever_calling_clip_on_text(self):
        df = _sample_df()
        provided_embedding = [0.3] * 512

        with patch.object(putils, "embed_query", return_value=[0.1] * 384), \
             patch.object(db_utils, "search_by_text_vibe", return_value={"https://a": 0.9}), \
             patch.object(db_utils, "search_by_image_embedding", return_value={"https://b": 0.8}) as mock_image_search, \
             patch("image_embedder.clip_encode_text") as mock_clip_encode:

            result_df, sorted_flag, err = putils.apply_ai_scores(
                df, vibe="apartament luminos", server_url=None, url_col="url",
                image_embedding=provided_embedding,
            )

        mock_clip_encode.assert_not_called()
        mock_image_search.assert_called_once()
        called_embedding = mock_image_search.call_args.args[0]
        self.assertEqual(called_embedding, provided_embedding)

        self.assertTrue(sorted_flag)
        self.assertIsNone(err)
        # Both "a" (text hit) and "b" (image hit) must be ranked (score > NaN),
        # "c" has no signal from either channel.
        scored = result_df.set_index("url")["_similarity_score"]
        self.assertFalse(pd.isna(scored["https://a"]))
        self.assertFalse(pd.isna(scored["https://b"]))
        self.assertTrue(pd.isna(scored["https://c"]))

    def test_no_vibe_and_no_image_is_a_no_op(self):
        df = _sample_df()
        result_df, sorted_flag, err = putils.apply_ai_scores(
            df, vibe="", server_url=None, url_col="url", image_embedding=None,
        )
        self.assertFalse(sorted_flag)
        self.assertIsNone(err)
        pd.testing.assert_frame_equal(result_df, df)


if __name__ == "__main__":
    unittest.main()
