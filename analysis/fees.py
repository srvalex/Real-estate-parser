"""
analysis/fees.py
─────────────────
Pull the up-front cost terms out of listing descriptions with regex, and
report the unique combinations landlords/agencies actually ask for.

Three separate components get quoted in Romanian rental ads, and they are
routinely confused with each other:

  comision  — the agency's intermediation fee. Overwhelmingly quoted as
              "50% din prima luna de chirie", NOT a full month.
  garantie  — the security deposit, refundable. Usually 1 month.
  avans     — first month's rent paid up front. Not a fee at all, but it
              lands in the same "what do I pay on day one" bucket.

Only `comision` is money the tenant never sees again on top of rent, so
conflating the three overstates the cost of renting through an agency.

Text is normalised before matching: HTML entities decoded (descriptions
carry raw &#539; etc.), diacritics stripped (both "garanție" and "garantie"
occur), whitespace collapsed. Matching is deliberately bounded by sentence
punctuation so a phrase does not reach across into an unrelated clause.
"""
import collections
import html
import os
import re
import sys
import unicodedata

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import db_utils  # noqa: E402

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
SAMPLE = 10_000

_WORD_NUM = {"o": 1, "un": 1, "una": 1, "doua": 2, "trei": 3, "1": 1, "2": 2, "3": 3}

# Bounded by [^.!?;] so a match cannot run past the end of its own clause.
_NO_FEE = re.compile(r"fara\s+comision|comision\s*(?:de)?\s*0(?!\d)|comision\s+zero|"
                     r"0\s*%\s*comision|fara\s+agenti[ie]|direct\s+(?:de\s+la\s+)?proprietar", re.I)
_FEE_PCT = re.compile(r"comision[^.!?;]{0,80}?(\d{1,3})\s*%|(\d{1,3})\s*%[^.!?;]{0,50}?comision", re.I)
_FEE_MONTH = re.compile(r"comision[^.!?;]{0,50}?\b(o|un|una|1|2|doua)\b\s*(?:luna|luni|chirie|chirii)", re.I)

_DEPOSIT = re.compile(
    r"\b(o|un|una|doua|trei|1|2|3)\b\s*lun[ai][^.!?;]{0,25}?garantie"
    r"|garantie[^.!?;]{0,45}?\b(o|un|una|doua|trei|1|2|3)\b\s*(?:luna|luni|chirie|chirii)"
    r"|garantie[^.!?;]{0,15}?(\d)\s*l\b", re.I)

_ADVANCE = re.compile(
    r"\b(o|un|una|doua|1|2)\b\s*lun[ai]\s*(?:de\s+chirie\s+)?(?:in\s+)?avans"
    r"|avans[^.!?;]{0,30}?\b(o|un|una|doua|1|2)\b\s*(?:luna|luni)"
    r"|avans\s*(\d)\s*l\b"
    r"|chirie[a]?\s+in\s+avans[^.!?;]{0,20}?\b(o|un|una|1|2)\b\s*lun", re.I)


def _norm(text: str) -> str:
    text = html.unescape(text or "")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).lower()


def _first_num(match) -> int | None:
    """First non-empty capture group, mapped through the word->number table."""
    if not match:
        return None
    for g in match.groups():
        if g:
            return _WORD_NUM.get(g.strip(), None) if not g.isdigit() else int(g)
    return None


def extract(text: str) -> dict:
    t = _norm(text)
    mentions_fee = "comision" in t

    if _NO_FEE.search(t):
        fee = "0% (fara comision)"
    else:
        pct = _FEE_PCT.search(t)
        if pct:
            v = int(pct.group(1) or pct.group(2))
            fee = f"{v}%" if 0 < v <= 200 else None
        else:
            months = _first_num(_FEE_MONTH.search(t))
            fee = f"{months * 100}% ({months} chirie)" if months else None
    if fee is None:
        fee = "mentionat, fara valoare" if mentions_fee else "nespecificat"

    dep = _first_num(_DEPOSIT.search(t))
    adv = _first_num(_ADVANCE.search(t))
    return {
        "comision": fee,
        "garantie": f"{dep} luni" if dep else "nespecificat",
        "avans": f"{adv} luni" if adv else "nespecificat",
    }


def fetch(limit: int = SAMPLE) -> pd.DataFrame:
    client = db_utils.get_client()
    rows, last = [], ""
    while len(rows) < limit:
        resp = (client.table("listings")
                .select("url, platform_id, description, price_numeric, price_currency")
                .eq("is_available", 1).not_.is_("description", "null")
                .gt("url", last).order("url").limit(1000).execute())
        batch = resp.data or []
        if not batch:
            break
        rows.extend(batch)
        last = batch[-1]["url"]
        print(f"  fetched {len(rows):,}", end="\r")
    print()
    return pd.DataFrame(rows[:limit])


def main() -> None:
    df = fetch()
    parsed = pd.DataFrame([extract(d) for d in df["description"]])
    df = pd.concat([df.reset_index(drop=True), parsed], axis=1)
    df.to_csv(os.path.join(CACHE_DIR, "fees_parsed.csv"), index=False)

    print(f"\n{len(df):,} live listings with a description\n")
    for col in ("comision", "garantie", "avans"):
        print(f"=== {col} ===")
        vc = df[col].value_counts()
        for val, n in vc.head(8).items():
            print(f"  {n:6}  {n/len(df)*100:5.1f}%  {val}")
        print()

    print("=== UNIQUE COMBINATIONS (comision | garantie | avans) ===")
    combo = (df.groupby(["comision", "garantie", "avans"])
             .size().reset_index(name="listings")
             .sort_values("listings", ascending=False))
    combo["pct"] = (combo.listings / len(df) * 100).round(1)
    print(combo.head(20).to_string(index=False))
    combo.to_csv(os.path.join(CACHE_DIR, "fees_combinations.csv"), index=False)
    print(f"\n{len(combo)} distinct combinations in total")

    stated = df[~df.comision.isin(["nespecificat", "mentionat, fara valoare"])]
    print(f"\nListings with a resolvable commission value: {len(stated):,} "
          f"({len(stated)/len(df)*100:.1f}%)")
    print(stated.comision.value_counts().to_string())


if __name__ == "__main__":
    main()
