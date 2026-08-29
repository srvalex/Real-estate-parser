"""
build_filter_plan is the pure translation from a validated ListingQuery
into primitive filter operations — no I/O, so these run without a DB or
network. Canonical fields must become plain SimpleFilters on real
`listings` columns; every `extras` filter must become an OrFilter (see
query_model._translate_extra_filter's docstring for why: postgrest-py's
`.filter()` mangles any column string containing `:`, which the `::numeric`
cast on number fields always does), never a raw SimpleFilter, so
apply_filter_plan always routes it through `.or_()` instead.
"""
import unittest

from query_model import ExtraFilter, ListingQuery, OrFilter, SimpleFilter, build_filter_plan


class CanonicalFieldTests(unittest.TestCase):
    def test_empty_query_has_only_the_default_availability_filter(self):
        plan = build_filter_plan(ListingQuery())
        self.assertEqual(plan.filters, (SimpleFilter("is_available", "eq", 1),))
        self.assertEqual(plan.or_groups, ())
        self.assertEqual(plan.limit, 50)

    def test_price_range_maps_to_gte_and_lte_on_price_numeric(self):
        plan = build_filter_plan(ListingQuery(price_min=300, price_max=800, is_available=None))
        self.assertIn(SimpleFilter("price_numeric", "gte", 300), plan.filters)
        self.assertIn(SimpleFilter("price_numeric", "lte", 800), plan.filters)

    def test_rooms_and_district_and_property_type_map_to_in_filters(self):
        plan = build_filter_plan(ListingQuery(
            rooms=["2", "3"], district=["Colentina"], property_type=["Apartament"],
            is_available=None,
        ))
        self.assertIn(SimpleFilter("rooms", "in", ("2", "3")), plan.filters)
        self.assertIn(SimpleFilter("district", "in", ("Colentina",)), plan.filters)
        self.assertIn(SimpleFilter("property_type", "in", ("Apartament",)), plan.filters)

    def test_is_available_false_maps_to_eq_zero(self):
        plan = build_filter_plan(ListingQuery(is_available=False))
        self.assertIn(SimpleFilter("is_available", "eq", 0), plan.filters)

    def test_is_available_none_omits_the_filter_entirely(self):
        plan = build_filter_plan(ListingQuery(is_available=None))
        self.assertEqual(plan.filters, ())


class ExtrasFieldTests(unittest.TestCase):
    def test_scalar_extras_filter_becomes_an_or_group_not_a_plain_filter(self):
        plan = build_filter_plan(ListingQuery(
            is_available=None,
            extras=[ExtraFilter(key="heating_type", op="eq", value="gas")],
        ))
        self.assertEqual(plan.filters, ())
        self.assertEqual(len(plan.or_groups), 1)
        group = plan.or_groups[0]
        self.assertIsInstance(group, OrFilter)
        self.assertEqual(len(group.conditions), 1)
        cond = group.conditions[0]
        self.assertEqual(cond.column, "extras->attributes->>heating")
        self.assertEqual(cond.op, "eq")
        self.assertEqual(cond.value, "gas")

    def test_array_extras_filter_keeps_jsonb_path_and_json_encodes_value(self):
        plan = build_filter_plan(ListingQuery(
            is_available=None,
            extras=[ExtraFilter(key="amenities", op="contains", value="lift")],
        ))
        cond = plan.or_groups[0].conditions[0]
        # no `->>` on the leaf key — must stay jsonb for `cs` to work
        self.assertEqual(cond.column, "extras->attributes->extras_types")
        self.assertEqual(cond.op, "cs")
        self.assertEqual(cond.value, '["lift"]')

    def test_number_extras_filter_appends_numeric_cast(self):
        plan = build_filter_plan(ListingQuery(
            is_available=None,
            extras=[ExtraFilter(key="latitude", op="gte", value=44.4)],
        ))
        cond = plan.or_groups[0].conditions[0]
        self.assertEqual(cond.column, "extras->location->coordinates->>latitude::numeric")

    def test_multiple_extras_filters_each_become_their_own_or_group(self):
        plan = build_filter_plan(ListingQuery(
            is_available=None,
            extras=[
                ExtraFilter(key="heating_type", op="eq", value="gas"),
                ExtraFilter(key="amenities", op="contains", value="lift"),
            ],
        ))
        self.assertEqual(len(plan.or_groups), 2)


if __name__ == "__main__":
    unittest.main()
