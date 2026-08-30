"""
Tests for api/template_photos.py — the relocation of
streamlit_interface/components/home.py's template-photo picker logic
(cache-then-CLIP lookup, multi-select averaging).

Mocks image_embedding.embed_image and points _TEMPLATE_DIR/_CACHE_PATH at a
temp fixture — never downloads/runs the real CLIP model or touches the real
streamlit_interface/template_photos/ assets in this suite. embed_image is
mocked in every test (not just the ones asserting on it directly): _embeddings()
unconditionally warms up all four template ids on first access, regardless
of which one a given test actually asks for, so any real CLIP call anywhere
in this file would import torch for real mid-suite — confirmed live
2026-08-30 that this segfaults (torch's bundled OpenMP runtime clashes with
pyarrow's, already loaded earlier in the same pytest process by tests/db/'s
pandas usage).
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import api.template_photos as template_photos


def _unit_vector(seed: int, dim: int = 512) -> list:
    rng = np.random.RandomState(seed)
    v = rng.rand(dim)
    return (v / np.linalg.norm(v)).tolist()


class TemplatePhotosTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(template_photos._embeddings.cache_clear)
        template_photos._embeddings.cache_clear()

        self.vecs = {f"template_{i}": _unit_vector(i) for i in range(1, 5)}
        self.filenames = {
            "template_1": "template_1.png",
            "template_2": "template_2.jpg",
            "template_3": "template_3.jpg",
            "template_4": "template_4.jpg",
        }
        self._write_cache({pid: self.vecs[pid] for pid in self.vecs})  # all four cached by default
        for fname in self.filenames.values():
            open(os.path.join(self.tmpdir.name, fname), "w").close()

        self._dir_patch = patch.object(template_photos, "_TEMPLATE_DIR", self.tmpdir.name)
        self._cache_patch = patch.object(
            template_photos, "_CACHE_PATH", os.path.join(self.tmpdir.name, "embeddings.json")
        )
        self._dir_patch.start()
        self._cache_patch.start()
        self.addCleanup(self._dir_patch.stop)
        self.addCleanup(self._cache_patch.stop)

        # Safety net so a bug in a test's own setup can never trigger a real
        # CLIP/torch call — see module docstring.
        self._embed_patch = patch.object(template_photos, "embed_image", return_value=_unit_vector(999))
        self.mock_embed_default = self._embed_patch.start()
        self.addCleanup(self._embed_patch.stop)

    def _write_cache(self, by_photo_id: dict):
        cache = {self.filenames[pid]: vec for pid, vec in by_photo_id.items()}
        with open(os.path.join(self.tmpdir.name, "embeddings.json"), "w") as f:
            json.dump(cache, f)

    def test_list_template_photos_returns_all_four_with_known_labels(self):
        result = template_photos.list_template_photos()
        self.assertEqual(
            result,
            [
                {"id": "template_1", "label": "Mobilat modern"},
                {"id": "template_2", "label": "Clasic, luxos"},
                {"id": "template_3", "label": "Primitor"},
                {"id": "template_4", "label": "Bloc comunist"},
            ],
        )

    def test_all_cached_never_calls_clip(self):
        emb = template_photos.get_combined_embedding(["template_1"])
        self.mock_embed_default.assert_not_called()
        self.assertEqual(emb, self.vecs["template_1"])

    def test_uncached_photo_falls_back_to_clip_for_just_that_one(self):
        # Remove template_3 from the cache; 1/2/4 stay cached.
        self._write_cache({pid: v for pid, v in self.vecs.items() if pid != "template_3"})
        template_photos._embeddings.cache_clear()

        fresh_vec = _unit_vector(99)
        self.mock_embed_default.return_value = fresh_vec
        emb = template_photos.get_combined_embedding(["template_3"])

        self.mock_embed_default.assert_called_once()
        called_path = self.mock_embed_default.call_args.args[0]
        self.assertTrue(called_path.endswith("template_3.jpg"))
        self.assertEqual(emb, fresh_vec)

    def test_single_selection_returns_its_own_embedding_unmodified(self):
        emb = template_photos.get_combined_embedding(["template_2"])
        self.assertEqual(emb, self.vecs["template_2"])

    def test_multiple_selections_are_averaged_and_renormalised(self):
        emb = template_photos.get_combined_embedding(["template_1", "template_2"])
        arr = np.array(emb)
        self.assertAlmostEqual(np.linalg.norm(arr), 1.0, places=5)
        expected_direction = np.array(self.vecs["template_1"]) + np.array(self.vecs["template_2"])
        expected_direction /= np.linalg.norm(expected_direction)
        np.testing.assert_allclose(arr, expected_direction, atol=1e-6)

    def test_unknown_id_is_ignored(self):
        self.assertIsNone(template_photos.get_combined_embedding(["nonexistent"]))

    def test_empty_selection_returns_none(self):
        self.assertIsNone(template_photos.get_combined_embedding([]))


if __name__ == "__main__":
    unittest.main()
