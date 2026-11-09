"""
Integrity of the hand-labeled OLX validation set plus the pure functions
that read it. No DB and no model calls — prepare_olx_validation_set's
fetch is exercised against a fake client, per the repo convention that
Supabase and LLM calls are always mocked in unit tests.
"""
import json
import os
import unittest
from unittest.mock import MagicMock

from benchmarks.llm.enrichment_schema import CanonicalFill, EnrichmentResult
from benchmarks.prepare_olx_validation_set import (
    DB_SNAPSHOT_COLUMNS,
    fetch_latest_olx,
    to_template_row,
)
from benchmarks.summarize_olx_validation_set import (
    DATASET_PATH,
    canonical_coverage,
    label_distribution,
    load_rows,
)


class DatasetIntegrityTests(unittest.TestCase):
    """The dataset is a checked-in artifact other work is scored against —
    a silently malformed or half-labeled row would show up as a model
    accuracy drop, not as an error, so assert its shape directly."""

    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows(DATASET_PATH)

    def test_has_two_hundred_rows(self):
        self.assertEqual(len(self.rows), 200)

    def test_every_row_is_olx_with_text_to_label_from(self):
        for row in self.rows:
            self.assertEqual(row["platform"], "OLX")
            self.assertIn("olx.ro", row["url"])
            self.assertTrue(row["description"].strip())

    def test_urls_are_unique(self):
        urls = [row["url"] for row in self.rows]
        self.assertEqual(len(set(urls)), len(urls))

    def test_every_row_is_labeled_and_validates_against_the_schemas(self):
        for row in self.rows:
            self.assertIsNotNone(row["expected"], row["url"])
            self.assertIsNotNone(row["expected_canonical"], row["url"])
            # Round-trips: model_validate raises on an out-of-enum value,
            # and re-dumping must reproduce the stored dict exactly, so a
            # stray/misspelled key can't sit unnoticed in the file.
            self.assertEqual(
                EnrichmentResult.model_validate(row["expected"]).model_dump(),
                row["expected"],
            )
            self.assertEqual(
                CanonicalFill.model_validate(row["expected_canonical"]).model_dump(),
                row["expected_canonical"],
            )

    def test_db_snapshot_carries_every_tracked_column(self):
        for row in self.rows:
            self.assertEqual(set(row["db"]), set(DB_SNAPSHOT_COLUMNS))

    def test_every_enrichment_label_is_one_of_the_schema_values(self):
        """model_validate already enforces this, but assert it directly so
        a schema loosened later doesn't silently let free text into the
        labels the models are scored against."""
        allowed = {"own_heating": {"yes", "no", "unknown"},
                   "parking_available": {"yes", "no", "unknown"},
                   "pets_allowed": {"yes", "no", "unknown"},
                   "renovation_status": {"renovated", "needs_work", "new_build", "unknown"}}
        for row in self.rows:
            for field, values in allowed.items():
                self.assertIn(row["expected"][field], values, row["url"])

    def test_rows_are_ordered_newest_first(self):
        scraped = [row["scraped_at"] for row in self.rows]
        self.assertEqual(scraped, sorted(scraped, reverse=True))

    def test_every_label_class_the_schema_allows_is_actually_represented(self):
        """A validation set that never exercises a label can't measure it."""
        distribution = label_distribution(self.rows)
        for field, expected_values in {
            "own_heating": {"yes", "no", "unknown"},
            "parking_available": {"yes", "no", "unknown"},
            "pets_allowed": {"yes", "no", "unknown"},
            "renovation_status": {"renovated", "needs_work", "new_build", "unknown"},
        }.items():
            self.assertLessEqual(expected_values, set(distribution[field]), field)


class CanonicalCoverageTests(unittest.TestCase):
    def _row(self, db, text):
        return {"db": db, "expected_canonical": text}

    def test_counts_a_blank_db_column_filled_from_text(self):
        rows = [self._row({c: None for c in DB_SNAPSHOT_COLUMNS},
                          {**{c: None for c in DB_SNAPSHOT_COLUMNS}, "rooms": "2"})]
        stats = canonical_coverage(rows)["rooms"]
        self.assertEqual((stats["db_blank"], stats["fills_blank"], stats["text_states"]), (1, 1, 1))

    def test_blank_db_column_the_text_is_also_silent_on_is_not_a_fill(self):
        rows = [self._row({c: None for c in DB_SNAPSHOT_COLUMNS},
                          {c: None for c in DB_SNAPSHOT_COLUMNS})]
        stats = canonical_coverage(rows)["rooms"]
        self.assertEqual((stats["db_blank"], stats["fills_blank"]), (1, 0))

    def test_rounded_area_is_not_reported_as_a_contradiction(self):
        """The scraper stores "63,3 mp" as 63 — the same number, written twice."""
        rows = [self._row({**{c: None for c in DB_SNAPSHOT_COLUMNS}, "area_sqm": 63},
                          {**{c: None for c in DB_SNAPSHOT_COLUMNS}, "area_sqm": 63.3})]
        self.assertEqual(canonical_coverage(rows)["area_sqm"]["contradicts"], 0)

    def test_genuinely_different_area_is_a_contradiction(self):
        rows = [self._row({**{c: None for c in DB_SNAPSHOT_COLUMNS}, "area_sqm": 98},
                          {**{c: None for c in DB_SNAPSHOT_COLUMNS}, "area_sqm": 83.0})]
        self.assertEqual(canonical_coverage(rows)["area_sqm"]["contradicts"], 1)

    def test_text_column_contradiction_ignores_case_and_whitespace(self):
        rows = [self._row({**{c: None for c in DB_SNAPSHOT_COLUMNS}, "floor": "Parter"},
                          {**{c: None for c in DB_SNAPSHOT_COLUMNS}, "floor": " parter "})]
        self.assertEqual(canonical_coverage(rows)["floor"]["contradicts"], 0)


class FetchLatestOlxTests(unittest.TestCase):
    def _client(self, data):
        client = MagicMock()
        builder = client.table.return_value
        for method in ("select", "eq", "not_", "order", "limit"):
            getattr(builder, method).return_value = builder
        builder.not_.is_.return_value = builder
        builder.execute.return_value = MagicMock(data=data)
        return client

    def test_drops_whitespace_only_descriptions_the_is_null_filter_cannot_catch(self):
        client = self._client([
            {"url": "a", "description": "   "},
            {"url": "b", "description": "real text"},
        ])
        self.assertEqual([r["url"] for r in fetch_latest_olx(client, 10)], ["b"])

    def test_truncates_the_over_fetched_pool_to_n(self):
        client = self._client([{"url": str(i), "description": "x"} for i in range(50)])
        self.assertEqual(len(fetch_latest_olx(client, 5)), 5)

    def test_returns_empty_list_when_the_query_returns_no_data(self):
        client = self._client(None)
        self.assertEqual(fetch_latest_olx(client, 5), [])


class TemplateRowTests(unittest.TestCase):
    def test_leaves_both_label_targets_unset(self):
        row = to_template_row({"url": "u", "title": "t", "description": "d"})
        self.assertIsNone(row["expected"])
        self.assertIsNone(row["expected_canonical"])

    def test_missing_optional_text_becomes_empty_string_not_none(self):
        row = to_template_row({"url": "u"})
        self.assertEqual((row["title"], row["description"]), ("", ""))

    def test_db_snapshot_records_missing_columns_as_none(self):
        row = to_template_row({"url": "u", "rooms": "2"})
        self.assertEqual(row["db"]["rooms"], "2")
        self.assertIsNone(row["db"]["total_floors"])


if __name__ == "__main__":
    unittest.main()
