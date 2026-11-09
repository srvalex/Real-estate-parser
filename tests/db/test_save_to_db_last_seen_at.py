"""
Tests for save_to_db() stamping last_seen_at on confirmed-live records.

Found while investigating BUGS.md-style report: a query for non-Bucureşti
listings where date(first_seen_at) != date(last_seen_at) returned 0 rows,
suggesting the availability recheck never touched new cities. Turned out to
be broader: last_seen_at is written in exactly one place in the whole
codebase (batch_update_availability's is_available == 1 branch), but every
platform's "still alive" recheck result (a full parsed record, not a bare
flag) is routed through save_to_db() instead -- which upserts via
_clean_record(), and _clean_record() never sets last_seen_at. Supabase's
upsert only touches columns present in the payload, so the column stayed
frozen at its insert-time default forever, for every city -- Bucureşti just
had enough legacy rows predating this code path to mask it.

Fixed by stamping last_seen_at in save_to_db() itself (not _clean_record()):
demo/clean_listing.py previews _clean_record()'s output directly and
tests/db/test_clean_record.py asserts on it verbatim, so a wall-clock
timestamp has no business leaking into that pure mapping step.
"""
import unittest
from unittest.mock import patch, MagicMock

import db_utils


class SaveToDbLastSeenAtTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.table = self.client.table.return_value
        self.table.upsert.return_value = self.table
        self.table.execute.return_value = MagicMock()
        self._patch = patch.object(db_utils, "get_client", return_value=self.client)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _upserted_batch(self):
        """Return the list of dicts passed to the (single, batch) upsert call."""
        self.table.upsert.assert_called_once()
        args, kwargs = self.table.upsert.call_args
        self.assertEqual(kwargs.get("on_conflict"), "url")
        return args[0]

    def test_confirmed_live_record_gets_last_seen_at_stamped(self):
        db_utils.save_to_db([{"url": "https://x", "is_available": 1}])

        batch = self._upserted_batch()
        self.assertEqual(len(batch), 1)
        self.assertIn("last_seen_at", batch[0])
        self.assertRegex(batch[0]["last_seen_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_expired_record_is_not_stamped(self):
        db_utils.save_to_db([{"url": "https://x", "is_available": 0}])

        batch = self._upserted_batch()
        self.assertNotIn("last_seen_at", batch[0])

    def test_record_with_no_is_available_is_not_stamped(self):
        db_utils.save_to_db([{"url": "https://x", "title": "Apartment"}])

        batch = self._upserted_batch()
        self.assertNotIn("last_seen_at", batch[0])

    def test_mixed_batch_only_stamps_the_live_rows(self):
        db_utils.save_to_db([
            {"url": "https://live", "is_available": 1},
            {"url": "https://expired", "is_available": 0},
        ])

        batch = self._upserted_batch()
        by_url = {row["url"]: row for row in batch}
        self.assertIn("last_seen_at", by_url["https://live"])
        self.assertNotIn("last_seen_at", by_url["https://expired"])

    def test_does_not_mutate_clean_record_output_for_unrelated_fields(self):
        db_utils.save_to_db([{
            "url": "https://x", "is_available": 1, "title": "Nice flat",
        }])

        batch = self._upserted_batch()
        self.assertEqual(batch[0]["title"], "Nice flat")
        self.assertEqual(batch[0]["is_available"], 1)


if __name__ == "__main__":
    unittest.main()
