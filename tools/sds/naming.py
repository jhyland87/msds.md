"""Pick a readable chemical name for notes whose source title is an abbreviation.

Wikipedia titles some articles by abbreviation (ABCN, HATU, X-Gluc). Notes for
those get a full name, with the abbreviation kept as an alias.
"""

from __future__ import annotations

import re

MAX_NAME_LENGTH = 90


def is_abbreviation(name: str) -> bool:
    """True for names like "ABCN", "DMTMM", "EPI-001", "PyBOP", "X-Gluc", "P4-t-Bu"."""
    if re.fullmatch(r"[A-Z0-9][A-Z0-9\-]{1,9}", name):
        return True
    compact = name.replace("-", "")
    return len(compact) <= 7 and " " not in name and sum(c.isupper() for c in name) >= 2


def acceptable(candidate: str | None, abbreviation: str, allow_single_word: bool) -> bool:
    """Whether `candidate` is a usable full name for `abbreviation`."""
    if not candidate or len(candidate) > MAX_NAME_LENGTH:
        return False
    if is_abbreviation(candidate) or abbreviation.lower() in candidate.lower():
        return False
    # Mixtures ("a;b") and CAS-index inversions ("Methanaminium, N-…").
    if ";" in candidate or re.match(r"^[A-Z][a-z]+, ", candidate):
        return False
    # A bare synonym word ("Tanane") is usually a trade name; titles and labels are curated.
    if not allow_single_word and re.fullmatch(r"[A-Za-z]+", candidate):
        return False
    return True


def choose_name(abbreviation: str, label: str | None, title: str | None, synonyms: list[str]) -> str | None:
    """First acceptable name from the Wikidata label, PubChem title, then PubChem synonyms."""
    for candidate, single_word_ok in [(label, True), (title, True), *((s, False) for s in synonyms)]:
        if candidate and acceptable(candidate, abbreviation, single_word_ok):
            # Wikidata labels are lowercase; capitalise words but not locants ("p-", "tert-").
            return candidate[0].upper() + candidate[1:] if re.match(r"(?!(?:tert|sec|cis|trans)-)[a-z]{3}", candidate) else candidate
    return None
