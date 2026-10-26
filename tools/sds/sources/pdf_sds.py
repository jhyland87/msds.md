"""Supplier SDS PDF adapter: split a 16-section SDS PDF into SDS blocks."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pdfplumber

from ..model import Block, Item

SECTION_RE = re.compile(r"^\s*SECTION\s+(\d{1,2})\s*[:.\-–]?\s*(.*)$", re.IGNORECASE)
# Some suppliers (e.g. Fisher) head sections "2. Hazard(s) identification" with no "SECTION".
# "2. Hazard(s) identification" (Fisher) or "* 2 Hazard(s) identification" (Cayman).
NUMBERED_RE = re.compile(r"^\s*\*?\s*(\d{1,2})\.?\s*([A-Z].{3,80})$")
# A bare numbered line only counts as a section heading if its title fits that section.
SECTION_KEYWORDS = {
    1: "identification", 2: "hazard", 3: "composition", 4: "first", 5: "fire",
    6: "accidental release", 7: "handling", 8: "exposure", 9: "physical", 10: "stability",
    11: "toxicolog", 12: "ecolog", 13: "disposal", 14: "transport", 15: "regulatory", 16: "other",
}
# Short Title Case lines ("Signal Word", "Hazard Statements") act as subheadings.
TITLE_LINE_RE = re.compile(r"^(?:[A-Z][a-z()/-]*\s?){2,5}$")
JOIN_WORDS = re.compile(r"(?:[,/(\-]|\b(?:and|or|of|the|to|with|in|for|a))$", re.I)
SUBHEAD_RE = re.compile(r"^\d{1,2}\.\d{1,2}(?:\.\d{1,2})?\.?\s+(.+)$")
KV_RE = re.compile(r"^([^:]{2,70}?)\s+:\s+(.*)$")
# Bulleted "· Key:value" lines (Cayman-style sheets).
BULLET_KV_RE = re.compile(r"^([^:]{2,70}?):\s*(.+)$")
# Supplier Section 9 labels -> OSHA property rows (first match wins).
PROPERTY_RULES: list[tuple[str, str]] = [
    (r"odou?r threshold", "Odor threshold"),
    (r"odou?r", "Odor"),
    (r"colou?r|appearance|physical state", "Appearance"),
    (r"^ph\b", "pH"),
    (r"melting|freezing", "Melting / freezing point"),
    (r"boiling", "Boiling point"),
    (r"flash point", "Flash point"),
    (r"evaporation", "Evaporation rate"),
    (r"explosive limits|flammab\w* limits|\b[lu]el\b", "Explosive limits (LEL / UEL)"),
    (r"flammability", "Flammability"),
    (r"vapou?r pressure", "Vapor pressure"),
    (r"vapou?r density", "Vapor density"),
    (r"density|specific gravity", "Relative density"),
    (r"solubility", "Solubility"),
    (r"log ?p|partition", "Partition coefficient (log Kow)"),
    (r"auto-?ignition", "Auto-ignition temperature"),
    (r"decomposition", "Decomposition temperature"),
    (r"viscosity", "Viscosity"),
]


def property_row(label: str) -> str | None:
    """Map a supplier Section 9 label to an OSHA property row."""
    for pattern, row in PROPERTY_RULES:
        if re.search(pattern, label, re.I):
            return row
    return None


NOISE_RE = re.compile(
    r"^(no additional information available|not applicable|no data available|\(contd\. (on|from) page \d+\))\.?$",
    re.I,
)


def extract_text(path: Path) -> list[str]:
    """Return the text of each page."""
    with pdfplumber.open(path) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def strip_repeated_lines(pages: list[str]) -> list[str]:
    """Drop header/footer lines that repeat on most pages."""
    counts = Counter(line.strip() for page in pages for line in set(page.splitlines()))
    threshold = max(2, len(pages) // 2)
    repeated = {line for line, n in counts.items() if n >= threshold and not SECTION_RE.match(line)}
    lines: list[str] = []
    for page in pages:
        for line in page.splitlines():
            stripped = line.strip()
            # Footer page counters ("3/10", "Page 3 of 10") vary per page.
            if (
                stripped
                and stripped not in repeated
                and not re.fullmatch(r"_{5,}", stripped)
                and not re.search(r"\b\d+\s*/\s*\d+$|Page \d+ of \d+", stripped)
            ):
                lines.append(stripped)
    return lines


def section_heading(line: str, current: int | None) -> int | None:
    """Section number if `line` starts SDS section n, else None."""
    match = SECTION_RE.match(line)
    if match and 1 <= int(match.group(1)) <= 16:
        return int(match.group(1))
    match = NUMBERED_RE.match(line)
    if match:
        number = int(match.group(1))
        expected = SECTION_KEYWORDS.get(number, "~")
        if number > (current or 0) and expected in match.group(2).lower():
            return number
    return None


def split_sections(lines: list[str]) -> dict[int, list[str]]:
    """Group lines under their section heading."""
    sections: dict[int, list[str]] = {}
    current: int | None = None
    for line in lines:
        number = section_heading(line, current)
        if number is not None:
            current = number
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def lines_to_blocks(lines: list[str], heading_prefix: str, source: str) -> list[Block]:
    """Turn the lines of one section into blocks of labeled items."""
    blocks: list[Block] = []
    block = Block(heading_prefix)
    for line in lines:
        bulleted = line.startswith("·")
        line = line.lstrip("·* ").strip()
        if not line:
            continue
        sub = SUBHEAD_RE.match(line)
        title = sub.group(1).strip() if sub else (line if TITLE_LINE_RE.match(line) else None)
        if title:
            if block.items:
                blocks.append(block)
            block = Block(f"{title} ({heading_prefix})")
            continue
        if NOISE_RE.match(line):
            continue
        kv = KV_RE.match(line) or (BULLET_KV_RE.match(line) if bulleted else None)
        if kv and NOISE_RE.match(kv.group(2).strip()):
            continue
        if kv:
            block.items.append(Item(text=kv.group(2).strip(), label=kv.group(1).strip(), source=source))
            continue
        last = block.items[-1] if block.items else None
        # A wrapped line starts lowercase or follows a dangling comma/connector.
        if last and (line[:1].islower() or JOIN_WORDS.search(last.text)):
            last.text = f"{last.text} {line}".strip()
        else:
            block.items.append(Item(text=line, source=source))
    if block.items:
        blocks.append(block)
    return [b for b in blocks if any(i.text for i in b.items)]


def parse_sds_pdf(path: Path, supplier: str, source: str) -> dict[int, list[Block]]:
    """Parse a supplier SDS PDF into {section number: blocks}."""
    lines = strip_repeated_lines(extract_text(path))
    return {
        num: lines_to_blocks(sec_lines, f"{supplier} SDS", source)
        for num, sec_lines in split_sections(lines).items()
    }
