"""
Tests for the candidate_urls scoping parameter on db_utils.search_by_text_vibe
and db_utils.search_by_image_embedding.

Bug: both functions only ever asked Supabase for the global top-`limit`
nearest neighbours across the WHOLE listings table, with no way to scope to
a caller's already-filtered candidate set. A listing outside that global
cutoff got no score at all, even if it was the best match within the
caller's actual filtered pool (e.g. one district) — silently sorted last,
no error shown. This risk grows with table size, not with anything wrong
in a specific search.

Fix: both functions accept an optional candidate_urls list and forward it
to the corresponding pgvector RPC (match_listings / match_listings_by_image),
which — when given — scores every URL in that list, ignoring match_count.
"""
import unittest
from unittest.mock import patch, MagicMock

import db_utils


class ScopedTextSearchTests(unittest.TestCase):
    def setUp(self):
        self.anon_client = MagicMock()
        self._patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.anon_client.rpc.return_value.execute.return_value = MagicMock(data=[])

    def test_candidate_urls_forwarded_to_the_rpc_when_given(self):
        db_utils.search_by_text_vibe([0.1] * 384, candidate_urls=["https://a", "https://b"])

        call_args = self.anon_client.rpc.call_args
        self.assertEqual(call_args.args[0], "match_listings")
        params = call_args.args[1]
        self.assertEqual(params["candidate_urls"], ["https://a", "https://b"])

    def test_candidate_urls_key_is_omitted_entirely_when_not_given(self):
        """Omitting the key (rather than sending candidate_urls=None) lets
        the SQL function's own DEFAULT NULL apply — asserting its absence
        locks in that we don't rely on supabase-py serializing None the
        same way as an omitted key."""
        db_utils.search_by_text_vibe([0.1] * 384)

        params = self.anon_client.rpc.call_args.args[1]
        self.assertNotIn("candidate_urls", params)

    def test_empty_candidate_list_is_treated_as_not_given(self):
        db_utils.search_by_text_vibe([0.1] * 384, candidate_urls=[])

        params = self.anon_client.rpc.call_args.args[1]
        self.assertNotIn("candidate_urls", params)


class ScopedImageSearchTests(unittest.TestCase):
    def setUp(self):
        self.anon_client = MagicMock()
        self._patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.anon_client.rpc.return_value.execute.return_value = MagicMock(data=[])

    def test_candidate_urls_forwarded_to_the_rpc_when_given(self):
        db_utils.search_by_image_embedding([0.1] * 512, candidate_urls=["https://a"])

        call_args = self.anon_client.rpc.call_args
        self.assertEqual(call_args.args[0], "match_listings_by_image")
        params = call_args.args[1]
        self.assertEqual(params["candidate_urls"], ["https://a"])

    def test_candidate_urls_key_is_omitted_entirely_when_not_given(self):
        db_utils.search_by_image_embedding([0.1] * 512)

        params = self.anon_client.rpc.call_args.args[1]
        self.assertNotIn("candidate_urls", params)


if __name__ == "__main__":
    unittest.main()
