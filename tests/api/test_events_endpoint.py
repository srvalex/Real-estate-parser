"""
Tests for POST /events (api/main.py) — minimal alpha traffic tracking.

Mocks db_utils.log_user_event throughout — never hits real Supabase,
matching every other test under tests/api/.
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


class EventValidationTests(unittest.TestCase):
    def test_unknown_event_type_is_rejected(self):
        resp = client.post("/events", json={"event_type": "not_a_real_type", "visitor_id": "v1"})
        self.assertEqual(resp.status_code, 422)

    def test_missing_visitor_id_is_rejected(self):
        resp = client.post("/events", json={"event_type": "page_view"})
        self.assertEqual(resp.status_code, 422)

    def test_missing_event_type_is_rejected(self):
        resp = client.post("/events", json={"visitor_id": "v1"})
        self.assertEqual(resp.status_code, 422)


class EventLoggingTests(unittest.TestCase):
    def test_minimal_page_view_is_forwarded_to_log_user_event(self):
        with patch("api.main.db_utils.log_user_event", return_value=True) as mock_log:
            resp = client.post("/events", json={"event_type": "page_view", "visitor_id": "v1"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"logged": True})
        mock_log.assert_called_once_with(
            event_type="page_view", visitor_id="v1", session_id=None, path=None, metadata=None,
        )

    def test_full_listing_click_payload_is_forwarded(self):
        payload = {
            "event_type": "listing_click",
            "visitor_id": "v1",
            "session_id": "s1",
            "path": "/",
            "metadata": {"listing_url": "https://example.com/a"},
        }
        with patch("api.main.db_utils.log_user_event", return_value=True) as mock_log:
            resp = client.post("/events", json=payload)

        self.assertEqual(resp.status_code, 200)
        mock_log.assert_called_once_with(
            event_type="listing_click",
            visitor_id="v1",
            session_id="s1",
            path="/",
            metadata={"listing_url": "https://example.com/a"},
        )

    def test_logging_failure_still_returns_200_with_logged_false(self):
        """A dropped event must never surface as a request failure to the
        frontend — same fail-safe contract as log_user_event itself."""
        with patch("api.main.db_utils.log_user_event", return_value=False):
            resp = client.post("/events", json={"event_type": "page_view", "visitor_id": "v1"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"logged": False})


if __name__ == "__main__":
    unittest.main()
