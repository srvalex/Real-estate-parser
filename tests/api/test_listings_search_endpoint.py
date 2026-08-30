"""
Tests for GET /listings/search (api/main.py), MIGRATION_PLAN.md Phase 1
(hard filters) + Phase 3 (vibe ranking) + GEO_EXPANSION_PLAN.md Phase 0
(city scoping), combined.

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


def _params(**overrides):
    """Every request needs `city` now (GEO_EXPANSION_PLAN.md Phase 0) — this
    just keeps every other test from repeating that boilerplate."""
    base = {"city": "Bucuresti", "districts": "Dristor,Obor"}
    base.update(overrides)
    return base


class RequiredParamTests(unittest.TestCase):
    def test_missing_districts_is_rejected(self):
        resp = client.get("/listings/search", params={"city": "Bucuresti"})
        self.assertEqual(resp.status_code, 422)

    def test_empty_districts_is_rejected(self):
        resp = client.get("/listings/search", params={"city": "Bucuresti", "districts": "  , "})
        self.assertEqual(resp.status_code, 422)

    def test_missing_city_is_rejected(self):
        resp = client.get("/listings/search", params={"districts": "Dristor"})
        self.assertEqual(resp.status_code, 422)


class CityScopingTests(unittest.TestCase):
    """The actual bug this phase exists to prevent: neighbourhood names are
    not globally unique once more than one city's data exists — confirmed
    live 2026-08-30 that "Centru" exists in both Cluj-Napoca and Iași, and
    "Dacia"/"Aviatiei"/"Cantemir"/"Tudor Vladimirescu" exist in both
    București and Iași. Without city scoping, selecting Cluj-Napoca's
    "Centru" would silently also return Iași's "Centru" listings."""

    def test_city_forwarded_to_district_query(self):
        p1, p2, p3 = _patch_db()
        with p1 as mock_query, p2, p3:
            client.get("/listings/search", params=_params(city="Cluj-Napoca", districts="Centru"))
        self.assertEqual(mock_query.call_args.kwargs.get("city"), "Cluj-Napoca")

    def test_city_forwarded_to_price_stats(self):
        p1, p2, p3 = _patch_db()
        with p1, p2 as mock_stats, p3:
            client.get("/listings/search", params=_params(city="Iasi", districts="Centru"))
        self.assertEqual(mock_stats.call_args.kwargs.get("city"), "Iasi")

    def test_applied_filters_echoes_the_requested_city(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params=_params(city="Cluj-Napoca", districts="Centru"))
        self.assertEqual(resp.json()["applied_filters"]["city"]["value"], "Cluj-Napoca")

    def test_sector_lookup_is_scoped_to_the_requested_city(self):
        """"Dacia" exists in both București (with a real sector) and Iași
        (no sector layer) — the response's `sector` field must reflect
        whichever city was actually requested, not silently resolve via
        the other city's data."""
        rows = [{**_SAMPLE_ROWS[0], "district": "Dacia"}]
        p1, p2, p3 = _patch_db(rows=rows)
        with p1, p2, p3:
            bucharest_resp = client.get("/listings/search", params=_params(city="Bucuresti", districts="Dacia"))
        with p1, p2, p3:
            iasi_resp = client.get("/listings/search", params=_params(city="Iasi", districts="Dacia"))
        self.assertNotEqual(bucharest_resp.json()["results"][0]["sector"], "")
        self.assertEqual(iasi_resp.json()["results"][0]["sector"], "")


def _patch_db_whole_city_paginated(rows=None, total=None, price_stats=None):
    resolved_rows = rows if rows is not None else _SAMPLE_ROWS
    resolved_total = total if total is not None else len(resolved_rows)
    return (
        patch(
            "api.main.db_utils.query_listings_by_city_paginated",
            return_value=(resolved_rows, resolved_total),
        ),
        patch("api.main.db_utils.get_price_stats", return_value=price_stats or {}),
        patch("api.main.db_utils.log_user_search", return_value=True),
    )


def _patch_db_whole_city(rows=None, price_stats=None):
    return (
        patch("api.main.db_utils.query_listings_by_city", return_value=rows if rows is not None else _SAMPLE_ROWS),
        patch("api.main.db_utils.get_price_stats", return_value=price_stats or {}),
        patch("api.main.db_utils.log_user_search", return_value=True),
    )


