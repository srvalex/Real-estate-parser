"""
score_enrichment/score_filter_query/aggregate_accuracy are pure functions —
no I/O, no model calls — so these run without Ollama or a DB.
"""
import unittest

from benchmarks.llm.enrichment_schema import (
    CanonicalFill,
    EnrichmentResult,
    sanitize_canonical_fill,
)
from benchmarks.llm.scoring import (
    aggregate_accuracy,
    score_canonical_fill,
    score_enrichment,
    score_filter_query,
)
from query_model import ExtraFilter, ListingQuery


class ScoreEnrichmentTests(unittest.TestCase):
    def test_all_fields_match_when_identical(self):
        result = EnrichmentResult(own_heating="yes", parking_available="yes",
                                  pets_allowed="yes", renovation_status="renovated")
        self.assertTrue(all(score_enrichment(result, result).values()))

    def test_every_schema_field_is_scored(self):
        scores = score_enrichment(EnrichmentResult(), EnrichmentResult())
        self.assertEqual(set(scores), set(EnrichmentResult.model_fields))

    def test_a_single_wrong_field_fails_only_that_field(self):
        expected = EnrichmentResult(own_heating="yes", pets_allowed="no")
        actual = EnrichmentResult(own_heating="no", pets_allowed="no")
        scores = score_enrichment(expected, actual)
        self.assertFalse(scores["own_heating"])
        self.assertTrue(scores["pets_allowed"])

    def test_unknown_is_not_a_free_pass_against_a_stated_value(self):
        """Answering "unknown" where the text stated a fact is a miss, not
        a neutral abstention — coverage is the point of the field."""
        scores = score_enrichment(EnrichmentResult(parking_available="yes"), EnrichmentResult())
        self.assertFalse(scores["parking_available"])


class ScoreFilterQueryTests(unittest.TestCase):
    def test_default_queries_match_on_every_field(self):
        scores = score_filter_query(ListingQuery(), ListingQuery())
        self.assertTrue(all(scores.values()))

    def test_none_vs_none_counts_as_a_match(self):
        expected = ListingQuery(price_min=None)
        actual = ListingQuery(price_min=None)
        scores = score_filter_query(expected, actual)
        self.assertTrue(scores["price_min"])

    def test_list_fields_compared_as_sets_ignoring_order(self):
        expected = ListingQuery(district=["Titan", "Dristor"])
        actual = ListingQuery(district=["Dristor", "Titan"])
        scores = score_filter_query(expected, actual)
        self.assertTrue(scores["district"])

    def test_list_field_mismatch_scored_false(self):
        expected = ListingQuery(district=["Titan"])
        actual = ListingQuery(district=["Militari"])
        scores = score_filter_query(expected, actual)
        self.assertFalse(scores["district"])

    def test_extras_compared_order_independently(self):
        expected = ListingQuery(extras=[
            ExtraFilter(key="heating_type", op="eq", value="gas"),
            ExtraFilter(key="amenities", op="contains", value="lift"),
        ])
        actual = ListingQuery(extras=[
            ExtraFilter(key="amenities", op="contains", value="lift"),
            ExtraFilter(key="heating_type", op="eq", value="gas"),
        ])
        scores = score_filter_query(expected, actual)
        self.assertTrue(scores["extras"])

    def test_extras_mismatch_scored_false(self):
        expected = ListingQuery(extras=[ExtraFilter(key="heating_type", op="eq", value="gas")])
        actual = ListingQuery(extras=[ExtraFilter(key="heating_type", op="eq", value="electric")])
        scores = score_filter_query(expected, actual)
        self.assertFalse(scores["extras"])

    def test_vibe_text_scored_on_presence_not_exact_wording(self):
        expected = ListingQuery(vibe_text="with parking")
        actual = ListingQuery(vibe_text="must have parking")
        scores = score_filter_query(expected, actual)
        self.assertTrue(scores["vibe_text"])

    def test_vibe_text_mismatch_when_one_side_is_none(self):
        expected = ListingQuery(vibe_text="cozy")
        actual = ListingQuery(vibe_text=None)
        scores = score_filter_query(expected, actual)
        self.assertFalse(scores["vibe_text"])

    def test_limit_field_is_excluded_from_scoring(self):
        expected = ListingQuery(limit=50)
        actual = ListingQuery(limit=200)
        scores = score_filter_query(expected, actual)
        self.assertNotIn("limit", scores)


class AggregateAccuracyTests(unittest.TestCase):
    def test_overall_and_per_field_rates_across_samples(self):
        all_scores = [
            {"a": True, "b": False},
            {"a": True, "b": True},
        ]
        result = aggregate_accuracy(all_scores)
        self.assertEqual(result["a"], 1.0)
        self.assertEqual(result["b"], 0.5)
        self.assertEqual(result["overall"], 0.75)

    def test_field_present_in_only_some_samples_is_averaged_over_its_own_count(self):
        all_scores = [
            {"a": True},
            {"a": False, "b": True},
        ]
        result = aggregate_accuracy(all_scores)
        self.assertEqual(result["a"], 0.5)
        self.assertEqual(result["b"], 1.0)

    def test_empty_input_returns_zero_overall(self):
        result = aggregate_accuracy([])
        self.assertEqual(result["overall"], 0.0)


if __name__ == "__main__":
    unittest.main()


