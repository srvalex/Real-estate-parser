"""
Tests for db_utils._strip_rest_suffix.

Bug: Supabase's current dashboard hands out a "Data API URL" that already
includes the /rest/v1 suffix (e.g. "https://xxxx.supabase.co/rest/v1/"),
under the newer SUPABASE_DATA_API/SUPABASE_SECRET_API_KEY/SUPABASE_PUBLISH_KEY
naming that replaced the legacy SUPABASE_URL/SUPABASE_KEY/SUPABASE_ANON_KEY
names. supabase-py's create_client() appends /rest/v1 itself, so using that
URL as-is doubles the path and every request fails with PostgREST's
PGRST125 ("Invalid path specified in request URL") — confirmed live against
the real project this session before this fix.
"""
import unittest

import db_utils


class StripRestSuffixTests(unittest.TestCase):
    def test_strips_rest_v1_suffix_with_trailing_slash(self):
        self.assertEqual(
            db_utils._strip_rest_suffix("https://xxxx.supabase.co/rest/v1/"),
            "https://xxxx.supabase.co",
        )

    def test_strips_rest_v1_suffix_without_trailing_slash(self):
        self.assertEqual(
            db_utils._strip_rest_suffix("https://xxxx.supabase.co/rest/v1"),
            "https://xxxx.supabase.co",
        )

    def test_bare_project_url_is_unchanged(self):
        self.assertEqual(
            db_utils._strip_rest_suffix("https://xxxx.supabase.co"),
            "https://xxxx.supabase.co",
        )

    def test_bare_project_url_with_trailing_slash_has_slash_stripped(self):
        self.assertEqual(
            db_utils._strip_rest_suffix("https://xxxx.supabase.co/"),
            "https://xxxx.supabase.co",
        )

    def test_empty_string_is_unchanged(self):
        self.assertEqual(db_utils._strip_rest_suffix(""), "")


if __name__ == "__main__":
    unittest.main()
