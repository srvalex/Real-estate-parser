import unittest

from rrf import rrf_fuse


class RrfFuseTests(unittest.TestCase):
    def test_text_only_ranks_by_text_score_descending(self):
        text_scores = {"a": 0.9, "b": 0.5, "c": 0.1}
        result = rrf_fuse(text_scores, {}, urls=["a", "b", "c"])
        self.assertEqual(sorted(result, key=result.get, reverse=True), ["a", "b", "c"])

    def test_image_only_ranks_by_image_score_descending(self):
        image_scores = {"a": 0.2, "b": 0.9}
        result = rrf_fuse({}, image_scores, urls=["a", "b"])
        self.assertGreater(result["b"], result["a"])

    def test_url_absent_from_both_lists_is_excluded(self):
        result = rrf_fuse({"a": 0.9}, {"b": 0.9}, urls=["a", "b", "c"])
        self.assertNotIn("c", result)
        self.assertIn("a", result)
        self.assertIn("b", result)

    def test_url_present_in_both_lists_outranks_single_list_membership(self):
        # "a" is #1 in both lists; "b" is #1 in text only. Combined score for
        # "a" must exceed "b" even though "b" is top-ranked in its one list.
        text_scores = {"a": 0.9, "c": 0.4, "b": 0.95}
        image_scores = {"a": 0.9, "d": 0.1}
        result = rrf_fuse(text_scores, image_scores, urls=["a", "b", "c", "d"])
        self.assertGreater(result["a"], result["b"])

    def test_weights_control_relative_contribution(self):
        # Rank-1 in text vs rank-1 in image, weights swapped from default —
        # whichever channel has the higher weight should win.
        text_scores = {"a": 1.0}
        image_scores = {"b": 1.0}
        heavy_image = rrf_fuse(text_scores, image_scores, urls=["a", "b"], w_text=0.1, w_image=0.9)
        self.assertGreater(heavy_image["b"], heavy_image["a"])

        heavy_text = rrf_fuse(text_scores, image_scores, urls=["a", "b"], w_text=0.9, w_image=0.1)
        self.assertGreater(heavy_text["a"], heavy_text["b"])

    def test_empty_score_dicts_yield_empty_result(self):
        self.assertEqual(rrf_fuse({}, {}, urls=["a", "b"]), {})

    def test_raw_scores_ignored_only_rank_order_matters(self):
        # Two very different raw-score distributions that share the same rank
        # order must fuse to the same relative outcome — RRF is purely ordinal.
        urls = ["a", "b", "c"]
        low_spread = {"a": 0.51, "b": 0.50, "c": 0.49}
        high_spread = {"a": 0.99, "b": 0.10, "c": 0.01}
        r1 = rrf_fuse(low_spread, {}, urls)
        r2 = rrf_fuse(high_spread, {}, urls)
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
