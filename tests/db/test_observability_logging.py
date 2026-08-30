"""
Tests for the crawl_run_logs / availability_check_logs / user_searches /
user_events logging helpers in db_utils.py.

These are backend-only observability tables (see scripts/supabase_schema.sql
section 9) — every function here must use get_client() (service-role),
never get_anon_client(), and must never let a logging failure raise out of
the caller: the crawl/check itself must keep running even if Supabase is
briefly unreachable when we try to log about it.
"""
import unittest
from unittest.mock import patch, MagicMock

import db_utils


class CrawlRunLogTests(unittest.TestCase):
    def setUp(self):
        self.service_client = MagicMock()
        self.anon_client = MagicMock()
        self._service_patch = patch.object(db_utils, "get_client", return_value=self.service_client)
        self._anon_patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self.mock_service = self._service_patch.start()
        self.mock_anon = self._anon_patch.start()
        self.addCleanup(self._service_patch.stop)
        self.addCleanup(self._anon_patch.stop)

    def test_start_returns_the_new_row_id(self):
        table = self.service_client.table.return_value
        table.insert.return_value = table
        table.execute.return_value = MagicMock(data=[{"id": 42}])

        run_id = db_utils.start_crawl_run_log(mode="incremental", platforms=["olx", "storia"])

        self.assertEqual(run_id, 42)
        self.mock_service.assert_called()
        self.mock_anon.assert_not_called()
        insert_payload = table.insert.call_args.args[0]
        self.assertEqual(insert_payload["mode"], "incremental")
        self.assertEqual(insert_payload["platforms"], ["olx", "storia"])

    def test_start_returns_none_on_exception_without_raising(self):
        self.service_client.table.side_effect = Exception("network blip")

        run_id = db_utils.start_crawl_run_log(mode="full", platforms=["olx"])

        self.assertIsNone(run_id)

    def test_finish_is_a_noop_when_run_id_is_none(self):
        db_utils.finish_crawl_run_log(None, listings_new=5, status="success")

        self.service_client.table.assert_not_called()

    def test_finish_updates_the_correct_row(self):
        table = self.service_client.table.return_value
        table.update.return_value = table
        table.eq.return_value = table
        table.execute.return_value = MagicMock(data=[{"id": 42}])

        db_utils.finish_crawl_run_log(42, listings_new=17, status="success")

        table.eq.assert_called_once_with("id", 42)
        update_payload = table.update.call_args.args[0]
        self.assertEqual(update_payload["listings_new"], 17)
        self.assertEqual(update_payload["status"], "success")

    def test_finish_swallows_exceptions(self):
        self.service_client.table.side_effect = Exception("network blip")

        try:
            db_utils.finish_crawl_run_log(42, status="failed", error_message="boom")
        except Exception:
            self.fail("finish_crawl_run_log must not raise even if the update fails")


class AvailabilityCheckLogTests(unittest.TestCase):
    def setUp(self):
        self.service_client = MagicMock()
        self.anon_client = MagicMock()
        self._service_patch = patch.object(db_utils, "get_client", return_value=self.service_client)
        self._anon_patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self.mock_service = self._service_patch.start()
        self.mock_anon = self._anon_patch.start()
        self.addCleanup(self._service_patch.stop)
        self.addCleanup(self._anon_patch.stop)

    def test_start_returns_the_new_row_id(self):
        table = self.service_client.table.return_value
        table.insert.return_value = table
        table.execute.return_value = MagicMock(data=[{"id": 7}])

        run_id = db_utils.start_availability_check_log(platforms=["olx"])

        self.assertEqual(run_id, 7)
        self.mock_anon.assert_not_called()

    def test_finish_is_a_noop_when_run_id_is_none(self):
        db_utils.finish_availability_check_log(None, listings_checked=100)

        self.service_client.table.assert_not_called()

    def test_finish_updates_all_three_counters(self):
        table = self.service_client.table.return_value
        table.update.return_value = table
        table.eq.return_value = table
        table.execute.return_value = MagicMock(data=[{"id": 7}])

        db_utils.finish_availability_check_log(
            7, listings_checked=100, listings_expired=12, listings_blocked=3, status="success",
        )

        update_payload = table.update.call_args.args[0]
        self.assertEqual(update_payload["listings_checked"], 100)
        self.assertEqual(update_payload["listings_expired"], 12)
        self.assertEqual(update_payload["listings_blocked"], 3)


