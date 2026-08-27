"""
Direct tests for pipeline_core.apply_filters — this had zero test coverage
anywhere before this relocation (BUGS.md #10). Constructs its own
_price_num/_rooms_num helper columns inline (normally produced by
pipeline_core.prepare_dataframe) so each filter can be exercised in
isolation without depending on that other function's behavior.
"""
import unittest

import pandas as pd

import pipeline_core


def _df(rows):
    return pd.DataFrame(rows)


class MaxPriceFilterTests(unittest.TestCase):
    def test_zero_or_missing_max_price_imposes_no_constraint(self):
        df = _df([{"_price_num": 100}, {"_price_num": 5000}])
        result = pipeline_core.apply_filters(df, max_price=0, sel_rooms="Orice")
        self.assertEqual(len(result), 2)

    def test_excludes_rows_over_budget(self):
        df = _df([{"_price_num": 400}, {"_price_num": 900}])
        result = pipeline_core.apply_filters(df, max_price=500, sel_rooms="Orice")
        self.assertEqual(result["_price_num"].tolist(), [400])

    def test_never_penalizes_missing_price(self):
        df = _df([{"_price_num": None}, {"_price_num": 900}])
        result = pipeline_core.apply_filters(df, max_price=500, sel_rooms="Orice")
        self.assertEqual(len(result), 1)
        self.assertTrue(result["_price_num"].isna().all())


class RoomsFilterTests(unittest.TestCase):
    def test_orice_imposes_no_constraint(self):
        df = _df([{"_rooms_num": 1}, {"_rooms_num": 3}])
        result = pipeline_core.apply_filters(df, max_price=0, sel_rooms="Orice")
        self.assertEqual(len(result), 2)

    def test_exact_room_count_match(self):
        df = _df([{"_rooms_num": 1}, {"_rooms_num": 2}])
        result = pipeline_core.apply_filters(df, max_price=0, sel_rooms="2")
        self.assertEqual(result["_rooms_num"].tolist(), [2])

    def test_five_plus_matches_five_and_above(self):
        df = _df([{"_rooms_num": 4}, {"_rooms_num": 5}, {"_rooms_num": 6}])
        result = pipeline_core.apply_filters(df, max_price=0, sel_rooms="5+")
        self.assertEqual(sorted(result["_rooms_num"].tolist()), [5, 6])


class AreaFilterTests(unittest.TestCase):
    def test_min_and_max_sqm_together(self):
        df = _df([
            {"area_sqm": 30}, {"area_sqm": 55}, {"area_sqm": 120},
        ])
        result = pipeline_core.apply_filters(df, max_price=0, sel_rooms="Orice", min_sqm=40, max_sqm=60)
        self.assertEqual(result["area_sqm"].tolist(), [55])

    def test_never_penalizes_missing_area(self):
        df = _df([{"area_sqm": None}, {"area_sqm": 55}])
        result = pipeline_core.apply_filters(df, max_price=0, sel_rooms="Orice", min_sqm=40, max_sqm=60)
        self.assertEqual(len(result), 2)


class PropertyTypeFilterTests(unittest.TestCase):
    def test_no_types_imposes_no_constraint(self):
        df = _df([{"property_type": "Studio"}, {"property_type": "Apartament"}])
        result = pipeline_core.apply_filters(df, max_price=0, sel_rooms="Orice", property_types=None)
        self.assertEqual(len(result), 2)

    def test_filters_to_selected_types_but_keeps_unknown(self):
        df = _df([
            {"property_type": "Studio"}, {"property_type": "Apartament"}, {"property_type": None},
        ])
        result = pipeline_core.apply_filters(
            df, max_price=0, sel_rooms="Orice", property_types=["Studio"]
        )
        self.assertEqual(len(result), 2)  # Studio + the unknown-type row


class EmptyDataFrameTests(unittest.TestCase):
    def test_empty_dataframe_is_a_no_op(self):
        df = pd.DataFrame()
        result = pipeline_core.apply_filters(df, max_price=500, sel_rooms="2")
        self.assertTrue(result.empty)


if __name__ == "__main__":
    unittest.main()
