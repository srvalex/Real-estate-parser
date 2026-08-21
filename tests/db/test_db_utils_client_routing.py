"""
Tests for the service-role / anon client split in db_utils.py.

Before this split, every function — including the ones only the public
Streamlit app calls — used the service_role client (full read/write,
bypasses Row Level Security). A leaked Streamlit env var would have handed
out full read/write/delete on the whole table. Fix: Streamlit-facing reads
go through get_anon_client() (constrained by the RLS policy in
scripts/supabase_schema.sql), backend/crawler writes keep using
get_client() (service_role).

These tests lock in two things: the client-factory logic itself, and —
more importantly — which of the two clients each individual function
actually uses. That second part is the real security property: a future
edit that quietly changes one Streamlit-facing function back to
get_client() would reintroduce the vulnerability, and these tests catch
that at the function level, not just in the factory.
"""
import unittest
from unittest.mock import patch, MagicMock

import db_utils


class ClientFactoryTests(unittest.TestCase):
    def setUp(self):
        db_utils._client = None
        db_utils._anon_client = None
        db_utils._warned_anon_fallback = False

    def tearDown(self):
        db_utils._client = None
        db_utils._anon_client = None
        db_utils._warned_anon_fallback = False

    def test_get_client_uses_service_role_key(self):
        with patch.object(db_utils, "SUPABASE_URL", "https://x.supabase.co"), \
             patch.object(db_utils, "SUPABASE_KEY", "service-role-key"), \
             patch.object(db_utils, "create_client") as mock_create:
            mock_create.return_value = MagicMock()
            db_utils.get_client()
        mock_create.assert_called_once_with("https://x.supabase.co", "service-role-key")

    def test_get_anon_client_uses_anon_key_when_set(self):
        with patch.object(db_utils, "SUPABASE_URL", "https://x.supabase.co"), \
             patch.object(db_utils, "SUPABASE_KEY", "service-role-key"), \
             patch.object(db_utils, "SUPABASE_ANON_KEY", "anon-key"), \
             patch.object(db_utils, "create_client") as mock_create:
            mock_create.return_value = MagicMock()
            db_utils.get_anon_client()
        mock_create.assert_called_once_with("https://x.supabase.co", "anon-key")

    def test_get_anon_client_falls_back_to_service_role_key_with_warning(self):
        """Fallback must exist (so nothing breaks before RLS is configured)
        but must be loud about it — silent fallback would hide exactly the
        misconfiguration this split exists to prevent."""
        with patch.object(db_utils, "SUPABASE_URL", "https://x.supabase.co"), \
             patch.object(db_utils, "SUPABASE_KEY", "service-role-key"), \
             patch.object(db_utils, "SUPABASE_ANON_KEY", ""), \
             patch.object(db_utils, "create_client") as mock_create, \
             patch("builtins.print") as mock_print:
            mock_create.return_value = MagicMock()
            db_utils.get_anon_client()
        mock_create.assert_called_once_with("https://x.supabase.co", "service-role-key")
        self.assertTrue(
            any("SUPABASE_ANON_KEY not set" in str(call) for call in mock_print.call_args_list),
            "Expected a warning about the missing anon key to be printed",
        )

    def test_get_client_and_get_anon_client_are_independent_singletons(self):
        with patch.object(db_utils, "SUPABASE_URL", "https://x.supabase.co"), \
             patch.object(db_utils, "SUPABASE_KEY", "service-role-key"), \
             patch.object(db_utils, "SUPABASE_ANON_KEY", "anon-key"), \
             patch.object(db_utils, "create_client", side_effect=lambda url, key: MagicMock()):
            service_client = db_utils.get_client()
            anon_client = db_utils.get_anon_client()
        self.assertIsNot(service_client, anon_client)


