import unittest
from unittest.mock import Mock, patch

import db_utils


class AvailabilityLimitTests(unittest.TestCase):
    def test_get_listings_for_availability_check_respects_limit(self):
        fake_resp = Mock()
        fake_resp.data = [
            {"url": "https://a", "platform_id": "storia"},
            {"url": "https://b", "platform_id": "storia"},
            {"url": "https://c", "platform_id": "storia"},
        ]

        table = Mock()
        table.select.return_value = table
        table.or_.return_value = table
        table.eq.return_value = table
        table.range.return_value = table
        table.execute.return_value = fake_resp

        client = Mock()
        client.table.return_value = table

        with patch("db_utils.get_client", return_value=client):
            rows = db_utils.get_listings_for_availability_check(limit=2)

        self.assertEqual(len(rows), 2)
        self.assertEqual([r["url"] for r in rows], ["https://a", "https://b"])


if __name__ == "__main__":
    unittest.main()
