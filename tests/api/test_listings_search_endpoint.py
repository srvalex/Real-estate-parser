"""
Tests for GET /listings/search (api/main.py), MIGRATION_PLAN.md Phase 1
(hard filters) + Phase 3 (vibe ranking), combined.

Mocks the DB/embedding layers throughout (db_utils.query_listings_by_district,
db_utils.get_price_stats, db_utils.search_by_text_vibe, api.main.embed_query,
db_utils.log_user_search) — never hits real Supabase or loads the real
SentenceTransformer model, matching every existing test under tests/db/,
tests/ranking/.
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

_SAMPLE_ROWS = [
    {
        "url": "https://example.com/a",
        "title": "Apartament A",
        "description": "Aproape de metrou, renovat recent.",
        "price_eur": "500",
        "price_numeric": 500.0,
        "price_currency": "EUR",
        "district": "Dristor",
        "location_full": "Dristor, Sector 3",
        "rooms": "2",
        "area_sqm": 55.0,
        "property_type": "Apartament",
        "platform": "OLX",
        "image_urls": [{"medium": "https://img/a.jpg"}],
        "features": ["metro", "renovated"],
        "scraped_at": "2026-08-20T10:00:00Z",
        "first_seen_at": "2026-08-01T10:00:00Z",
    },
    {
        "url": "https://example.com/b",
        "title": "Apartament B",
        "description": "Studio mic, ieftin.",
        "price_eur": "900",
        "price_numeric": 900.0,
        "price_currency": "EUR",
        "district": "Obor",
        "location_full": "Obor, Sector 2",
        "rooms": "1",
        "area_sqm": 30.0,
        "property_type": "Studio",
        "platform": "Storia",
        "image_urls": [],
        "features": [],
        "scraped_at": "2026-08-22T10:00:00Z",
        "first_seen_at": "2026-08-15T10:00:00Z",
    },
]


def _patch_db(rows=None, price_stats=None):
    return (
        patch("api.main.db_utils.query_listings_by_district", return_value=rows if rows is not None else _SAMPLE_ROWS),
        patch("api.main.db_utils.get_price_stats", return_value=price_stats or {}),
        patch("api.main.db_utils.log_user_search", return_value=True),
    )


class RequiredParamTests(unittest.TestCase):
    def test_missing_districts_is_rejected(self):
        resp = client.get("/listings/search")
        self.assertEqual(resp.status_code, 422)

    def test_empty_districts_is_rejected(self):
        resp = client.get("/listings/search", params={"districts": "  , "})
        self.assertEqual(resp.status_code, 422)


class HardFilterTests(unittest.TestCase):
    def test_no_optional_filters_returns_every_row(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params={"districts": "Dristor,Obor"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total_count"], 2)
        self.assertEqual({r["url"] for r in body["results"]}, {"https://example.com/a", "https://example.com/b"})

    def test_max_price_excludes_more_expensive_listing(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params={"districts": "Dristor,Obor", "max_price": 600})
        body = resp.json()
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["results"][0]["url"], "https://example.com/a")

    def test_rooms_filter(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params={"districts": "Dristor,Obor", "rooms": "1"})
        body = resp.json()
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["results"][0]["url"], "https://example.com/b")

    def test_property_types_filter(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params={"districts": "Dristor,Obor", "property_types": "Studio"})
        body = resp.json()
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["results"][0]["property_type"], "Studio")

    def test_min_and_max_sqm_filter(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get(
                "/listings/search",
                params={"districts": "Dristor,Obor", "min_sqm": 40, "max_sqm": 60},
            )
        body = resp.json()
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["results"][0]["url"], "https://example.com/a")

    def test_district_names_forwarded_to_db_layer(self):
        p1, p2, p3 = _patch_db()
        with p1 as mock_query, p2, p3:
            client.get("/listings/search", params={"districts": "Dristor"})
        called_names = mock_query.call_args.args[0]
        self.assertEqual(set(called_names), {"Dristor"})


class NearbyZoneTests(unittest.TestCase):
    def test_nearby_districts_are_included_in_the_db_query(self):
        p1, p2, p3 = _patch_db()
        with p1 as mock_query, p2, p3:
            client.get("/listings/search", params={"districts": "Dristor", "nearby_districts": "Obor"})
        called_names = mock_query.call_args.args[0]
        self.assertEqual(set(called_names), {"Dristor", "Obor"})

    def test_result_from_nearby_only_district_is_flagged(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params={"districts": "Dristor", "nearby_districts": "Obor"})
        results = {r["url"]: r for r in resp.json()["results"]}
        self.assertFalse(results["https://example.com/a"]["isNearbyZone"])  # Dristor: core zone
        self.assertTrue(results["https://example.com/b"]["isNearbyZone"])   # Obor: nearby only

    def test_result_present_in_both_core_and_nearby_is_not_flagged(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get(
                "/listings/search", params={"districts": "Dristor,Obor", "nearby_districts": "Obor"}
            )
        results = {r["url"]: r for r in resp.json()["results"]}
        self.assertFalse(results["https://example.com/b"]["isNearbyZone"])


class VibeRankingGatingTests(unittest.TestCase):
    def test_vibe_absent_never_calls_embed_or_text_search(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3, \
             patch("api.main.embed_query") as mock_embed, \
             patch("api.main.db_utils.search_by_text_vibe") as mock_search:
            resp = client.get("/listings/search", params={"districts": "Dristor,Obor"})
        mock_embed.assert_not_called()
        mock_search.assert_not_called()
        self.assertFalse(resp.json()["embedding_sorted"])

    def test_vibe_present_invokes_ranking_and_reorders_by_score(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3, \
             patch("api.main.embed_query", return_value=[0.1] * 384) as mock_embed, \
             patch(
                 "api.main.db_utils.search_by_text_vibe",
                 return_value={"https://example.com/b": 0.9, "https://example.com/a": 0.2},
             ) as mock_search:
            resp = client.get(
                "/listings/search",
                params={"districts": "Dristor,Obor", "vibe": "aproape de metrou"},
            )
        mock_embed.assert_called_once_with("aproape de metrou")
        mock_search.assert_called_once()
        body = resp.json()
        self.assertTrue(body["embedding_sorted"])
        self.assertEqual(body["results"][0]["url"], "https://example.com/b")
        self.assertIsNotNone(body["results"][0]["matchScore"])


class PaginationTests(unittest.TestCase):
    def test_page_size_slices_results_and_total_count_reflects_full_set(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get(
                "/listings/search", params={"districts": "Dristor,Obor", "page_size": 1, "page": 1}
            )
        body = resp.json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["total_count"], 2)
        self.assertEqual(body["page"], 1)

    def test_second_page_returns_the_remaining_row(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            page1 = client.get(
                "/listings/search", params={"districts": "Dristor,Obor", "page_size": 1, "page": 1}
            ).json()
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            page2 = client.get(
                "/listings/search", params={"districts": "Dristor,Obor", "page_size": 1, "page": 2}
            ).json()
        self.assertEqual(len(page2["results"]), 1)
        self.assertNotEqual(page1["results"][0]["url"], page2["results"][0]["url"])
        self.assertEqual(
            {page1["results"][0]["url"], page2["results"][0]["url"]},
            {"https://example.com/a", "https://example.com/b"},
        )


class CorsTests(unittest.TestCase):
    def test_cors_header_present_for_allowed_origin(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get(
                "/listings/search",
                params={"districts": "Dristor"},
                headers={"Origin": "http://localhost:3000"},
            )
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "http://localhost:3000")

    def test_cors_header_absent_for_disallowed_origin(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get(
                "/listings/search",
                params={"districts": "Dristor"},
                headers={"Origin": "https://evil.example.com"},
            )
        self.assertIsNone(resp.headers.get("access-control-allow-origin"))


if __name__ == "__main__":
    unittest.main()
