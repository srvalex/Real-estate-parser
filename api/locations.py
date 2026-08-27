"""
api/locations.py
─────────────────
Neighbourhood → sector lookup. `sector` isn't a listings table column — it's
purely a client-facing grouping derived from streamlit_interface/districts.json
(the same file the crawler-side app already uses; mock_ui keeps its own
in-sync copy at lib/data/districts.json for the location search bar).
"""
import json
import os
from functools import lru_cache

_DISTRICTS_JSON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "streamlit_interface", "districts.json"
)


@lru_cache(maxsize=1)
def _sector_by_neighborhood() -> dict[str, str]:
    with open(_DISTRICTS_JSON, "r", encoding="utf-8") as f:
        districts: dict[str, list[str]] = json.load(f)
    return {
        neighborhood: sector
        for sector, neighborhoods in districts.items()
        for neighborhood in neighborhoods
    }


def sector_for(neighborhood: str) -> str:
    """Best-effort lookup — returns "" for a neighbourhood not found in
    districts.json rather than raising, since a listing's district string
    not matching the known list exactly (see BUGS.md #4, a related risk for
    a different column) shouldn't break the whole response."""
    return _sector_by_neighborhood().get(neighborhood, "")