class ScoreCanonicalFillTests(unittest.TestCase):
    def test_identical_fills_match_on_every_field(self):
        fill = CanonicalFill(rooms="2", area_sqm=55, floor="6", total_floors="10", year_built="1986")
        self.assertTrue(all(score_canonical_fill(fill, fill).values()))

    def test_text_fields_compare_case_and_whitespace_insensitively(self):
        expected = CanonicalFill(floor="Parter", year_built="Dupa 2000")
        actual = CanonicalFill(floor=" parter ", year_built="dupa 2000")
        scores = score_canonical_fill(expected, actual)
        self.assertTrue(scores["floor"])
        self.assertTrue(scores["year_built"])

    def test_area_within_tolerance_matches(self):
        """"63,3 mp" read back as 63.0 is the same extraction, not a miss."""
        scores = score_canonical_fill(CanonicalFill(area_sqm=63.3), CanonicalFill(area_sqm=63.0))
        self.assertTrue(scores["area_sqm"])

    def test_area_outside_tolerance_does_not_match(self):
        scores = score_canonical_fill(CanonicalFill(area_sqm=83), CanonicalFill(area_sqm=98))
        self.assertFalse(scores["area_sqm"])

    def test_inventing_a_value_the_text_never_stated_is_a_miss(self):
        scores = score_canonical_fill(CanonicalFill(), CanonicalFill(rooms="2", area_sqm=50, floor="3"))
        self.assertFalse(scores["rooms"])
        self.assertFalse(scores["area_sqm"])
        self.assertFalse(scores["floor"])

    def test_missing_a_value_the_text_did_state_is_a_miss(self):
        scores = score_canonical_fill(CanonicalFill(area_sqm=50), CanonicalFill())
        self.assertFalse(scores["area_sqm"])

    def test_both_none_matches(self):
        self.assertTrue(all(score_canonical_fill(CanonicalFill(), CanonicalFill()).values()))

    def test_scores_are_aggregatable_alongside_enrichment_scores(self):
        scores = [
            score_canonical_fill(CanonicalFill(rooms="2"), CanonicalFill(rooms="2")),
            score_canonical_fill(CanonicalFill(rooms="2"), CanonicalFill(rooms="3")),
        ]
        self.assertEqual(aggregate_accuracy(scores)["rooms"], 0.5)


class SecondaryFieldTests(unittest.TestCase):
    """`parking.type` is measured but must not decide the ranking —
    whether a listing has parking at all is the filter that matters."""

    def test_secondary_field_is_excluded_from_overall(self):
        scores = [{"pets_allowed": True, "parking.type": False}]
        result = aggregate_accuracy(scores, frozenset({"parking.type"}))
        self.assertEqual(result["overall"], 1.0)

    def test_secondary_field_is_still_reported_per_field(self):
        scores = [{"pets_allowed": True, "parking.type": False}]
        result = aggregate_accuracy(scores, frozenset({"parking.type"}))
        self.assertEqual(result["parking.type"], 0.0)

    def test_default_still_counts_every_field(self):
        scores = [{"pets_allowed": True, "parking.type": False}]
        self.assertEqual(aggregate_accuracy(scores)["overall"], 0.5)

    def test_overall_is_zero_when_every_scored_field_is_secondary(self):
        result = aggregate_accuracy([{"parking.type": True}], frozenset({"parking.type"}))
        self.assertEqual(result["overall"], 0.0)


class SanitizeCanonicalFillTests(unittest.TestCase):
    """`floor` and `year_built` are TEXT columns, so structured output
    validates any string a model invents — these are the cases the first
    benchmark run actually produced."""

    def test_drops_a_year_that_is_not_a_year(self):
        for junk in ("bloc nou", "nou", "nouă", "Sep 2026", "prima închiriere"):
            self.assertIsNone(sanitize_canonical_fill(CanonicalFill(year_built=junk)).year_built, junk)

    def test_keeps_a_four_digit_year(self):
        self.assertEqual(sanitize_canonical_fill(CanonicalFill(year_built="1982")).year_built, "1982")

    def test_drops_a_floor_that_is_neither_a_number_nor_a_named_level(self):
        for junk in ("etaj imtermediar", "retras", "un nivel", "1/11 sau 7/11", "prima închiriere"):
            self.assertIsNone(sanitize_canonical_fill(CanonicalFill(floor=junk)).floor, junk)

    def test_keeps_numeric_and_named_floors(self):
        for good in ("3", "Parter", "Demisol", "Mansarda", "subsol"):
            self.assertEqual(sanitize_canonical_fill(CanonicalFill(floor=good)).floor, good)

    def test_trims_surrounding_whitespace_rather_than_rejecting(self):
        self.assertEqual(sanitize_canonical_fill(CanonicalFill(floor=" Parter ")).floor, "Parter")

    def test_drops_an_impossible_area(self):
        self.assertIsNone(sanitize_canonical_fill(CanonicalFill(area_sqm=3000)).area_sqm)
        self.assertIsNone(sanitize_canonical_fill(CanonicalFill(area_sqm=0)).area_sqm)

    def test_keeps_a_plausible_area_and_the_rooms_enum(self):
        cleaned = sanitize_canonical_fill(CanonicalFill(area_sqm=55, rooms="2"))
        self.assertEqual((cleaned.area_sqm, cleaned.rooms), (55.0, "2"))

    def test_leaves_the_original_untouched(self):
        original = CanonicalFill(year_built="bloc nou")
        sanitize_canonical_fill(original)
        self.assertEqual(original.year_built, "bloc nou")

    def test_a_clean_result_survives_unchanged(self):
        fill = CanonicalFill(rooms="3", area_sqm=70, floor="2", total_floors="4", year_built="2017")
        self.assertEqual(sanitize_canonical_fill(fill).model_dump(), fill.model_dump())
