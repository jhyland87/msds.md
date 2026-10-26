"""Read the SDS layout from the vault's Obsidian templates.

`Templates/SDS.md` is the single source for section headings, the Section 9
property rows, non-mandatory sections and the frontmatter key order. The
snippet templates define the data-gap callout and the citation format, so
hand-written and generated notes stay identical in structure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "Templates"
SDS_TEMPLATE = TEMPLATES / "SDS.md"
GAP_TEMPLATE = TEMPLATES / "SDS data gap.md"
SOURCE_TEMPLATE = TEMPLATES / "SDS source.md"


@dataclass(frozen=True)
class Layout:
    section_titles: dict[int, str]
    non_mandatory: frozenset[int]
    required_properties: tuple[str, ...]
    frontmatter_keys: tuple[str, ...]
    gap_callout: str
    gap_text: str
    source_line: str


def parse_layout(sds: str, gap: str, source: str) -> Layout:
    """Parse the template texts into a Layout (raises if the SDS template is malformed)."""
    titles: dict[int, str] = {}
    non_mandatory: set[int] = set()
    current: int | None = None
    for line in sds.splitlines():
        heading = re.match(r"^## (\d{1,2})\. (.+)$", line)
        if heading:
            current = int(heading.group(1))
            titles[current] = heading.group(2).strip()
        elif line.startswith("## "):
            current = None
        elif current and "Non-mandatory" in line:
            non_mandatory.add(current)
    if sorted(titles) != list(range(1, 17)):
        raise ValueError(f"{SDS_TEMPLATE} must contain headings '## 1. …' to '## 16. …' (found {sorted(titles)})")

    section_9 = sds.split(f"## 9. {titles[9]}", 1)[1].split("\n## ", 1)[0]
    properties = tuple(re.findall(r"^\| \*\*(.+?)\*\* \|", section_9, re.M))

    frontmatter = re.match(r"^---\n(.*?)\n---\n", sds, re.S)
    keys = tuple(re.findall(r"^([a-z_]+):", frontmatter.group(1), re.M)) if frontmatter else ()

    gap_lines = [line.removeprefix(">").strip() for line in gap.strip().splitlines()]
    return Layout(
        section_titles=titles,
        non_mandatory=frozenset(non_mandatory),
        required_properties=properties,
        frontmatter_keys=keys,
        gap_callout=gap.strip(),
        gap_text=gap_lines[-1],
        source_line=source.strip(),
    )


@cache
def load_layout() -> Layout:
    return parse_layout(SDS_TEMPLATE.read_text(), GAP_TEMPLATE.read_text(), SOURCE_TEMPLATE.read_text())


def format_source(layout: Layout, number: int, title: str, url: str | None, accessed: str) -> str:
    """Fill the `SDS source` snippet for one footnote definition."""
    line = layout.source_line
    if not url:
        line = re.sub(r"\.?\s*<\{\{url\}\}>", "", line)
    return (
        line.replace("{{n}}", str(number))
        .replace("{{source}}", title)
        .replace("{{url}}", url or "")
        .replace("{{date:YYYY-MM-DD}}", accessed)
    )
