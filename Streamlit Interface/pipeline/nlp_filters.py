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


# ── Description-level exclusion phrases (Romanian) ───────────────────────
# If a listing description contains any of these, it explicitly denies the feature.
EXCLUSION_PATTERNS = {
    "PET_FRIENDLY": [
        "nu acceptam animale", "nu acceptăm animale",
        "nu se accepta animale", "nu se acceptă animale",
        "nu se admit animale", "nu accepta animale",
        "fara animale", "fără animale",
        "animale nepermise", "animale nu sunt permise",
        "nu este pet-friendly", "nu e pet-friendly",
        "nu este pet friendly", "nu e pet friendly",
        "no pets", "nu acceptam caini", "nu acceptăm câini",
        "nu acceptam pisici", "nu acceptăm pisici",
    ],
    "HAS_PARKING": [
        "fara loc de parcare", "fără loc de parcare",
        "nu include parcare", "nu este inclusa parcarea",
        "parcare neinclusa", "parcare neinclus",
        "nu are parcare", "nu dispune de parcare",
    ],
    "HAS_BALCONY": [
        "fara balcon", "fără balcon",
        "nu are balcon", "nu dispune de balcon",
    ],
    "FURNISHED": [
        "nemobilat", "fara mobila", "fără mobilă",
        "nu este mobilat", "nu e mobilat",
    ],
    "HAS_HEATING_UNIT": [
        "fara centrala", "fără centrală",
        "nu are centrala", "nu are centrală",
        "incalzire centrala de bloc",   # district heating ≠ own boiler
    ],
}

# ── Positive confirmation phrases ─────────────────────────────────────────
# If present in description, listing explicitly confirms the feature.
CONFIRMATION_PATTERNS = {
    "PET_FRIENDLY": [
        "pet-friendly", "pet friendly", "acceptam animale",
        "acceptăm animale", "animale acceptate", "animale de companie permise",
        "acceptam catei", "acceptăm câini", "acceptam pisici",
    ],
    "HAS_PARKING": [
        "loc de parcare", "parcare inclusa", "parcare inclusă",
        "parcare proprie", "garaj inclus",
    ],
    "HAS_BALCONY": [
        "balcon", "terasa", "terasă",
    ],
    "FURNISHED": [
        "mobilat", "mobilată", "complet mobilat", "partial mobilat",
    ],
}


def apply_description_filters(df, spacy_filters: dict):
    """
    Hard-exclude listings whose descriptions explicitly deny a requested feature.
    Returns (filtered_df, excluded_count, summary_dict).

    summary_dict maps filter_key → count of listings excluded by that filter.
    """
    import pandas as pd

    if not spacy_filters or "description" not in df.columns:
        return df, 0, {}

    desc = df["description"].fillna("").str.lower()
    keep = pd.Series(True, index=df.index)
    summary = {}

    for filter_key in spacy_filters:
        patterns = EXCLUSION_PATTERNS.get(filter_key, [])
        if not patterns:
            continue
        filter_mask = pd.Series(False, index=df.index)
        for pattern in patterns:
            filter_mask |= desc.str.contains(pattern, na=False, regex=False)
        excluded = filter_mask.sum()
        if excluded:
            summary[filter_key] = int(excluded)
        keep &= ~filter_mask

    excluded_total = int((~keep).sum())
    return df[keep].reset_index(drop=True), excluded_total, summary


def extract_filters(text: str) -> dict:
    """
    Run spaCy NLP on the user prompt and return a dict of detected filters.

    Returns:
        e.g. {"ROOM_COUNT": "2", "LOCATION_SECTOR": "4", "HAS_METRO": True,
              "PROPERTY_TYPE": "Garsonieră", "AREA_MIN": 50}
    """
    import re as _re
    doc = nlp(text.lower())
    found = {}
    lowered = text.lower()

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
            if key not in found:
                found[key] = True

    # 4. Exact substring check for multi-word phrases
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

    # 5. Property type — keyword matching
    if "PROPERTY_TYPE" not in found:
        if any(w in lowered for w in ("garsonier", "studio", "garconiera", "garçonieră")):
            found["PROPERTY_TYPE"] = "Garsonieră"
        elif any(w in lowered for w in ("casă", "casa", "vilă", "vila", "duplex")):
            found["PROPERTY_TYPE"] = "Casă / Vilă"
        elif "apartament" in lowered:
            found["PROPERTY_TYPE"] = "Apartament"

    # 6. Area range — "X mp", "minim X mp", "pana la X mp", etc.
    # Minimum area: "minim/cel putin/minimum X mp"
    m = _re.search(
        r"(?:minim|cel\s+pu[tț]in|minimum|peste|mai\s+mare\s+de)\s+(\d+)\s*mp",
        lowered,
    )
    if m:
        found["AREA_MIN"] = int(m.group(1))

    # Maximum area: "maxim/pana la/cel mult X mp"
    m = _re.search(
        r"(?:maxim|p[aâ]n[aă]\s+la|cel\s+mult|sub)\s+(\d+)\s*mp",
        lowered,
    )
    if m:
        found["AREA_MAX"] = int(m.group(1))

    # Bare "X mp" with no qualifier → treat as minimum hint
    if "AREA_MIN" not in found and "AREA_MAX" not in found:
        m = _re.search(r"(\d{2,3})\s*mp", lowered)
        if m:
            found["AREA_MIN"] = int(m.group(1))

    # 7. Price — "maxim 1500 euro", "sub 2000 eur", "pana la 1800 €", "buget 1200", bare "1500 euro"
    _currency = r"(?:euro|eur|€|ron|lei)"
    # Explicit upper-bound phrases
    m = _re.search(
        r"(?:maxim|p[aâ]n[aă]\s+la|cel\s+mult|sub|mai\s+pu[tț]in\s+de|buget(?:\s+de)?|pret\s+maxim)\s*(\d{3,5})\s*" + _currency,
        lowered,
    )
    if m:
        found["PRICE_MAX"] = int(m.group(1))
    else:
        # Bare "1500 euro" / "1500 €" with no qualifier
        m = _re.search(r"(\d{3,5})\s*" + _currency, lowered)
        if m:
            found["PRICE_MAX"] = int(m.group(1))

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
