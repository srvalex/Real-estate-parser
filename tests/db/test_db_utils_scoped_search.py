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

BUGS.md #7 follow-up: pipeline/utils.py used to cap the candidate set at
2000 and fall back to an unscoped global search past that size, reopening
the exact silent-miss problem this scoping exists to prevent. Fixed by
having these two functions batch a large candidate_urls list into multiple
bounded RPC calls (_RPC_CANDIDATE_CHUNK_SIZE each) and merge the results,
so callers never need to shrink or drop their candidate set — see the
ScopedTextSearchChunkingTests / ScopedImageSearchChunkingTests classes below.
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


class RpcWithRetryTests(unittest.TestCase):
    """_rpc_with_retry: a single RPC call is retried once on failure before
    giving up. Live testing 2026-08-23 showed a chunk that times out on its
    first attempt (a cold query-plan cost for that call shape) very
    reliably succeeds on an immediate retry, so this is worth doing before
    treating a chunk as unservable."""

    def test_succeeds_on_first_try_without_a_retry(self):
        client = MagicMock()
        client.rpc.return_value.execute.return_value = "ok"

        result = db_utils._rpc_with_retry(client, "match_listings", {"a": 1})

        self.assertEqual(result, "ok")
        self.assertEqual(client.rpc.call_count, 1)

    def test_retries_once_after_a_failure_and_returns_the_retry_result(self):
        client = MagicMock()
        client.rpc.return_value.execute.side_effect = [Exception("cold plan timeout"), "ok"]

        result = db_utils._rpc_with_retry(client, "match_listings", {"a": 1})

        self.assertEqual(result, "ok")
        self.assertEqual(client.rpc.call_count, 2)

    def test_propagates_the_exception_if_the_retry_also_fails(self):
        client = MagicMock()
        client.rpc.return_value.execute.side_effect = Exception("still down")

        with self.assertRaises(Exception):
            db_utils._rpc_with_retry(client, "match_listings", {"a": 1})

        self.assertEqual(client.rpc.call_count, 2)


class ScopedTextSearchChunkingTests(unittest.TestCase):
    def setUp(self):
        self.anon_client = MagicMock()
        self._patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_candidate_set_at_or_under_the_chunk_size_is_a_single_call(self):
        urls = [f"https://listing-{i}" for i in range(db_utils._RPC_CANDIDATE_CHUNK_SIZE)]
        self.anon_client.rpc.return_value.execute.return_value = MagicMock(
            data=[{"url": urls[0], "similarity": 0.9}]
        )

        result = db_utils.search_by_text_vibe([0.1] * 384, candidate_urls=urls)

        self.assertEqual(self.anon_client.rpc.call_count, 1)
        self.assertEqual(result, {urls[0]: 0.9})

    def test_candidate_set_over_the_chunk_size_is_split_into_multiple_calls(self):
        size = db_utils._RPC_CANDIDATE_CHUNK_SIZE
        urls = [f"https://listing-{i}" for i in range(size + 500)]

        responses = []

        def _rpc(name, params):
            batch = params["candidate_urls"]
            resp = MagicMock()
            resp.execute.return_value = MagicMock(
                data=[{"url": u, "similarity": 0.5} for u in batch]
            )
            responses.append(batch)
            return resp

        self.anon_client.rpc.side_effect = _rpc

        result = db_utils.search_by_text_vibe([0.1] * 384, candidate_urls=urls)

        self.assertEqual(self.anon_client.rpc.call_count, 2)
        self.assertEqual(len(responses[0]), size)
        self.assertEqual(len(responses[1]), 500)
        # Every URL across every batch was scored and merged into one dict.
        self.assertEqual(set(result.keys()), set(urls))

    def test_a_failed_batch_does_not_lose_results_from_other_batches(self):
        size = db_utils._RPC_CANDIDATE_CHUNK_SIZE
        urls = [f"https://listing-{i}" for i in range(size + 100)]

        def _rpc(name, params):
            batch = params["candidate_urls"]
            resp = MagicMock()
            if len(batch) == size:
                resp.execute.side_effect = Exception("network blip")
            else:
                resp.execute.return_value = MagicMock(
                    data=[{"url": u, "similarity": 0.5} for u in batch]
                )
            return resp

        self.anon_client.rpc.side_effect = _rpc

        result = db_utils.search_by_text_vibe([0.1] * 384, candidate_urls=urls)

        self.assertEqual(len(result), 100)


class ScopedImageSearchChunkingTests(unittest.TestCase):
    def setUp(self):
        self.anon_client = MagicMock()
        self._patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_candidate_set_over_the_chunk_size_is_split_into_multiple_calls(self):
        size = db_utils._RPC_CANDIDATE_CHUNK_SIZE
        urls = [f"https://listing-{i}" for i in range(size + 1)]

        def _rpc(name, params):
            batch = params["candidate_urls"]
            resp = MagicMock()
            resp.execute.return_value = MagicMock(
                data=[{"url": u, "similarity": 0.5} for u in batch]
            )
            return resp

        self.anon_client.rpc.side_effect = _rpc

        result = db_utils.search_by_image_embedding([0.1] * 512, candidate_urls=urls)

        self.assertEqual(self.anon_client.rpc.call_count, 2)
        self.assertEqual(set(result.keys()), set(urls))


if __name__ == "__main__":
    unittest.main()
