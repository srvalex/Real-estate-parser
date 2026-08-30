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
from functools import lru_cache

_CITIES_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cities.json")


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


def sector_for(city: str, neighborhood: str) -> str:
    """Best-effort lookup — "" when the city has no sector layer or the
    neighbourhood isn't in the known list, rather than raising."""
    return _sector_by_city_neighborhood().get((city, neighborhood), "")