class AllDistrictsTests(unittest.TestCase):
    """`all_districts=true` is the "search the whole city" mode: no
    `districts` param required.

    Without a vibe/image query to rank over, it goes through the fast
    paginated path (query_listings_by_city_paginated — hard filters and
    pagination pushed into the SQL query, never fetches more than one
    page). query_listings_by_city (fetch-the-entire-city) measured ~34s
    for a ~9000-row city precisely because it has no way to stop early —
    apply_ai_scores needs the full matching set in memory to rank, so a
    vibe/image query still has to fall back to it."""

    def test_all_districts_true_without_districts_succeeds(self):
        p1, p2, p3 = _patch_db_whole_city_paginated()
        with p1, p2, p3:
            resp = client.get("/listings/search", params={"city": "Iasi", "all_districts": "true"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total_count"], 2)

    def test_all_districts_without_vibe_uses_the_paginated_fast_path(self):
        p1, p2, p3 = _patch_db_whole_city_paginated()
        with p1 as mock_paginated, p2, p3, \
             patch("api.main.db_utils.query_listings_by_city") as mock_city_fetch_all, \
             patch("api.main.db_utils.query_listings_by_district") as mock_district_query:
            client.get("/listings/search", params={"city": "Iasi", "all_districts": "true"})
        mock_paginated.assert_called_once()
        mock_city_fetch_all.assert_not_called()
        mock_district_query.assert_not_called()

    def test_all_districts_forwards_city_max_price_and_page_offset(self):
        p1, p2, p3 = _patch_db_whole_city_paginated()
        with p1 as mock_paginated, p2, p3:
            client.get(
                "/listings/search",
                params={"city": "Iasi", "all_districts": "true", "max_price": 500, "page": 2, "page_size": 24},
            )
        self.assertEqual(mock_paginated.call_args.args[0], "Iasi")
        self.assertEqual(mock_paginated.call_args.kwargs.get("max_price_eur"), 500)
        self.assertEqual(mock_paginated.call_args.kwargs.get("offset"), 24)
        self.assertEqual(mock_paginated.call_args.kwargs.get("limit"), 24)

    def test_all_districts_forwards_rooms_sqm_and_property_types(self):
        p1, p2, p3 = _patch_db_whole_city_paginated()
        with p1 as mock_paginated, p2, p3:
            client.get(
                "/listings/search",
                params={
                    "city": "Iasi",
                    "all_districts": "true",
                    "rooms": "2",
                    "min_sqm": 40,
                    "max_sqm": 80,
                    "property_types": "Apartament,Studio",
                },
            )
        kwargs = mock_paginated.call_args.kwargs
        self.assertEqual(kwargs.get("rooms"), "2")
        self.assertEqual(kwargs.get("min_sqm"), 40)
        self.assertEqual(kwargs.get("max_sqm"), 80)
        self.assertEqual(kwargs.get("property_types"), ["Apartament", "Studio"])

    def test_all_districts_rooms_orice_is_not_forwarded_as_a_filter(self):
        p1, p2, p3 = _patch_db_whole_city_paginated()
        with p1 as mock_paginated, p2, p3:
            client.get("/listings/search", params={"city": "Iasi", "all_districts": "true", "rooms": "Orice"})
        self.assertIsNone(mock_paginated.call_args.kwargs.get("rooms"))

    def test_all_districts_echoes_in_applied_filters_without_districts_key(self):
        p1, p2, p3 = _patch_db_whole_city_paginated()
        with p1, p2, p3:
            resp = client.get("/listings/search", params={"city": "Iasi", "all_districts": "true"})
        applied = resp.json()["applied_filters"]
        self.assertEqual(applied["all_districts"]["value"], True)
        self.assertNotIn("districts", applied)

    def test_all_districts_with_vibe_falls_back_to_the_fetch_everything_path(self):
        """A vibe query needs the full matching set in memory to rank —
        the paginated SQL fast path can't do that, so all_districts=true
        combined with a vibe must still go through query_listings_by_city."""
        p1, p2, p3 = _patch_db_whole_city()
        with p1 as mock_city_fetch_all, p2, p3, \
             patch("api.main.db_utils.query_listings_by_city_paginated") as mock_paginated, \
             patch("api.main.embed_query", return_value=[0.1] * 384), \
             patch("api.main.db_utils.search_by_text_vibe", return_value={}):
            resp = client.get(
                "/listings/search", params={"city": "Iasi", "all_districts": "true", "vibe": "aproape de metrou"}
            )
        self.assertEqual(resp.status_code, 200)
        mock_city_fetch_all.assert_called_once()
        mock_paginated.assert_not_called()

    def test_all_districts_false_still_requires_districts(self):
        resp = client.get("/listings/search", params={"city": "Iasi", "all_districts": "false"})
        self.assertEqual(resp.status_code, 422)


class HardFilterTests(unittest.TestCase):
    def test_no_optional_filters_returns_every_row(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params=_params())
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total_count"], 2)
        self.assertEqual({r["url"] for r in body["results"]}, {"https://example.com/a", "https://example.com/b"})

    def test_max_price_excludes_more_expensive_listing(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params=_params(max_price=600))
        body = resp.json()
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["results"][0]["url"], "https://example.com/a")

    def test_rooms_filter(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params=_params(rooms="1"))
        body = resp.json()
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["results"][0]["url"], "https://example.com/b")

    def test_property_types_filter(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params=_params(property_types="Studio"))
        body = resp.json()
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["results"][0]["property_type"], "Studio")

    def test_min_and_max_sqm_filter(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params=_params(min_sqm=40, max_sqm=60))
        body = resp.json()
        self.assertEqual(body["total_count"], 1)
        self.assertEqual(body["results"][0]["url"], "https://example.com/a")

    def test_district_names_forwarded_to_db_layer(self):
        p1, p2, p3 = _patch_db()
        with p1 as mock_query, p2, p3:
            client.get("/listings/search", params=_params(districts="Dristor"))
        called_names = mock_query.call_args.args[0]
        self.assertEqual(set(called_names), {"Dristor"})


