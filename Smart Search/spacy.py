import spacy

nlp = spacy.load("ro_core_news_sm")

REAL_ESTATE_TAXONOMY = {
    "metrou": "HAS_METRO",
    "renovat": "CONDITION_RENOVATED",
    "centrală": "HAS_HEATING_UNIT",
    "parcare": "HAS_PARKING",
    "garaj": "HAS_PARKING",
    "pet-friendly":"PET_FRIENDLY",
    "animal de companie":"PET_FRIENDLY"
}

def extract_filters(text):
    doc = nlp(text.lower())
    found_filters = {}
    
    # 1. Extract Numeric Filters (e.g., "2 camere")
    for token in doc:
        if token.like_num and token.head.lemma_ == "cameră":
            found_filters["ROOM_COUNT"] = token.text

    # 2. Extract Keyword Filters via Lemmatization
    for token in doc:
        lemma = token.lemma_
        if lemma in REAL_ESTATE_TAXONOMY:
            filter_key = REAL_ESTATE_TAXONOMY[lemma]
            # Avoid overwriting if we already found a specific value (like ROOM_COUNT)
            if filter_key not in found_filters:
                found_filters[filter_key] = True

    # 3. Specific Logic for Sectors (e.g., "sectorul 4")
    # We look for the word 'sector' followed by a number
    for i, token in enumerate(doc):
        if token.lemma_ == "sector" and i + 1 < len(doc):
            next_token = doc[i+1]
            if next_token.like_num:
                found_filters["LOCATION_SECTOR"] = next_token.text

    return found_filters

prompt = "Caut apartament cu 2 camere in sectorul 4, aproape de metrou. Vreau sa fie ceva modern si renovat."
filters = extract_filters(prompt)
print(f"Extracted Filters: {filters}")