class UserSearchLogTests(unittest.TestCase):
    def setUp(self):
        self.service_client = MagicMock()
        self.anon_client = MagicMock()
        self._service_patch = patch.object(db_utils, "get_client", return_value=self.service_client)
        self._anon_patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self.mock_service = self._service_patch.start()
        self.mock_anon = self._anon_patch.start()
        self.addCleanup(self._service_patch.stop)
        self.addCleanup(self._anon_patch.stop)

    def test_uses_service_client_not_anon(self):
        table = self.service_client.table.return_value
        table.insert.return_value = table
        table.execute.return_value = MagicMock(data=[{"id": 1}])

        db_utils.log_user_search(
            session_id="sess-1", visitor_id="visitor-1",
            http_method="GET", http_path="/listings/search",
            form_fields={"rooms": {"value": "2", "source": "nlp"}},
            results_count=5,
        )

        self.mock_service.assert_called()
        self.mock_anon.assert_not_called()

    def test_form_fields_payload_is_forwarded_unchanged(self):
        table = self.service_client.table.return_value
        table.insert.return_value = table
        table.execute.return_value = MagicMock(data=[{"id": 1}])
        fields = {
            "rooms": {"value": "2", "source": "nlp"},
            "max_price": {"value": None, "source": "unset"},
            "districts": {"value": ["Floreasca"], "source": "user"},
        }

        db_utils.log_user_search(
            session_id="sess-1", visitor_id="visitor-1",
            http_method="GET", http_path="/listings/search",
            form_fields=fields, results_count=5,
        )

        insert_payload = table.insert.call_args.args[0]
        self.assertEqual(insert_payload["form_fields"], fields)

    def test_returns_false_on_exception_without_raising(self):
        self.service_client.table.side_effect = Exception("network blip")

        result = db_utils.log_user_search(
            session_id="sess-1", visitor_id="visitor-1",
            http_method="GET", http_path="/listings/search",
            form_fields={}, results_count=0,
        )

        self.assertFalse(result)


class UserEventLogTests(unittest.TestCase):
    def setUp(self):
        self.service_client = MagicMock()
        self.anon_client = MagicMock()
        self._service_patch = patch.object(db_utils, "get_client", return_value=self.service_client)
        self._anon_patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self.mock_service = self._service_patch.start()
        self.mock_anon = self._anon_patch.start()
        self.addCleanup(self._service_patch.stop)
        self.addCleanup(self._anon_patch.stop)

    def test_uses_service_client_not_anon(self):
        table = self.service_client.table.return_value
        table.insert.return_value = table
        table.execute.return_value = MagicMock(data=[{"id": 1}])

        db_utils.log_user_event(event_type="page_view", visitor_id="visitor-1")

        self.mock_service.assert_called()
        self.mock_anon.assert_not_called()

    def test_insert_payload_carries_all_fields(self):
        table = self.service_client.table.return_value
        table.insert.return_value = table
        table.execute.return_value = MagicMock(data=[{"id": 1}])

        db_utils.log_user_event(
            event_type="listing_click",
            visitor_id="visitor-1",
            session_id="sess-1",
            path="/",
            metadata={"listing_url": "https://example.com/a"},
        )

        insert_payload = table.insert.call_args.args[0]
        self.assertEqual(insert_payload["event_type"], "listing_click")
        self.assertEqual(insert_payload["visitor_id"], "visitor-1")
        self.assertEqual(insert_payload["session_id"], "sess-1")
        self.assertEqual(insert_payload["path"], "/")
        self.assertEqual(insert_payload["metadata"], {"listing_url": "https://example.com/a"})

    def test_optional_fields_default_to_none(self):
        table = self.service_client.table.return_value
        table.insert.return_value = table
        table.execute.return_value = MagicMock(data=[{"id": 1}])

        db_utils.log_user_event(event_type="page_view", visitor_id="visitor-1")

        insert_payload = table.insert.call_args.args[0]
        self.assertIsNone(insert_payload["session_id"])
        self.assertIsNone(insert_payload["path"])
        self.assertIsNone(insert_payload["metadata"])

    def test_returns_true_on_success(self):
        table = self.service_client.table.return_value
        table.insert.return_value = table
        table.execute.return_value = MagicMock(data=[{"id": 1}])

        result = db_utils.log_user_event(event_type="page_view", visitor_id="visitor-1")

        self.assertTrue(result)

    def test_returns_false_on_exception_without_raising(self):
        self.service_client.table.side_effect = Exception("network blip")

        result = db_utils.log_user_event(event_type="page_view", visitor_id="visitor-1")

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
