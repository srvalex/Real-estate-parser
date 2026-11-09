"""
CSV export is pure file I/O over an already-labeled dataset — no DB, no
model calls. The round-trip test reads the real checked-in dataset back
out of the CSV, since a silently mangled export is the failure mode that
matters here (someone reviews the CSV and trusts what it says).
"""
import csv
import io
import os
import tempfile
import unittest

from benchmarks.export_olx_validation_set import FIELDNAMES, to_csv_row, write_csv
from benchmarks.summarize_olx_validation_set import DATASET_PATH, load_rows


def _row(**overrides):
    base = {
        "url": "https://olx.ro/x",
        "scraped_at": "2026-09-05T00:00:00+00:00",
        "title": "t",
        "description": "d",
        "db": {"rooms": "2", "area_sqm": 50, "floor": "3",
               "total_floors": None, "year_built": "Dupa 2000"},
        "expected": {
            "own_heating": "yes",
            "parking_available": "yes",
            "pets_allowed": "no",
            "renovation_status": "renovated",
        },
        "expected_canonical": {"rooms": "2", "area_sqm": 50.0, "floor": "3",
                               "total_floors": "8", "year_built": None},
    }
    base.update(overrides)
    return base


class ToCsvRowTests(unittest.TestCase):
    def test_emits_exactly_the_declared_columns(self):
        self.assertEqual(list(to_csv_row(_row())), FIELDNAMES)

    def test_exports_every_enrichment_label_as_its_own_column(self):
        out = to_csv_row(_row())
        self.assertEqual(out["label_parking_available"], "yes")
        self.assertEqual(out["label_own_heating"], "yes")

    def test_keeps_db_and_text_values_in_separate_columns(self):
        """The whole point of the CSV — what the scraper has vs. what the
        text says — must not collapse into one column."""
        out = to_csv_row(_row())
        self.assertIsNone(out["db_total_floors"])
        self.assertEqual(out["text_total_floors"], "8")

    def test_collapses_description_newlines_to_single_spaces(self):
        out = to_csv_row(_row(description="line one\n\nline  two\n"))
        self.assertEqual(out["description"], "line one line two")

    def test_unlabeled_row_exports_with_empty_label_columns(self):
        out = to_csv_row(_row(expected=None, expected_canonical=None))
        self.assertIsNone(out["label_own_heating"])
        self.assertIsNone(out["label_parking_available"])
        self.assertIsNone(out["text_rooms"])

    def test_missing_title_and_description_do_not_raise(self):
        out = to_csv_row({"url": "u", "db": {}})
        self.assertEqual((out["title"], out["description"]), ("", ""))


class WriteCsvTests(unittest.TestCase):
    def test_writes_a_header_plus_one_line_per_row(self):
        buffer = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            write_csv([_row(), _row(url="https://olx.ro/y")], path)
            with open(path, encoding="utf-8") as f:
                buffer.write(f.read())
        parsed = list(csv.DictReader(io.StringIO(buffer.getvalue())))
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["label_own_heating"], "yes")

    def test_real_dataset_round_trips_row_for_row(self):
        rows = load_rows(DATASET_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            write_csv(rows, path)
            with open(path, encoding="utf-8") as f:
                parsed = list(csv.DictReader(f))
        self.assertEqual(len(parsed), len(rows))
        for source, exported in zip(rows, parsed):
            self.assertEqual(exported["url"], source["url"])
            self.assertEqual(exported["label_pets_allowed"], source["expected"]["pets_allowed"])


if __name__ == "__main__":
    unittest.main()
