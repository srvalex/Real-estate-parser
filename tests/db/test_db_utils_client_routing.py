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
import re
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import db_utils

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STREAMLIT_INTERFACE = _REPO_ROOT / "streamlit_interface"


class ClientFactoryTests(unittest.TestCase):
    def setUp(self):
        db_utils._client = None
        db_utils._anon_client = None

    def tearDown(self):
        db_utils._client = None
        db_utils._anon_client = None

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

    def test_get_anon_client_raises_when_anon_key_not_set(self):
        """No more silent fallback to the service-role key (BUGS.md #8):
        with RLS confirmed working, a missing anon key must fail loudly
        instead of quietly handing out full read/write/delete."""
        with patch.object(db_utils, "SUPABASE_URL", "https://x.supabase.co"), \
             patch.object(db_utils, "SUPABASE_KEY", "service-role-key"), \
             patch.object(db_utils, "SUPABASE_ANON_KEY", ""), \
             patch.object(db_utils, "create_client") as mock_create:
            with self.assertRaises(RuntimeError):
                db_utils.get_anon_client()
        mock_create.assert_not_called()

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


class StreamlitNeverUsesServiceRoleClientTests(unittest.TestCase):
    """BUGS.md #8's other half: it's not enough for db_utils's own functions
    to route correctly (ReadFunctionsUseAnonClientTests above) — nothing
    stops a future streamlit_interface/ change from importing get_client()
    directly and bypassing that boundary entirely. This scans every source
    file under streamlit_interface/ for a literal get_client( call so that
    regression fails loudly here instead of shipping to the public surface
    silently."""

    _GET_CLIENT_CALL = re.compile(r"(?<!\w)get_client\s*\(")

    def test_no_streamlit_source_file_calls_get_client(self):
        offenders = []
        for path in _STREAMLIT_INTERFACE.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if self._GET_CLIENT_CALL.search(line):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}")

        self.assertEqual(
            offenders, [],
            "streamlit_interface/ must never call the service-role get_client() "
            "directly -- use get_anon_client() instead:\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
