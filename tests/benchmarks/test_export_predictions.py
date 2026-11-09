"""
Pivoting per-model prediction rows into one row per listing — pure
dict/CSV work, no Ollama and no DB. The pivot is what the error analysis
is read from, so mixing two models' answers into one column, or dropping a
listing whose call failed, would quietly corrupt that analysis.
"""
import csv
import io
import os
import tempfile
import unittest

from benchmarks.export_predictions import flatten, load_predictions, pivot, write_csv


_UNSET = object()  # `None` is a meaningful value here (a failed call), so it can't mean "use the default"


def _prediction(model="m1", url="u1", actual=_UNSET, scores=_UNSET, **overrides):
    row = {
        "task": "enrichment",
        "model": model,
        "url": url,
        "title": "t",
        "description": "d",
        "expected": {"heating_type": "gas", "parking": {"available": True, "type": "garage"}},
        "actual": {"heating_type": "gas", "parking": {"available": True, "type": "garage"}}
                  if actual is _UNSET else actual,
        "scores": {"heating_type": True, "parking.available": True, "parking.type": True}
                  if scores is _UNSET else scores,
    }
    row.update(overrides)
    return row


class FlattenTests(unittest.TestCase):
    def test_nested_object_becomes_dotted_keys(self):
        self.assertEqual(
            flatten({"a": 1, "parking": {"available": True, "type": None}}),
            {"a": 1, "parking.available": True, "parking.type": None},
        )

    def test_none_flattens_to_an_empty_mapping(self):
        """A failed call has `actual: null` — that must not raise."""
        self.assertEqual(flatten(None), {})


class PivotTests(unittest.TestCase):
    def test_one_row_per_listing_not_per_call(self):
        header, rows = pivot([_prediction(model="m1"), _prediction(model="m2")])
        self.assertEqual(len(rows), 1)

    def test_each_model_gets_its_own_column_per_field(self):
        _header, rows = pivot([
            _prediction(model="m1", actual={"heating_type": "gas", "parking": {}}),
            _prediction(model="m2", actual={"heating_type": "central", "parking": {}}),
        ])
        self.assertEqual(rows[0]["m1_heating_type"], "gas")
        self.assertEqual(rows[0]["m2_heating_type"], "central")
        self.assertEqual(rows[0]["expected_heating_type"], "gas")

    def test_model_and_listing_order_follow_first_appearance(self):
        header, rows = pivot([_prediction(model="zz", url="b"), _prediction(model="aa", url="a")])
        self.assertLess(header.index("zz_heating_type"), header.index("aa_heating_type"))
        self.assertEqual([r["url"] for r in rows], ["b", "a"])

    def test_correct_count_is_reported_per_model(self):
        _header, rows = pivot([_prediction(
            model="m1",
            scores={"heating_type": False, "parking.available": True, "parking.type": True},
        )])
        self.assertEqual(rows[0]["m1_correct"], "2/3")

    def test_models_agree_flag_tracks_identical_answers(self):
        same = pivot([_prediction(model="m1"), _prediction(model="m2")])[1][0]
        differing = pivot([
            _prediction(model="m1", actual={"heating_type": "gas", "parking": {}}),
            _prediction(model="m2", actual={"heating_type": "other", "parking": {}}),
        ])[1][0]
        self.assertTrue(same["models_agree"])
        self.assertFalse(differing["models_agree"])

    def test_any_wrong_flag_is_set_when_either_model_missed_a_field(self):
        _header, rows = pivot([
            _prediction(model="m1"),
            _prediction(model="m2", scores={"heating_type": False}),
        ])
        self.assertTrue(rows[0]["any_wrong"])

    def test_a_failed_call_keeps_the_listing_and_records_the_error(self):
        _header, rows = pivot([
            _prediction(model="m1"),
            _prediction(model="m2", actual=None, scores=None, error="boom"),
        ])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["m2_heating_type"])
        self.assertEqual(rows[0]["m2_correct"], "")
        self.assertIn("m2: boom", rows[0]["errors"])

    def test_description_newlines_are_collapsed(self):
        _header, rows = pivot([_prediction(description="a\n\nb")])
        self.assertEqual(rows[0]["description"], "a b")


class WriteCsvTests(unittest.TestCase):
    def test_round_trips_through_csv_with_the_declared_header(self):
        header, rows = pivot([_prediction(model="m1"), _prediction(model="m2", url="u2")])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            write_csv(header, rows, path)
            with open(path, encoding="utf-8") as f:
                text = f.read()
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([r["url"] for r in parsed], ["u1", "u2"])
        self.assertEqual(list(parsed[0]), header)


class LoadPredictionsTests(unittest.TestCase):
    def test_ignores_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"model": "m", "url": "u", "expected": {}}\n\n')
            self.assertEqual(len(load_predictions(path)), 1)


if __name__ == "__main__":
    unittest.main()
