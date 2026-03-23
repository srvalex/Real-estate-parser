"""
nlp_filters.py
──────────────
Local spaCy-based filter extractor for Romanian real-estate prompts.
Replaces the remote Ollama parse_vibe round-trip with instant local NLP.

Usage:
    from nlp_filters import extract_filters, get_olx_keywords

    filters = extract_filters("Caut 2 camere langa metrou, pet-friendly")
    # → {"ROOM_COUNT": "2", "HAS_METRO": True, "PET_FRIENDLY": True}

    slugs = get_olx_keywords(filters)
    # → ["metrou", "pet-friendly"]
    # Append to OLX URL: /q-metrou-pet-friendly/
"""

import spacy

nlp = spacy.load("ro_core_news_sm")

# ── Taxonomy: Romanian lemma → internal filter key ───────────────────────
REAL_ESTATE_TAXONOMY = {
    "metrou":              "HAS_METRO",
    "renovat":             "CONDITION_RENOVATED",
    "modern":              "STYLE_MODERN",
    "luminos":             "FEAT_BRIGHT",
    "centrală":            "HAS_HEATING_UNIT",
    "centrala":            "HAS_HEATING_UNIT",
    "parcare":             "HAS_PARKING",
    "garaj":               "HAS_PARKING",
    "balcon":              "HAS_BALCONY",
    "pet-friendly":        "PET_FRIENDLY",
    "animal":              "PET_FRIENDLY",   # "animal de companie"
    "mobilat":             "FURNISHED",
    "nemobilat":           "UNFURNISHED",
    "liniștit":            "FEAT_QUIET",

}

# ── OLX URL slug mapping: filter key → keyword appended to /q-... path ───
FILTER_TO_OLX_SLUG = {
    "HAS_METRO":           "metrou",
    "HAS_PARKING":         "parcare",
    "PET_FRIENDLY":        "pet-friendly",
    "HAS_HEATING_UNIT":    "centrala",
    "HAS_BALCONY":         "balcon",
    "CONDITION_RENOVATED": "renovat",
    "STYLE_MODERN":        "modern",
    "FURNISHED":           "mobilat",
    "FEAT_QUIET":          "linistit",
}


def extract_filters(text: str) -> dict:
    """
    Run spaCy NLP on the user prompt and return a dict of detected filters.

    Returns:
        e.g. {"ROOM_COUNT": "2", "LOCATION_SECTOR": "4", "HAS_METRO": True}
    """
    doc = nlp(text.lower())
    found = {}

    # 1. Room count — numeric token whose syntactic head lemma is "cameră"
    for token in doc:
        if token.like_num and token.head.lemma_ in ("cameră", "camera", "camere"):
            found["ROOM_COUNT"] = token.text
            break

    # 2. Sector number — "sectorul" / "sector" followed by a digit
    for i, token in enumerate(doc):
        if token.lemma_ in ("sector", "sectorul") and i + 1 < len(doc):
            nxt = doc[i + 1]
            if nxt.like_num:
                found["LOCATION_SECTOR"] = nxt.text
                break

    # 3. Keyword taxonomy via lemmatization
    for token in doc:
        lemma = token.lemma_
        if lemma in REAL_ESTATE_TAXONOMY:
            key = REAL_ESTATE_TAXONOMY[lemma]
            if key not in found:          # don't overwrite specific values
                found[key] = True

    # 4. Exact substring check for multi-word phrases (e.g. "pet-friendly")
    lowered = text.lower()
    multi_word = {
        "pet-friendly":        "PET_FRIENDLY",
        "animal de companie":  "PET_FRIENDLY",
        "lângă metrou":        "HAS_METRO",
        "aproape de metrou":   "HAS_METRO",
        "loc de parcare":      "HAS_PARKING",
    }
    for phrase, key in multi_word.items():
        if phrase in lowered and key not in found:
            found[key] = True

    return found


def get_olx_keywords(filters: dict) -> list[str]:
    """
    Convert a filters dict into a list of OLX URL slug keywords.

    Example:
        {"HAS_METRO": True, "PET_FRIENDLY": True} → ["metrou", "pet-friendly"]

    These are joined with "-" and inserted into the OLX URL path:
        /q-metrou-pet-friendly/
    """
    return [
        FILTER_TO_OLX_SLUG[key]
        for key in filters
        if key in FILTER_TO_OLX_SLUG and filters[key]
    ]


# ── Quick self-test ───────────────────────────────────────────────────────
if __name__ == "__main__":
    test_prompt = (
        "Caut apartament cu 2 camere in sectorul 4, aproape de metrou. "
        "Vreau sa fie ceva modern si renovat. Pet-friendly si cu parcare."
    )
    f = extract_filters(test_prompt)
    print("Filters :", f)
    print("OLX slugs:", get_olx_keywords(f))
