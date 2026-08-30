"""
Tests for pipeline_core.apply_ai_scores's per-channel score columns
(_text_similarity / _image_similarity), added alongside the fused
_similarity_score so the API can surface ScoredListing.textSimilarity /
.imageSimilarity separately instead of aliasing both to the same fused
number. The RRF-fusion/CLIP-gating behavior itself is already covered by
tests/ranking/test_apply_ai_scores_clip_gating.py and
tests/ranking/test_apply_ai_scores_candidate_scoping.py (which exercise
this same function indirectly via the streamlit_interface/pipeline/utils.py
wrapper) — this file only covers the new columns.
"""
import unittest
from unittest.mock import patch

import pandas as pd

import db_utils
import pipeline_core


def _df():
    return pd.DataFrame({"url": ["https://a", "https://b", "https://c"]})


class PerChannelScoreColumnTests(unittest.TestCase):
    def test_text_only_sets_text_similarity_and_no_image_column(self):
        with patch.object(db_utils, "search_by_text_vibe", return_value={"https://a": 0.9, "https://b": 0.4}):
            result, sorted_flag, err = pipeline_core.apply_ai_scores(
                _df(), "liniștit", url_col="url", embed_query=lambda v: [0.1] * 384,
            )
        self.assertTrue(sorted_flag)
        self.assertIsNone(err)
        self.assertIn("_text_similarity", result.columns)
        self.assertNotIn("_image_similarity", result.columns)
        self.assertEqual(result.set_index("url").loc["https://a", "_text_similarity"], 0.9)

    def test_image_only_sets_image_similarity_and_no_text_column(self):
        with patch.object(db_utils, "search_by_image_embedding", return_value={"https://b": 0.8}):
            result, sorted_flag, err = pipeline_core.apply_ai_scores(
                _df(), "", url_col="url", embed_query=lambda v: None, image_embedding=[0.2] * 512,
            )
        self.assertTrue(sorted_flag)
        self.assertIsNone(err)
        self.assertIn("_image_similarity", result.columns)
        self.assertNotIn("_text_similarity", result.columns)
        self.assertEqual(result.set_index("url").loc["https://b", "_image_similarity"], 0.8)

    def test_both_channels_set_both_columns_independently_of_the_fused_score(self):
        with patch.object(db_utils, "search_by_text_vibe", return_value={"https://a": 0.9}), \
             patch.object(db_utils, "search_by_image_embedding", return_value={"https://b": 0.8}):
            result, sorted_flag, err = pipeline_core.apply_ai_scores(
                _df(), "luminos", url_col="url", embed_query=lambda v: [0.1] * 384, image_embedding=[0.2] * 512,
            )
        self.assertTrue(sorted_flag)
        self.assertIsNone(err)
        row_a = result.set_index("url").loc["https://a"]
        row_b = result.set_index("url").loc["https://b"]
        self.assertEqual(row_a["_text_similarity"], 0.9)
        self.assertTrue(pd.isna(row_a["_image_similarity"]))
        self.assertEqual(row_b["_image_similarity"], 0.8)
        self.assertTrue(pd.isna(row_b["_text_similarity"]))
        # the fused RRF score is a separate number from either raw channel score
        self.assertIn("_similarity_score", result.columns)

    def test_neither_channel_running_sets_no_score_columns_at_all(self):
        result, sorted_flag, err = pipeline_core.apply_ai_scores(
            _df(), "", url_col="url", embed_query=lambda v: None, image_embedding=None,
        )
        self.assertFalse(sorted_flag)
        self.assertIsNone(err)
        self.assertNotIn("_text_similarity", result.columns)
        self.assertNotIn("_image_similarity", result.columns)
        self.assertNotIn("_similarity_score", result.columns)


if __name__ == "__main__":
    unittest.main()
