"""Fill empty SDS sections from the substance's GHS label.

Supplier SDSs derive much of Sections 4–8 and 10–13 from the GHS precautionary
(P) and hazard (H) statements. When no source has narrative data for a
section, list the label statements that apply to it instead of a bare gap.
"""

from __future__ import annotations

import re

from .model import Block, Ghs, Item, SdsDocument
from .sources.pubchem import statement_text

HEADING = "From the GHS label"
PICTOGRAM_NAMES = {
    "GHS01": "Explosive",
    "GHS02": "Flammable",
    "GHS03": "Oxidizer",
    "GHS04": "Compressed Gas",
    "GHS05": "Corrosive",
    "GHS06": "Acute Toxic",
    "GHS07": "Irritant",
    "GHS08": "Health Hazard",
    "GHS09": "Environmental Hazard",
}


def ghs_from_text(
    text: str,
    codes: dict[str, str],
    pictograms: dict[str, list[str]],
    source: str,
) -> Ghs:
    """Build a GHS label from free text, e.g. Section 2 of a supplier SDS.

    Statement texts and pictograms come from the official GHS code table, so a
    supplier's wording or PDF layout doesn't leak into the note's header.
    """
    signal = re.search(r"Signal word[\s\S]{0,160}?\b(Danger|Warning)\b", text, re.I)
    h_codes = list(dict.fromkeys(re.findall(r"\b(H\d{3}[A-Za-z]{0,2}|EUH\d{3})\b", text)))
    if not h_codes:
        # Some sheets print only the statement texts; map them back to codes.
        h_codes = codes_for_statements(text, codes)
    p_codes = list(dict.fromkeys(re.findall(r"\bP\d{3}(?:\s*\+\s*P\d{3})*", text)))
    ghs = Ghs(source=source)
    ghs.hazard_statements = [(c, codes[c]) for c in h_codes if c in codes]
    ghs.precautionary_codes = [re.sub(r"\s+", "", c) for c in p_codes]
    found = set(re.findall(r"\bGHS0[1-9]\b", text))
    for code, _ in ghs.hazard_statements:
        found.update(pictograms.get(code, []))
    # GHS precedence: the exclamation mark is dropped when the skull applies.
    if "GHS06" in found:
        found.discard("GHS07")
    ghs.pictograms = [(p, PICTOGRAM_NAMES[p]) for p in sorted(found)]
    ghs.signal_word = signal.group(1).capitalize() if signal else None
    return ghs


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def codes_for_statements(text: str, codes: dict[str, str]) -> list[str]:
    """H-codes whose official statement text appears verbatim in `text`."""
    haystack = f" {normalize(text)} "
    found = []
    candidates = [
        (code, normalize(statement))
        for code, statement in codes.items()
        if code.startswith("H") and "+" not in code and not statement.startswith("(Deleted)")
    ]
    # Longest statements first, so "Causes severe skin burns and eye damage" wins over shorter overlaps.
    for code, statement in sorted(candidates, key=lambda c: -len(c[1])):
        if len(statement) > 12 and f" {statement} " in haystack:
            found.append(code)
            haystack = haystack.replace(f" {statement} ", " ")
    return found


def p_section(code: str) -> int | None:
    """OSHA section a precautionary statement belongs to (first code of a combination)."""
    number = int(re.match(r"P(\d{3})", code).group(1))
    if 370 <= number <= 381:
        return 5
    if number in (390, 391):
        return 6
    if 300 <= number <= 364:
        return 4
    if 280 <= number <= 285 or number == 271:
        return 8
    if 200 <= number <= 299 or 400 <= number <= 499:
        return 7
    if number in (501, 502):
        return 13
    return None


def h_section(code: str) -> int | None:
    """OSHA section a hazard statement informs (physical, health, environmental)."""
    match = re.match(r"(?:EU)?H(\d{3})", code)
    if not match:
        return None
    number = int(match.group(1))
    if code.startswith("EUH") or 200 <= number < 300:
        return 10
    if 300 <= number < 400:
        return 11
    if 400 <= number < 500:
        return 12
    return None


def fill_from_ghs(doc: SdsDocument, ghs_codes: dict[str, str]) -> None:
    """Add GHS-derived blocks to sections that have no other data."""
    empty = {n for n in (4, 5, 6, 7, 8, 10, 11, 12, 13) if not doc.sections.get(n)}
    source = doc.ghs.source
    if not empty or not source:
        return
    found: dict[int, list[Item]] = {}
    for code in doc.ghs.precautionary_codes:
        section = p_section(code)
        text = statement_text(code, ghs_codes)
        if section in empty and text:
            found.setdefault(section, []).append(Item(text=text, label=code, source=source))
    for code, text in doc.ghs.hazard_statements:
        section = h_section(code)
        if section in empty:
            found.setdefault(section, []).append(Item(text=text, label=code, source=source))
    for section, items in found.items():
        doc.add_block(section, Block(HEADING, items))
