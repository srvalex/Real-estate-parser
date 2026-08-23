"""
Tests for apply_ai_scores' candidate-set scoping (streamlit_interface/pipeline/utils.py).

Companion fix to tests/db/test_db_utils_scoped_search.py: this covers the
decision of *what* gets passed as candidate_urls — the caller's already
district/price/rooms/type-filtered df, deduplicated. There is deliberately
no size cap here (BUGS.md #7): a large candidate set (e.g. every sector
selected at once) used to fall back to the old unscoped global top-K search,
which could silently miss a niche-filtered search's actual best matches.
db_utils.search_by_text_vibe/search_by_image_embedding now split a large
candidate_urls list into bounded RPC batches internally instead
(tests/db/test_db_utils_scoped_search.py covers that batching), so this
module always passes the full filtered set through.
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

    def test_oversized_candidate_set_is_still_passed_through_in_full(self):
        """A large candidate set (e.g. every sector selected at once) must
        not fall back to an unscoped global search -- db_utils is
        responsible for batching it into bounded RPC calls, not this
        module for shrinking or dropping it."""
        huge_df = pd.DataFrame({"url": [f"https://listing-{i}" for i in range(2500)]})

        with patch.object(putils, "embed_query", return_value=[0.1] * 384), \
             patch.object(db_utils, "search_by_text_vibe", return_value={}) as mock_text_search:

            putils.apply_ai_scores(huge_df, vibe="apartament luminos", server_url=None, url_col="url")

        called_kwargs = mock_text_search.call_args.kwargs
        self.assertEqual(len(called_kwargs["candidate_urls"]), 2500)

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
