"""
Tests for apply_ai_scores' candidate-set scoping (streamlit_interface/pipeline/utils.py).

Companion fix to tests/db/test_db_utils_scoped_search.py: this covers the
decision of *what* gets passed as candidate_urls — the caller's already
district/price/rooms/type-filtered df, deduplicated, unless it's
pathologically large (e.g. every sector selected at once), in which case
it falls back to the old unscoped global top-K search rather than sending
an enormous URL array to the RPC.
"""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

# repo_root/tests/ranking/test_apply_ai_scores_candidate_scoping.py -> repo_root is 2 levels up.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_UTILS_PATH = _REPO_ROOT / "streamlit_interface" / "pipeline" / "utils.py"


def _load_pipeline_utils():
    spec = importlib.util.spec_from_file_location("pipeline_utils_under_test_scoping", _UTILS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


putils = _load_pipeline_utils()

import db_utils  # noqa: E402


class CandidateScopingTests(unittest.TestCase):
    def test_small_candidate_set_is_passed_as_candidate_urls(self):
        df = pd.DataFrame({"url": ["https://a", "https://b", "https://c"]})

        with patch.object(putils, "embed_query", return_value=[0.1] * 384), \
             patch.object(db_utils, "search_by_text_vibe", return_value={}) as mock_text_search:

            putils.apply_ai_scores(df, vibe="apartament luminos", server_url=None, url_col="url")

        called_kwargs = mock_text_search.call_args.kwargs
        self.assertEqual(sorted(called_kwargs["candidate_urls"]), ["https://a", "https://b", "https://c"])

    def test_duplicate_urls_in_df_are_deduplicated_before_scoping(self):
        df = pd.DataFrame({"url": ["https://a", "https://a", "https://b"]})

        with patch.object(putils, "embed_query", return_value=[0.1] * 384), \
             patch.object(db_utils, "search_by_text_vibe", return_value={}) as mock_text_search:

            putils.apply_ai_scores(df, vibe="apartament luminos", server_url=None, url_col="url")

        called_kwargs = mock_text_search.call_args.kwargs
        self.assertEqual(sorted(called_kwargs["candidate_urls"]), ["https://a", "https://b"])

    def test_oversized_candidate_set_falls_back_to_unscoped_search(self):
        """Beyond the defensive cap, candidate_urls must be None (letting
        the RPC's own global top-K path run) rather than sending a huge
        URL array."""
        huge_df = pd.DataFrame({"url": [f"https://listing-{i}" for i in range(2500)]})

        with patch.object(putils, "embed_query", return_value=[0.1] * 384), \
             patch.object(db_utils, "search_by_text_vibe", return_value={}) as mock_text_search:

            putils.apply_ai_scores(huge_df, vibe="apartament luminos", server_url=None, url_col="url")

        called_kwargs = mock_text_search.call_args.kwargs
        self.assertIsNone(called_kwargs["candidate_urls"])

    def test_image_search_also_receives_the_same_candidate_scoping(self):
        df = pd.DataFrame({"url": ["https://a", "https://b"]})

        with patch.object(db_utils, "search_by_image_embedding", return_value={}) as mock_image_search:
            putils.apply_ai_scores(
                df, vibe="", server_url=None, url_col="url",
                image_embedding=[0.1] * 512,
            )

        called_kwargs = mock_image_search.call_args.kwargs
        self.assertEqual(sorted(called_kwargs["candidate_urls"]), ["https://a", "https://b"])


if __name__ == "__main__":
    unittest.main()