class NearbyZoneTests(unittest.TestCase):
    def test_nearby_districts_are_included_in_the_db_query(self):
        p1, p2, p3 = _patch_db()
        with p1 as mock_query, p2, p3:
            client.get("/listings/search", params=_params(districts="Dristor", nearby_districts="Obor"))
        called_names = mock_query.call_args.args[0]
        self.assertEqual(set(called_names), {"Dristor", "Obor"})

    def test_result_from_nearby_only_district_is_flagged(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params=_params(districts="Dristor", nearby_districts="Obor"))
        results = {r["url"]: r for r in resp.json()["results"]}
        self.assertFalse(results["https://example.com/a"]["isNearbyZone"])  # Dristor: core zone
        self.assertTrue(results["https://example.com/b"]["isNearbyZone"])   # Obor: nearby only

    def test_result_present_in_both_core_and_nearby_is_not_flagged(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get(
                "/listings/search", params=_params(districts="Dristor,Obor", nearby_districts="Obor")
            )
        results = {r["url"]: r for r in resp.json()["results"]}
        self.assertFalse(results["https://example.com/b"]["isNearbyZone"])


class VibeRankingGatingTests(unittest.TestCase):
    def test_vibe_absent_never_calls_embed_or_text_search(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3, \
             patch("api.main.embed_query") as mock_embed, \
             patch("api.main.db_utils.search_by_text_vibe") as mock_search:
            resp = client.get("/listings/search", params=_params())
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
            resp = client.get("/listings/search", params=_params(vibe="aproape de metrou"))
        mock_embed.assert_called_once_with("aproape de metrou")
        mock_search.assert_called_once()
        body = resp.json()
        self.assertTrue(body["embedding_sorted"])
        self.assertEqual(body["results"][0]["url"], "https://example.com/b")
        self.assertIsNotNone(body["results"][0]["matchScore"])
        # text-only search: no image channel ran, so imageSimilarity stays null
        self.assertIsNone(body["results"][0]["imageSimilarity"])
        self.assertIsNotNone(body["results"][0]["textSimilarity"])


class TemplatePhotoSearchTests(unittest.TestCase):
    def test_no_template_photos_never_looks_up_an_embedding_or_runs_image_search(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3, \
             patch("api.main.get_combined_embedding") as mock_combine, \
             patch("api.main.db_utils.search_by_image_embedding") as mock_image_search:
            client.get("/listings/search", params=_params())
        mock_combine.assert_not_called()
        mock_image_search.assert_not_called()

    def test_template_photos_present_runs_image_search_without_vibe_text(self):
        p1, p2, p3 = _patch_db()
        fake_embedding = [0.3] * 512
        with p1, p2, p3, \
             patch("api.main.get_combined_embedding", return_value=fake_embedding) as mock_combine, \
             patch("api.main.embed_query") as mock_text_embed, \
             patch(
                 "api.main.db_utils.search_by_image_embedding",
                 return_value={"https://example.com/a": 0.7},
             ) as mock_image_search:
            resp = client.get("/listings/search", params=_params(template_photos="template_1"))
        mock_combine.assert_called_once_with(["template_1"])
        mock_text_embed.assert_not_called()
        mock_image_search.assert_called_once()
        called_embedding = mock_image_search.call_args.args[0]
        self.assertEqual(called_embedding, fake_embedding)

        body = resp.json()
        self.assertTrue(body["embedding_sorted"])
        result_a = next(r for r in body["results"] if r["url"] == "https://example.com/a")
        self.assertIsNotNone(result_a["imageSimilarity"])
        self.assertIsNone(result_a["textSimilarity"])
        self.assertEqual(body["applied_filters"]["template_photos"]["value"], ["template_1"])

    def test_multiple_template_photos_forwarded_as_a_list(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3, \
             patch("api.main.get_combined_embedding", return_value=[0.1] * 512) as mock_combine, \
             patch("api.main.db_utils.search_by_image_embedding", return_value={}):
            client.get("/listings/search", params=_params(template_photos="template_1,template_3"))
        mock_combine.assert_called_once_with(["template_1", "template_3"])

    def test_vibe_and_template_photos_together_run_both_channels(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3, \
             patch("api.main.get_combined_embedding", return_value=[0.2] * 512), \
             patch("api.main.embed_query", return_value=[0.1] * 384), \
             patch("api.main.db_utils.search_by_text_vibe", return_value={"https://example.com/a": 0.5}), \
             patch("api.main.db_utils.search_by_image_embedding", return_value={"https://example.com/b": 0.9}):
            resp = client.get(
                "/listings/search", params=_params(vibe="luminos", template_photos="template_2")
            )
        body = resp.json()
        results = {r["url"]: r for r in body["results"]}
        self.assertIsNotNone(results["https://example.com/a"]["textSimilarity"])
        self.assertIsNotNone(results["https://example.com/b"]["imageSimilarity"])


class TemplatePhotoListEndpointTests(unittest.TestCase):
    def test_returns_the_four_known_photos(self):
        resp = client.get("/template-photos")
        self.assertEqual(resp.status_code, 200)
        ids = [p["id"] for p in resp.json()]
        self.assertEqual(ids, ["template_1", "template_2", "template_3", "template_4"])


class PaginationTests(unittest.TestCase):
    def test_page_size_slices_results_and_total_count_reflects_full_set(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get("/listings/search", params=_params(page_size=1, page=1))
        body = resp.json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["total_count"], 2)
        self.assertEqual(body["page"], 1)

    def test_second_page_returns_the_remaining_row(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            page1 = client.get("/listings/search", params=_params(page_size=1, page=1)).json()
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            page2 = client.get("/listings/search", params=_params(page_size=1, page=2)).json()
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
                params=_params(districts="Dristor"),
                headers={"Origin": "http://localhost:3000"},
            )
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "http://localhost:3000")

    def test_cors_header_absent_for_disallowed_origin(self):
        p1, p2, p3 = _patch_db()
        with p1, p2, p3:
            resp = client.get(
                "/listings/search",
                params=_params(districts="Dristor"),
                headers={"Origin": "https://evil.example.com"},
            )
        self.assertIsNone(resp.headers.get("access-control-allow-origin"))


if __name__ == "__main__":
    unittest.main()
