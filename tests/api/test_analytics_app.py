"""
Tests for api/analytics_app.py — the internal, token-guarded analytics
service.

db_utils.fetch_analytics_data is mocked throughout, so nothing here touches
Supabase; the point of these tests is the boundary (auth, isolation from the
public API, aggregate-only responses) and the cache, not the arithmetic —
that lives in test_analytics.py.
"""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import analytics_app

client = TestClient(analytics_app.app)

TOKEN = "test-analytics-token"
AUTH = {"X-Analytics-Token": TOKEN}

_ROWS = [
    {
        "platform_id": "olx",
        "city": "Bucuresti",
        "district": "Aviatiei",
        "price_numeric": 500 + i * 10,
        "price_currency": "EUR",
        "rooms": "2 camere",
        "area_sqm": 55,
        "property_type": "Apartament",
        "first_seen_at": "2026-08-01T10:00:00+00:00",
        "scraped_at": "2026-08-02T10:00:00+00:00",
    }
    for i in range(5)
]


def _with_token():
    return patch.dict(os.environ, {"ANALYTICS_API_TOKEN": TOKEN})


class AuthTests(unittest.TestCase):
    def setUp(self):
        analytics_app._summary_cache.clear()

    def test_missing_token_is_rejected(self):
        with _with_token():
            resp = client.get("/analytics/summary")
        self.assertEqual(resp.status_code, 401)

    def test_wrong_token_is_rejected(self):
        with _with_token():
            resp = client.get("/analytics/summary", headers={"X-Analytics-Token": "nope"})
        self.assertEqual(resp.status_code, 401)

    def test_unconfigured_token_fails_closed_rather_than_serving_data(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANALYTICS_API_TOKEN", None)
            resp = client.get("/analytics/summary", headers={"X-Analytics-Token": "anything"})
        self.assertEqual(resp.status_code, 503)
        self.assertIn("ANALYTICS_API_TOKEN", resp.json()["detail"])

    def test_cities_endpoint_is_also_guarded(self):
        with _with_token():
            self.assertEqual(client.get("/analytics/cities").status_code, 401)

    def test_health_needs_no_token(self):
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")


class SummaryTests(unittest.TestCase):
    def setUp(self):
        analytics_app._summary_cache.clear()

    def test_summary_returns_aggregates_for_the_whole_dataset(self):
        with _with_token(), patch.object(analytics_app.db_utils, "fetch_analytics_data", return_value=_ROWS) as fetch:
            resp = client.get("/analytics/summary", headers=AUTH)

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        fetch.assert_called_once_with(city=None)
        self.assertEqual(body["kpis"]["total"], 5)
        self.assertEqual(body["kpis"]["with_price"], 5)
        self.assertEqual(body["by_sector"][0]["sector"], "Sector 1")
        self.assertIsNone(body["city"])
        self.assertTrue(body["generated_at"])

    def test_response_contains_no_listing_level_fields(self):
        with _with_token(), patch.object(analytics_app.db_utils, "fetch_analytics_data", return_value=_ROWS):
            body = client.get("/analytics/summary", headers=AUTH).text
        for leaked in ("url", "title", "description", "image_urls", "location_full"):
            self.assertNotIn(leaked, body)

    def test_city_param_is_pushed_down_to_the_query(self):
        with _with_token(), patch.object(analytics_app.db_utils, "fetch_analytics_data", return_value=_ROWS) as fetch:
            resp = client.get("/analytics/summary?city=Cluj-Napoca", headers=AUTH)

        self.assertEqual(resp.status_code, 200)
        fetch.assert_called_once_with(city="Cluj-Napoca")
        self.assertEqual(resp.json()["city"], "Cluj-Napoca")

    def test_unknown_city_is_rejected_before_hitting_the_db(self):
        with _with_token(), patch.object(analytics_app.db_utils, "fetch_analytics_data") as fetch:
            resp = client.get("/analytics/summary?city=Atlantis", headers=AUTH)

        self.assertEqual(resp.status_code, 422)
        fetch.assert_not_called()

    def test_cities_endpoint_lists_known_cities(self):
        with _with_token():
            resp = client.get("/analytics/cities", headers=AUTH)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Bucuresti", resp.json()["cities"])


class CacheTests(unittest.TestCase):
    def setUp(self):
        analytics_app._summary_cache.clear()

    def test_second_request_is_served_from_cache(self):
        with _with_token(), patch.object(analytics_app.db_utils, "fetch_analytics_data", return_value=_ROWS) as fetch:
            client.get("/analytics/summary", headers=AUTH)
            client.get("/analytics/summary", headers=AUTH)
        self.assertEqual(fetch.call_count, 1)

    def test_refresh_bypasses_the_cache(self):
        with _with_token(), patch.object(analytics_app.db_utils, "fetch_analytics_data", return_value=_ROWS) as fetch:
            client.get("/analytics/summary", headers=AUTH)
            client.get("/analytics/summary?refresh=true", headers=AUTH)
        self.assertEqual(fetch.call_count, 2)

    def test_each_city_is_cached_separately(self):
        with _with_token(), patch.object(analytics_app.db_utils, "fetch_analytics_data", return_value=_ROWS) as fetch:
            client.get("/analytics/summary", headers=AUTH)
            client.get("/analytics/summary?city=Bucuresti", headers=AUTH)
        self.assertEqual(fetch.call_count, 2)


class IsolationFromPublicApiTests(unittest.TestCase):
    """The separation is the feature — assert it, so a future refactor that
    merges the two apps fails a test instead of silently exposing the
    market data."""

    def test_public_api_exposes_no_analytics_route(self):
        from api.main import app as public_app

        paths = {route.path for route in public_app.routes}
        self.assertFalse([p for p in paths if p.startswith("/analytics")])

    def test_analytics_api_exposes_no_listing_route(self):
        paths = {route.path for route in analytics_app.app.routes}
        self.assertFalse([p for p in paths if p.startswith("/listings")])

    def test_analytics_cors_defaults_exclude_the_public_frontend_ports(self):
        for public_origin in ("http://localhost:3000", "http://localhost:3001", "http://localhost:3002"):
            self.assertNotIn(public_origin, analytics_app._allowed_origins)



class RoomFilterEndpointTests(unittest.TestCase):
    def setUp(self):
        analytics_app._summary_cache.clear()

    def _mixed_rows(self):
        return [dict(_ROWS[0], rooms=r) for r in ("1", "2 camere", "2", "3", "7")]

    def test_rooms_param_narrows_the_summary(self):
        with _with_token(), patch.object(
            analytics_app.db_utils, "fetch_analytics_data", return_value=self._mixed_rows()
        ):
            resp = client.get("/analytics/summary?rooms=2", headers=AUTH)

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["kpis"]["total"], 2)  # "2 camere" and "2"
        self.assertEqual(body["rooms"], ["2"])

    def test_multiple_room_counts_are_accepted(self):
        with _with_token(), patch.object(
            analytics_app.db_utils, "fetch_analytics_data", return_value=self._mixed_rows()
        ):
            body = client.get("/analytics/summary?rooms=1,3", headers=AUTH).json()
        self.assertEqual(body["kpis"]["total"], 2)
        self.assertEqual(body["rooms"], ["1", "3"])

    def test_five_plus_collects_every_larger_flat(self):
        with _with_token(), patch.object(
            analytics_app.db_utils, "fetch_analytics_data", return_value=self._mixed_rows()
        ):
            body = client.get("/analytics/summary?rooms=5%2B", headers=AUTH).json()
        self.assertEqual(body["kpis"]["total"], 1)  # the 7-room row

    def test_unknown_room_count_is_rejected(self):
        with _with_token(), patch.object(analytics_app.db_utils, "fetch_analytics_data") as fetch:
            resp = client.get("/analytics/summary?rooms=12", headers=AUTH)
        self.assertEqual(resp.status_code, 422)
        fetch.assert_not_called()

    def test_omitted_rooms_param_returns_everything(self):
        with _with_token(), patch.object(
            analytics_app.db_utils, "fetch_analytics_data", return_value=self._mixed_rows()
        ):
            body = client.get("/analytics/summary", headers=AUTH).json()
        self.assertEqual(body["kpis"]["total"], 5)
        self.assertEqual(body["rooms"], [])

    def test_rooms_native_charts_are_empty_only_while_filtering(self):
        with _with_token(), patch.object(
            analytics_app.db_utils, "fetch_analytics_data", return_value=self._mixed_rows()
        ):
            filtered = client.get("/analytics/summary?rooms=2", headers=AUTH).json()
            plain = client.get("/analytics/summary", headers=AUTH).json()
        self.assertEqual(filtered["by_rooms"], [])
        self.assertEqual(filtered["rooms_distribution"], [])
        self.assertTrue(plain["by_rooms"])
        self.assertTrue(plain["rooms_distribution"])

    def test_a_room_filter_does_not_poison_the_unfiltered_cache_entry(self):
        """Regression guard: a cache keyed on city alone would hand the
        2-room summary back to the next caller asking for the whole city."""
        with _with_token(), patch.object(
            analytics_app.db_utils, "fetch_analytics_data", return_value=self._mixed_rows()
        ):
            filtered = client.get("/analytics/summary?rooms=2", headers=AUTH).json()
            plain = client.get("/analytics/summary", headers=AUTH).json()
        self.assertEqual(filtered["kpis"]["total"], 2)
        self.assertEqual(plain["kpis"]["total"], 5)

    def test_same_filter_twice_is_served_from_cache(self):
        with _with_token(), patch.object(
            analytics_app.db_utils, "fetch_analytics_data", return_value=self._mixed_rows()
        ) as fetch:
            client.get("/analytics/summary?rooms=2", headers=AUTH)
            client.get("/analytics/summary?rooms=2", headers=AUTH)
        self.assertEqual(fetch.call_count, 1)

if __name__ == "__main__":
    unittest.main()
