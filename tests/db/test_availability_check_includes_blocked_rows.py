"""
Bug 4b (BUGS.md): get_listings_for_availability_check never re-checked
is_available = -1 rows. The .or_() filter only asked for 1 (still live,
re-confirm) and NULL (never checked), skipping -1 (blocked/transient on a
prior scrape attempt) entirely -- a listing that hit a blocked scrape got
stuck in limbo forever, never retried by any later availability-check run.

Fix: the filter now also includes is_available.eq.-1.
"""
import unittest
from unittest.mock import Mock, patch

import db_utils


class AvailabilityCheckIncludesBlockedRowsTests(unittest.TestCase):
    def test_or_filter_includes_confirmed_live_never_checked_and_blocked(self):
        fake_resp = Mock()
        fake_resp.data = []

        table = Mock()
        table.select.return_value = table
        table.or_.return_value = table
        table.eq.return_value = table
        table.range.return_value = table
        table.execute.return_value = fake_resp

        client = Mock()
        client.table.return_value = table

        with patch("db_utils.get_client", return_value=client):
            db_utils.get_listings_for_availability_check()

        filter_arg = table.or_.call_args.args[0]
        clauses = set(filter_arg.split(","))
        self.assertEqual(
            clauses,
            {"is_available.eq.1", "is_available.eq.-1", "is_available.is.null"},
        )


if __name__ == "__main__":
    unittest.main()
