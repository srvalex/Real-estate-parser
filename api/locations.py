"""
api/locations.py
─────────────────
Neighbourhood -> sector lookup, scoped by city (GEO_EXPANSION_PLAN.md
Phase 0/3). `sector` is only a real concept for București today — the other
cities in api/data/cities.json have no sector layer and always resolve to
"". The lookup is deliberately keyed by (city, neighbourhood), not
neighbourhood alone: confirmed live 2026-08-30 that neighbourhood names
collide across cities ("Dacia", "Aviatiei", "Cantemir", "Tudor Vladimirescu"
all exist in both București and Iași; "Centru" exists in both Cluj-Napoca
and Iași) — a city-blind lookup would silently mislabel one city's listing
with another city's sector.
"""
import json
import os
import re
from functools import lru_cache

_CITIES_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cities.json")

# Some listings name their sector directly instead of a neighbourhood —
# "Sectorul 3", "Sector 3", "sectorul 3". Confirmed live 2026-09-08: 167
# available Bucharest listings carry one of these as their `district`, and
# a neighbourhood-only lookup dropped every one of them out of the sector
# charts even though the row states its sector unambiguously.
_SELF_DECLARED_SECTOR = re.compile(r"^\s*sector(?:ul)?\s*([1-6])\s*$", re.IGNORECASE)


@lru_cache(maxsize=1)
def _cities() -> dict:
    with open(_CITIES_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _sector_by_city_neighborhood() -> dict:
    result: dict[tuple[str, str], str] = {}
    for city, value in _cities().items():
        if isinstance(value, dict):  # sectored city (e.g. București) — flat cities (a list) have no sector
            for sector, neighborhoods in value.items():
                for n in neighborhoods:
                    result[(city, n)] = sector
    return result


def known_cities() -> list[str]:
    """Every city in api/data/cities.json, alphabetically. The analytics
    service validates its `city` param against this so an arbitrary string
    can't be pushed into a Supabase filter."""
    return sorted(_cities().keys())


def city_has_sectors(city: str) -> bool:
    """True only for cities with a sector layer (București today). Analytics
    uses this to tell "this listing's sector is missing" apart from "this
    city has no sectors at all" — without it, every Cluj and Iași listing
    would be reported as an unattributed Bucharest-style gap."""
    return isinstance(_cities().get(city), dict)


def sector_for(city: str, neighborhood: str) -> str:
    """Best-effort lookup — "" when the city has no sector layer or the
    neighbourhood isn't in the known list, rather than raising.

    A `neighborhood` that names a sector outright ("Sectorul 3") resolves to
    that sector: the row is already telling us the answer, and refusing it
    for not being a neighbourhood name only loses data.
    """
    if not city_has_sectors(city):
        return ""
    direct = _SELF_DECLARED_SECTOR.match(neighborhood or "")
    if direct:
        return f"Sector {direct.group(1)}"
    return _sector_by_city_neighborhood().get((city, neighborhood), "")