class ReadFunctionsUseAnonClientTests(unittest.TestCase):
    """Every function the Streamlit app calls must go through
    get_anon_client() — never get_client()."""

    def setUp(self):
        self.anon_client = MagicMock()
        self.service_client = MagicMock()
        self._anon_patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self._service_patch = patch.object(db_utils, "get_client", return_value=self.service_client)
        self.mock_anon = self._anon_patch.start()
        self.mock_service = self._service_patch.start()
        self.addCleanup(self._anon_patch.stop)
        self.addCleanup(self._service_patch.stop)

    def test_query_listings_by_district_uses_anon_client(self):
        table = self.anon_client.table.return_value
        table.select.return_value = table
        table.in_.return_value = table
        table.eq.return_value = table
        table.execute.return_value = MagicMock(data=[])

        db_utils.query_listings_by_district(["Floreasca"])

        self.mock_anon.assert_called()
        self.mock_service.assert_not_called()

    def test_search_by_text_vibe_uses_anon_client(self):
        self.anon_client.rpc.return_value.execute.return_value = MagicMock(data=[])

        db_utils.search_by_text_vibe([0.1] * 384)

        self.mock_anon.assert_called()
        self.mock_service.assert_not_called()

    def test_search_by_image_embedding_uses_anon_client(self):
        self.anon_client.rpc.return_value.execute.return_value = MagicMock(data=[])

        db_utils.search_by_image_embedding([0.1] * 512)

        self.mock_anon.assert_called()
        self.mock_service.assert_not_called()

    def test_get_price_stats_uses_anon_client(self):
        table = self.anon_client.table.return_value
        table.select.return_value = table
        table.eq.return_value = table
        table.range.return_value = table
        table.execute.return_value = MagicMock(data=[])

        db_utils.get_price_stats()

        self.mock_anon.assert_called()
        self.mock_service.assert_not_called()

    def test_fetch_analytics_data_uses_anon_client(self):
        table = self.anon_client.table.return_value
        table.select.return_value = table
        table.eq.return_value = table
        table.not_.is_.return_value = table
        table.range.return_value = table
        table.execute.return_value = MagicMock(data=[])

        db_utils.fetch_analytics_data()

        self.mock_anon.assert_called()
        self.mock_service.assert_not_called()


class WriteFunctionsUseServiceRoleClientTests(unittest.TestCase):
    """Backend/crawler-only functions must keep using the service-role
    client. RLS would make an anon-key write fail anyway once configured,
    but this locks in the intent directly rather than relying on that."""

    def setUp(self):
        self.anon_client = MagicMock()
        self.service_client = MagicMock()
        self._anon_patch = patch.object(db_utils, "get_anon_client", return_value=self.anon_client)
        self._service_patch = patch.object(db_utils, "get_client", return_value=self.service_client)
        self.mock_anon = self._anon_patch.start()
        self.mock_service = self._service_patch.start()
        self.addCleanup(self._anon_patch.stop)
        self.addCleanup(self._service_patch.stop)

    def test_save_to_db_uses_service_client(self):
        db_utils.save_to_db([{"url": "https://x"}])

        self.mock_service.assert_called()
        self.mock_anon.assert_not_called()

    def test_get_all_db_urls_uses_service_client(self):
        table = self.service_client.table.return_value
        table.select.return_value = table
        table.range.return_value = table
        table.execute.return_value = MagicMock(data=[])

        db_utils.get_all_db_urls()

        self.mock_service.assert_called()
        self.mock_anon.assert_not_called()

    def test_batch_update_availability_uses_service_client(self):
        db_utils.batch_update_availability([{"url": "https://x", "is_available": 0}])

        self.mock_service.assert_called()
        self.mock_anon.assert_not_called()

    def test_get_listings_for_availability_check_uses_service_client(self):
        table = self.service_client.table.return_value
        table.select.return_value = table
        table.or_.return_value = table
        table.eq.return_value = table
        table.range.return_value = table
        table.execute.return_value = MagicMock(data=[])

        db_utils.get_listings_for_availability_check()

        self.mock_service.assert_called()
        self.mock_anon.assert_not_called()

    def test_update_image_embedding_uses_service_client(self):
        db_utils.update_image_embedding("https://x", [0.1] * 512)

        self.mock_service.assert_called()
        self.mock_anon.assert_not_called()

    def test_get_listings_missing_text_embedding_uses_service_client(self):
        table = self.service_client.table.return_value
        table.select.return_value = table
        table.is_.return_value = table
        table.limit.return_value = table
        table.execute.return_value = MagicMock(data=[])

        db_utils.get_listings_missing_text_embedding()

        self.mock_service.assert_called()
        self.mock_anon.assert_not_called()

    def test_get_listings_missing_image_embedding_uses_service_client(self):
        table = self.service_client.table.return_value
        table.select.return_value = table
        table.eq.return_value = table
        table.not_.is_.return_value = table
        table.is_.return_value = table
        table.order.return_value = table
        table.limit.return_value = table
        table.execute.return_value = MagicMock(data=[])

        db_utils.get_listings_missing_image_embedding()

        self.mock_service.assert_called()
        self.mock_anon.assert_not_called()


if __name__ == "__main__":
    unittest.main()
