"""
ExtraFilter is the only way an LLM-extracted query can touch the `extras`
JSONB column, and it's deliberately closed: `key` must be a name from
EXTRAS_REGISTRY (never a free-form JSON path), and `op` must match that
key's declared value_type (scalar ops for scalar fields, `contains` only
for array fields). These tests lock in that both halves of the gate
actually reject bad input, since a hole here is exactly what lets an agent
construct an unintended query against a column whose shape varies by
platform (see query_model.py's module docstring).
"""
import unittest

from pydantic import ValidationError

from query_model import EXTRAS_REGISTRY, ExtraFilter


class ScalarFieldOpValidationTests(unittest.TestCase):
    def test_eq_is_valid_for_a_string_field(self):
        f = ExtraFilter(key="heating_type", op="eq", value="gas")
        self.assertEqual(f.value, "gas")

    def test_gte_is_valid_for_a_number_field(self):
        f = ExtraFilter(key="latitude", op="gte", value=44.4)
        self.assertEqual(f.value, 44.4)

    def test_contains_is_rejected_for_a_scalar_field(self):
        with self.assertRaises(ValidationError):
            ExtraFilter(key="heating_type", op="contains", value="gas")


class ArrayFieldOpValidationTests(unittest.TestCase):
    def test_contains_is_valid_for_an_array_field(self):
        f = ExtraFilter(key="amenities", op="contains", value="lift")
        self.assertEqual(f.value, "lift")

    def test_eq_is_rejected_for_an_array_field(self):
        with self.assertRaises(ValidationError):
            ExtraFilter(key="amenities", op="eq", value="lift")

    def test_gte_is_rejected_for_an_array_field(self):
        with self.assertRaises(ValidationError):
            ExtraFilter(key="security_features", op="gte", value="monitoring")


class UnknownKeyValidationTests(unittest.TestCase):
    def test_arbitrary_json_path_key_is_rejected(self):
        with self.assertRaises(ValidationError):
            ExtraFilter(key="owner.phones", op="eq", value="+40700000000")

    def test_every_registry_key_is_actually_constructible(self):
        # Catches a registry/Literal drift: every key EXTRAS_REGISTRY
        # advertises must round-trip through the model with a legal op.
        for key, spec in EXTRAS_REGISTRY.items():
            op = "contains" if spec.value_type == "array" else "eq"
            value = "x" if spec.value_type != "number" else 1.0
            ExtraFilter(key=key, op=op, value=value)


if __name__ == "__main__":
    unittest.main()
