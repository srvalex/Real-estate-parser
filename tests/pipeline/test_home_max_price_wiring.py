"""
Test for BUGS.md #2: streamlit_interface/components/home.py used to call
query_listings_by_district(all_districts) with no max_price_eur, so the
currency-aware server-side price filter (db_utils.query_listings_by_district's
max_price_eur param, already unit-tested in
tests/db/test_query_listings_by_district_price_filter.py) existed but was
never actually used by the live app — every search fetched every row for the
selected districts regardless of the user's price cap, filtering client-side
only, after the fact.

This drives streamlit_interface/components/home.py's render_home() through a
full "user fills the form, clicks search" pass with `streamlit` mocked out
(no real UI, no network), and asserts the price cap the user entered is
forwarded to query_listings_by_district. It's a heavier test than a plain
function test because render_home() is a single large Streamlit
script-function with no smaller seam to test the wiring at.

home.py is loaded exactly once at module import time (not per test): it pulls
in the real components.results -> nlp_filters -> spacy -> torch chain, and
re-running importlib's module_from_spec/exec_module on the same file a second
time in the same process re-executes that whole chain from scratch, which
torch's C extension does not tolerate (raises "module functions cannot set
METH_CLASS or METH_STATIC" on the second load). Loading once and reusing the
same mock `streamlit` reference (reconfigured per test) avoids that entirely.
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STREAMLIT_INTERFACE = _REPO_ROOT / "streamlit_interface"
_HOME_PATH = _STREAMLIT_INTERFACE / "components" / "home.py"


class _StopRender(Exception):
    """Stands in for streamlit's internal StopException raised by st.stop()."""


def _configure_mock_streamlit(st: MagicMock, max_price: int) -> None:
    st.reset_mock()

    def _columns(spec):
        n = spec if isinstance(spec, int) else len(spec)
        return [MagicMock() for _ in range(n)]

    st.columns.side_effect = _columns
    st.text_area.return_value = ""          # empty vibe -> skips NLP extraction entirely
    st.number_input.side_effect = [max_price, 0, 0]  # max_price, min_sqm, max_sqm
    st.selectbox.return_value = "Orice"        # rooms filter
    st.multiselect.side_effect = [
        ["Apartament"],   # property_types
        ["Floreasca"],    # this district's selected neighbourhoods
    ]
    st.checkbox.return_value = False           # "select all" toggle for the district
    st.toggle.return_value = False             # proximity toggle
    st.button.return_value = True              # "Caută locuințe" clicked
    st.stop.side_effect = _StopRender


def _load_home_module():
    for sub in ("pipeline",):
        p = str(_STREAMLIT_INTERFACE / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    if str(_STREAMLIT_INTERFACE) not in sys.path:
        sys.path.insert(0, str(_STREAMLIT_INTERFACE))
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

    mock_st = MagicMock()
    with patch.dict(sys.modules, {"streamlit": mock_st}):
        spec = importlib.util.spec_from_file_location("home_under_test", _HOME_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, mock_st


_home, _mock_st = _load_home_module()


class MaxPriceWiringTests(unittest.TestCase):
    def test_max_price_entered_by_the_user_is_forwarded_to_the_district_query(self):
        _configure_mock_streamlit(_mock_st, max_price=500)

        with patch.object(os.path, "isdir", return_value=False), \
             patch("db_utils.query_listings_by_district", return_value=[]) as mock_query, \
             patch.dict(sys.modules, {"streamlit": _mock_st}), \
             self.assertRaises(_StopRender):
            _home.render_home(
                districts={"Sector 1": ["Floreasca", "Dorobanti"]},
                proximity={},
                server_url=None,
            )

        mock_query.assert_called_once()
        args, kwargs = mock_query.call_args
        self.assertEqual(args[0], ["Floreasca"])
        self.assertEqual(kwargs.get("max_price_eur"), 500)

    def test_zero_max_price_no_limit_is_still_forwarded_as_zero(self):
        """0 is this app's existing 'no limit' convention (also honoured
        server-side by query_listings_by_district) -- must be passed through
        as 0, not silently omitted or turned into None."""
        _configure_mock_streamlit(_mock_st, max_price=0)

        with patch.object(os.path, "isdir", return_value=False), \
             patch("db_utils.query_listings_by_district", return_value=[]) as mock_query, \
             patch.dict(sys.modules, {"streamlit": _mock_st}), \
             self.assertRaises(_StopRender):
            _home.render_home(
                districts={"Sector 1": ["Floreasca"]},
                proximity={},
                server_url=None,
            )

        self.assertEqual(mock_query.call_args.kwargs.get("max_price_eur"), 0)


if __name__ == "__main__":
    unittest.main()
