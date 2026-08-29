"""
apply_filter_plan wires a FilterPlan onto a real postgrest-py query
builder. These tests build a real Supabase client against a fake
https://example.supabase.co project — client construction and filter
chaining never make a network call (only .execute() would), so this
inspects the actual URL params PostgREST would receive without hitting a
network.

The multi-platform-OR case is exercised by monkeypatching a throwaway
EXTRAS_REGISTRY entry rather than an existing one, since today only Storia
has any real extras paths registered (see query_model.py's module
docstring) — this test is what proves the OR-across-platforms branch is
correct ahead of a platform's path actually being added.
"""
import unittest

from supabase import create_client

import query_model as qm
from query_model import ExtraFilter, ExtrasField, ListingQuery, apply_filter_plan, build_filter_plan


def _params(builder):
    return dict(builder.request.params.multi_items())


def _multi_params(builder):
    return sorted(builder.request.params.multi_items())


def _builder():
    client = create_client("https://example.supabase.co", "dummy-key")
    return client.table("listings").select("*")


class CanonicalFilterWiringTests(unittest.TestCase):
    def test_plain_columns_use_filter_or_in_not_or_clause(self):
        plan = build_filter_plan(ListingQuery(price_max=800, district=["Colentina"]))
        final = apply_filter_plan(_builder(), plan)
        params = _params(final)
        self.assertEqual(params["price_numeric"], "lte.800.0")
        self.assertEqual(params["district"], "in.(Colentina)")
        self.assertNotIn("or", params)

    def test_limit_is_always_applied(self):
        plan = build_filter_plan(ListingQuery(limit=17))
        final = apply_filter_plan(_builder(), plan)
        self.assertEqual(_params(final)["limit"], "17")


class ExtrasFilterWiringTests(unittest.TestCase):
    def test_single_platform_extras_filter_goes_through_or_clause(self):
        plan = build_filter_plan(ListingQuery(
            is_available=None,
            extras=[ExtraFilter(key="heating_type", op="eq", value="gas")],
        ))
        final = apply_filter_plan(_builder(), plan)
        pairs = _multi_params(final)
        or_values = [v for k, v in pairs if k == "or"]
        self.assertEqual(or_values, ['(extras->attributes->>heating.eq."gas")'])

    def test_this_column_is_never_sent_through_the_plain_filter_param(self):
        # Regression guard: extras->...->>x::numeric contains ':', which
        # postgrest-py's sanitize_param double-quotes into a broken literal
        # column name when passed through .filter()/.in_() instead of
        # .or_(). Confirms the numeric-cast column never appears as a
        # top-level param key.
        plan = build_filter_plan(ListingQuery(
            is_available=None,
            extras=[ExtraFilter(key="latitude", op="gte", value=44.4)],
        ))
        final = apply_filter_plan(_builder(), plan)
        for key, _ in final.request.params.multi_items():
            self.assertNotIn("::numeric", key)


class MultiPlatformOrEscapingTests(unittest.TestCase):
    def setUp(self):
        qm.EXTRAS_REGISTRY["_test_multi_platform"] = ExtrasField(
            platform_paths={
                "Storia": ("attributes", "heating"),
                "Imobiliare.ro": ("heatingType",),
            },
            value_type="string",
            description="throwaway field for OR-across-platforms coverage",
        )

    def tearDown(self):
        del qm.EXTRAS_REGISTRY["_test_multi_platform"]

    def _multi_filter(self, value):
        f = ExtraFilter.model_construct(key="_test_multi_platform", op="eq", value=value)
        group = qm._translate_extra_filter(f)
        plan = qm.FilterPlan(filters=(), or_groups=(group,), limit=50)
        return apply_filter_plan(_builder(), plan)

    def test_both_platform_paths_appear_in_a_single_or_group(self):
        final = self._multi_filter("gas")
        or_values = [v for k, v in final.request.params.multi_items() if k == "or"]
        self.assertEqual(len(or_values), 1)
        self.assertIn("extras->attributes->>heating.eq.", or_values[0])
        self.assertIn("extras->>heatingType.eq.", or_values[0])

    def test_a_value_shaped_like_filter_syntax_cannot_inject_a_new_clause(self):
        final = self._multi_filter("evil,or(is_available.eq.0)")
        keys = [k for k, _ in final.request.params.multi_items()]
        # the only "or" param present must be the one this function built —
        # an injected value must not add a second, independent "or" filter
        or_values = [v for k, v in final.request.params.multi_items() if k == "or"]
        self.assertEqual(len(or_values), 1)
        self.assertNotIn("is_available", keys)


if __name__ == "__main__":
    unittest.main()
