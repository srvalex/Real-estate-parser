"""
Regression tests for extractor._save_new_listings' handling of dict-valued
fields (extras, image_urls) on the SQLite write path.

Bug: sqlite3's DB-API cannot bind a Python dict as a parameter at all
("Error binding parameter N: type 'dict' is not supported"). pandas.to_sql()
catches that and re-raises it as the generic pandas.errors.DatabaseError
("Execution failed"), discarding the original message. _save_new_listings
already stringified `image_urls` before the SQLite insert, but not `extras`
— so every Storia/Imobiliare listing with a non-empty `extras` dict failed
this exact way on both the batch AND row-by-row SQLite insert, printing a
scary-looking "Execution failed" that had nothing to do with Supabase (the
Supabase upsert path handles dicts fine via its JSONB columns and always
succeeded regardless). Confirmed live against a real Storia listing before
this fix.

Fix: extras gets the same stringify-for-SQLite / restore-native-for-Supabase
treatment image_urls already had.
"""
import sqlite3
import unittest
from unittest.mock import patch

import extractor


def _fresh_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(f"CREATE TABLE listings ({extractor.DB_COLS})")
    return conn


class SaveNewListingsJsonSerializationTests(unittest.TestCase):
    def test_extras_dict_no_longer_breaks_the_sqlite_insert(self):
        item = {
            "url": "https://www.storia.ro/ro/oferta/test-1",
            "platform_id": "storia",
            "title": "Test listing",
            "is_available": 1,
            "image_urls": [{"thumbnail": "https://img/1.jpg"}],
            "extras": {"id": 123, "nested": {"a": 1}},
        }
        conn = _fresh_conn()

        with patch.object(extractor, "_get_embed_model", return_value=None), \
             patch.object(extractor, "save_to_firestore") as mock_save:
            df = extractor._save_new_listings([dict(item)], conn)

        self.assertEqual(len(df), 1)
        row = conn.execute(
            "SELECT url FROM listings WHERE url = ?", (item["url"],)
        ).fetchone()
        self.assertIsNotNone(row, "row must actually be present in SQLite, not silently dropped")

        mock_save.assert_called_once()
        saved_records = mock_save.call_args.args[0]
        self.assertEqual(saved_records[0]["extras"], {"id": 123, "nested": {"a": 1}})
        self.assertEqual(saved_records[0]["image_urls"], [{"thumbnail": "https://img/1.jpg"}])

    def test_item_without_extras_or_image_urls_is_unaffected(self):
        item = {
            "url": "https://www.olx.ro/d/oferta/test-2.html",
            "platform_id": "olx",
            "title": "Plain listing",
            "is_available": 1,
        }
        conn = _fresh_conn()

        with patch.object(extractor, "_get_embed_model", return_value=None), \
             patch.object(extractor, "save_to_firestore"):
            df = extractor._save_new_listings([dict(item)], conn)

        self.assertEqual(len(df), 1)
        row = conn.execute(
            "SELECT url FROM listings WHERE url = ?", (item["url"],)
        ).fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
