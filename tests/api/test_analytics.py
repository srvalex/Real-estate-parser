"""
Tests for api/analytics.py — the market-analytics aggregation behind the
internal dashboard.

Pure functions over row dicts: no Supabase, no app fixture. price_in_eur
and sector_for are injected by prepare_rows, so the stubs here fix the
exchange rate and the sector map instead of reaching for the live BNR rate
or cities.json.
"""
import unittest

from api import analytics


def _price_in_eur(price_numeric, price_currency):
    """Stand-in for db_utils.price_in_eur with a fixed 5.0 RON rate."""
    if price_numeric is None:
        return None
    try:
        value = float(price_numeric)
    except (TypeError, ValueError):
        return None
    return value / 5.0 if price_currency == "RON" else value


_SECTORS = {("Bucuresti", "Aviatiei"): "Sector 1", ("Bucuresti", "Dorobanti"): "Sector 1",
            ("Bucuresti", "Berceni"): "Sector 4"}


def _sector_for(city, neighborhood):
    return _SECTORS.get((city, neighborhood), "")


def _row(**overrides) -> dict:
    base = {
        "platform_id": "olx",
        "city": "Bucuresti",
        "district": "Aviatiei",
        "price_numeric": 500,
        "price_currency": "EUR",
        "rooms": "2 camere",
        "area_sqm": 55,
        "property_type": "Apartament",
        "first_seen_at": "2026-08-01T10:00:00+00:00",
        "scraped_at": "2026-08-02T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def _prepare(rows):
    return analytics.prepare_rows(rows, price_in_eur=_price_in_eur, sector_for=_sector_for)


class PrepareRowsTests(unittest.TestCase):
    def test_ron_price_is_converted_to_eur(self):
        [row] = _prepare([_row(price_numeric=2500, price_currency="RON")])
        self.assertEqual(row["price_eur"], 500.0)

    def test_price_below_floor_is_dropped_but_row_is_kept(self):
        [row] = _prepare([_row(price_numeric=20)])
        self.assertIsNone(row["price_eur"])

    def test_price_above_ceiling_is_dropped(self):
        [row] = _prepare([_row(price_numeric=150_000)])
        self.assertIsNone(row["price_eur"])

    def test_missing_price_yields_none_rather_than_raising(self):
        [row] = _prepare([_row(price_numeric=None)])
        self.assertIsNone(row["price_eur"])

    def test_rooms_are_normalised_from_free_text(self):
        rows = _prepare([
            _row(rooms="2 camere"), _row(rooms="5"), _row(rooms="6"),
            _row(rooms="garsoniera"), _row(rooms=None),
        ])
        self.assertEqual([r["rooms"] for r in rows], ["2", "5+", "5+", "?", "?"])

    def test_sector_lookup_is_city_scoped(self):
        rows = _prepare([
            _row(city="Bucuresti", district="Aviatiei"),
            _row(city="Iasi", district="Aviatiei"),  # same name, different city
        ])
        self.assertEqual([r["sector"] for r in rows], ["Sector 1", ""])

    def test_non_numeric_area_becomes_none(self):
        [row] = _prepare([_row(area_sqm="n/a")])
        self.assertIsNone(row["area"])


class KpiTests(unittest.TestCase):
    def test_kpis_over_mixed_rows(self):
        rows = _prepare([
            _row(price_numeric=400, area_sqm=40),
            _row(price_numeric=600, area_sqm=60),
            _row(price_numeric=None, area_sqm=50),
        ])
        kpis = analytics.compute_kpis(rows)
        self.assertEqual(kpis["total"], 3)
        self.assertEqual(kpis["with_price"], 2)
        self.assertEqual(kpis["with_price_pct"], 66.7)
        self.assertEqual(kpis["avg_price"], 500)
        self.assertEqual(kpis["median_price"], 500)
        self.assertEqual(kpis["avg_area"], 50)

    def test_empty_input_returns_zeroes_not_a_division_error(self):
        self.assertEqual(
            analytics.compute_kpis([]),
            {"total": 0, "with_price": 0, "with_price_pct": 0.0,
             "avg_price": 0, "median_price": 0, "avg_area": 0},
        )


class DailyListingsTests(unittest.TestCase):
    def test_groups_by_first_seen_day_and_sorts(self):
        rows = _prepare([
            _row(first_seen_at="2026-08-02T09:00:00+00:00"),
            _row(first_seen_at="2026-08-01T23:00:00+00:00"),
            _row(first_seen_at="2026-08-02T18:00:00+00:00"),
        ])
        self.assertEqual(
            analytics.daily_listings(rows),
            [{"day": "2026-08-01", "count": 1}, {"day": "2026-08-02", "count": 2}],
        )

    def test_falls_back_to_scraped_at_when_first_seen_is_missing(self):
        rows = _prepare([_row(first_seen_at=None, scraped_at="2026-08-05T00:00:00+00:00")])
        self.assertEqual(analytics.daily_listings(rows), [{"day": "2026-08-05", "count": 1}])

    def test_rows_with_no_timestamp_are_skipped(self):
        rows = _prepare([_row(first_seen_at=None, scraped_at=None)])
        self.assertEqual(analytics.daily_listings(rows), [])


class HistogramTests(unittest.TestCase):
    def test_empty_buckets_between_extremes_are_present(self):
        rows = _prepare([_row(price_numeric=310), _row(price_numeric=520)])
        bins = analytics.price_histogram(rows, bucket_size=100)
        self.assertEqual([b["bucket"] for b in bins], [300, 400, 500])
        self.assertEqual([b["count"] for b in bins], [1, 0, 1])

    def test_no_priced_rows_yields_no_bins(self):
        self.assertEqual(analytics.price_histogram(_prepare([_row(price_numeric=None)])), [])


class GroupedPriceTests(unittest.TestCase):
    def test_avg_and_median_by_sector(self):
        rows = _prepare([
            _row(district="Aviatiei", price_numeric=400),
            _row(district="Dorobanti", price_numeric=800),
            _row(district="Dorobanti", price_numeric=1000),
            _row(district="Berceni", price_numeric=300),
        ])
        by_sector = {s["sector"]: s for s in analytics.avg_price_by_sector(rows)}
        self.assertEqual(by_sector["Sector 1"]["avg"], 733)
        self.assertEqual(by_sector["Sector 1"]["median"], 800)
        self.assertEqual(by_sector["Sector 1"]["count"], 3)
        self.assertEqual(by_sector["Sector 1"]["label"], "S1")
        self.assertEqual(by_sector["Sector 4"]["avg"], 300)

    def test_rows_without_a_sector_are_excluded(self):
        rows = _prepare([_row(district="Nowhere", price_numeric=500)])
        self.assertEqual(analytics.avg_price_by_sector(rows), [])

    def test_neighbourhood_needs_three_listings_to_appear(self):
        rows = _prepare([
            _row(district="Aviatiei", price_numeric=500),
            _row(district="Aviatiei", price_numeric=600),
            _row(district="Dorobanti", price_numeric=900),
            _row(district="Dorobanti", price_numeric=1000),
            _row(district="Dorobanti", price_numeric=1100),
        ])
        result = analytics.avg_price_by_neighbourhood(rows, "Sector 1")
        self.assertEqual([d["district"] for d in result], ["Dorobanti"])
        self.assertEqual(result[0]["avg"], 1000)

    def test_neighbourhoods_are_sorted_cheapest_first(self):
        rows = _prepare(
            [_row(district="Dorobanti", price_numeric=1000)] * 3
            + [_row(district="Aviatiei", price_numeric=400)] * 3
        )
        result = analytics.avg_price_by_neighbourhood(rows, "Sector 1")
        self.assertEqual([d["district"] for d in result], ["Aviatiei", "Dorobanti"])

    def test_price_by_rooms_follows_room_order_and_skips_unknown(self):
        rows = _prepare([
            _row(rooms="3", price_numeric=900),
            _row(rooms="1", price_numeric=300),
            _row(rooms="1", price_numeric=500),
            _row(rooms="garsoniera", price_numeric=250),
        ])
        result = analytics.avg_price_by_rooms(rows)
        self.assertEqual([r["rooms"] for r in result], ["1", "3"])
        self.assertEqual(result[0], {"rooms": "1", "avg": 400, "median": 400,
                                     "min": 300, "max": 500, "count": 2})


class DistributionTests(unittest.TestCase):
    def test_rooms_distribution_reports_zero_for_absent_buckets(self):
        rows = _prepare([_row(rooms="2"), _row(rooms="2")])
        counts = {d["rooms"]: d["count"] for d in analytics.rooms_distribution(rows)}
        self.assertEqual(counts["2"], 2)
        self.assertEqual(counts["4"], 0)
        self.assertEqual(list(counts), analytics.ROOM_ORDER)

    def test_room_order_matches_what_normalisation_can_produce(self):
        """A bucket normalisation never emits would be a permanently empty
        bar in the dashboard — regression guard for exactly that."""
        producible = {analytics._normalise_rooms(v) for v in list(range(1, 12)) + ["garsoniera"]}
        self.assertEqual(set(analytics.ROOM_ORDER), producible - {"?"})

    def test_platform_breakdown_is_ordered_by_size(self):
        rows = _prepare([_row(platform_id="olx"), _row(platform_id="storia"), _row(platform_id="olx")])
        self.assertEqual(
            analytics.platform_breakdown(rows),
            [{"name": "olx", "value": 2}, {"name": "storia", "value": 1}],
        )

    def test_property_type_breakdown_ignores_empty_values(self):
        rows = _prepare([_row(property_type="Apartament"), _row(property_type=None)])
        self.assertEqual(analytics.property_type_breakdown(rows), [{"name": "Apartament", "value": 1}])


class ScatterTests(unittest.TestCase):
    def test_out_of_range_areas_are_excluded(self):
        rows = _prepare([_row(area_sqm=5), _row(area_sqm=500), _row(area_sqm=55), _row(area_sqm=None)])
        points = analytics.price_vs_area(rows)
        self.assertEqual([p["area"] for p in points], [55.0])

    def test_downsample_caps_length_and_is_deterministic(self):
        rows = _prepare([_row(price_numeric=100 + i, area_sqm=30 + (i % 100)) for i in range(500)])
        first = analytics.price_vs_area(rows, limit=50)
        second = analytics.price_vs_area(rows, limit=50)
        self.assertEqual(len(first), 50)
        self.assertEqual(first, second)

    def test_downsample_keeps_both_price_extremes(self):
        rows = _prepare([_row(price_numeric=100 + i, area_sqm=50) for i in range(300)])
        points = analytics.price_vs_area(rows, limit=20)
        self.assertEqual(points[0]["price"], 100)
        self.assertLessEqual(points[-1]["price"], 399)


class SummaryTests(unittest.TestCase):
    def test_summary_carries_every_chart_and_no_listing_fields(self):
        rows = _prepare([_row(district="Aviatiei", price_numeric=500 + i * 10) for i in range(5)])
        summary = analytics.build_summary(rows)
        self.assertEqual(
            set(summary),
            {"kpis", "sector_coverage", "daily_listings", "price_histogram", "by_sector",
             "by_neighbourhood", "by_rooms", "rooms_distribution", "platforms",
             "property_types", "price_vs_area"},
        )
        # No raw-listing identifiers may leak through the aggregation layer.
        serialised = repr(summary)
        for leaked in ("url", "title", "description", "image_urls"):
            self.assertNotIn(leaked, serialised)

    def test_neighbourhood_drilldown_is_keyed_by_sector(self):
        rows = _prepare([_row(district="Aviatiei", price_numeric=500)] * 3)
        summary = analytics.build_summary(rows)
        self.assertIn("Sector 1", summary["by_neighbourhood"])
        self.assertEqual(summary["by_neighbourhood"]["Sector 1"][0]["district"], "Aviatiei")

    def test_empty_rows_produce_a_complete_but_empty_summary(self):
        summary = analytics.build_summary([])
        self.assertEqual(summary["kpis"]["total"], 0)
        self.assertEqual(summary["by_sector"], [])
        self.assertEqual(summary["price_vs_area"], [])



class SectorCoverageTests(unittest.TestCase):
    """The sector charts can only cover listings whose district resolves to
    a sector. Live 2026-09-08, 1,292 of 10,783 priced Bucharest listings
    had none (blank district, or an Ilfov satellite town scraped as
    Bucharest) — the charts silently stood in for a city 12% larger than
    they represented. The gap is now reported rather than dropped."""

    def _prepare_with_layers(self, rows):
        return analytics.prepare_rows(
            rows,
            price_in_eur=_price_in_eur,
            sector_for=_sector_for,
            city_has_sectors=lambda c: c == "Bucuresti",
        )

    def test_unmapped_district_counts_as_missing_not_attributed(self):
        rows = self._prepare_with_layers([
            _row(district="Aviatiei"),
            _row(district="Voluntari"),   # Ilfov, scraped as Bucharest
            _row(district=""),            # crawler found no district
        ])
        self.assertEqual(
            analytics.sector_coverage(rows),
            {"attributed": 1, "missing": 2, "eligible": 3},
        )

    def test_cities_without_sectors_are_not_reported_as_a_gap(self):
        rows = self._prepare_with_layers([
            _row(city="Cluj-Napoca", district="Centru"),
            _row(city="Iasi", district="Copou"),
        ])
        self.assertEqual(
            analytics.sector_coverage(rows),
            {"attributed": 0, "missing": 0, "eligible": 0},
        )

    def test_unpriced_rows_are_outside_the_coverage_denominator(self):
        # Sector charts are price charts; a row with no usable price was
        # never eligible for them, so counting it as "missing" would
        # overstate the attribution gap.
        rows = self._prepare_with_layers([_row(district="", price_numeric=None)])
        self.assertEqual(analytics.sector_coverage(rows)["eligible"], 0)

    def test_attributed_matches_the_sector_chart_totals(self):
        rows = self._prepare_with_layers([
            _row(district="Aviatiei"), _row(district="Dorobanti"),
            _row(district="Berceni"), _row(district="Voluntari"),
        ])
        coverage = analytics.sector_coverage(rows)
        charted = sum(s["count"] for s in analytics.avg_price_by_sector(rows))
        self.assertEqual(coverage["attributed"], charted)
        self.assertEqual(coverage["attributed"] + coverage["missing"], coverage["eligible"])

    def test_summary_carries_coverage(self):
        rows = self._prepare_with_layers([_row(district="Aviatiei"), _row(district="Voluntari")])
        self.assertEqual(analytics.build_summary(rows)["sector_coverage"]["missing"], 1)


class RoomFilterTests(unittest.TestCase):
    def test_selected_room_counts_are_kept(self):
        rows = _prepare([_row(rooms="1"), _row(rooms="2"), _row(rooms="3")])
        kept = analytics.filter_by_rooms(rows, ["2", "3"])
        self.assertEqual(sorted(r["rooms"] for r in kept), ["2", "3"])

    def test_filter_matches_the_normalised_value_not_the_raw_text(self):
        # "2 camere" and 7 rooms reach filter_by_rooms as "2" and "5+".
        rows = _prepare([_row(rooms="2 camere"), _row(rooms="7")])
        self.assertEqual(len(analytics.filter_by_rooms(rows, ["2"])), 1)
        self.assertEqual(len(analytics.filter_by_rooms(rows, ["5+"])), 1)

    def test_empty_selection_means_everything_not_nothing(self):
        rows = _prepare([_row(rooms="1"), _row(rooms="2")])
        for empty in (None, [], ()):
            with self.subTest(empty=empty):
                self.assertEqual(len(analytics.filter_by_rooms(rows, empty)), 2)

    def test_selection_matching_no_row_yields_an_empty_set(self):
        rows = _prepare([_row(rooms="1")])
        self.assertEqual(analytics.filter_by_rooms(rows, ["4"]), [])

    def test_filtering_flows_through_to_every_aggregate(self):
        rows = _prepare([
            _row(rooms="1", price_numeric=400),
            _row(rooms="2", price_numeric=800),
            _row(rooms="2", price_numeric=600),
        ])
        summary = analytics.build_summary(analytics.filter_by_rooms(rows, ["2"]))
        self.assertEqual(summary["kpis"]["total"], 2)
        self.assertEqual(summary["kpis"]["avg_price"], 700)
        self.assertEqual(summary["by_sector"][0]["count"], 2)

    def test_rooms_native_charts_are_omitted_while_filtering(self):
        rows = _prepare([_row(rooms="2")])
        filtered = analytics.build_summary(rows, rooms_filtered=True)
        self.assertEqual(filtered["by_rooms"], [])
        self.assertEqual(filtered["rooms_distribution"], [])

    def test_rooms_native_charts_are_present_when_not_filtering(self):
        rows = _prepare([_row(rooms="2")])
        unfiltered = analytics.build_summary(rows, rooms_filtered=False)
        self.assertTrue(unfiltered["by_rooms"])
        self.assertTrue(unfiltered["rooms_distribution"])

if __name__ == "__main__":
    unittest.main()
