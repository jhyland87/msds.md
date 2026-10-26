"""Data model shared by the source adapters, merger and renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .vault_templates import load_layout

# Section headings, non-mandatory sections and Section 9 rows come from the
# vault's Obsidian template (Templates/SDS.md) so generated and hand-written
# notes share one layout.
LAYOUT = load_layout()
SECTION_TITLES = LAYOUT.section_titles
NON_MANDATORY_SECTIONS = LAYOUT.non_mandatory
REQUIRED_PROPERTIES = list(LAYOUT.required_properties)


@dataclass
class Source:
    """A citable origin of one or more facts (becomes a footnote)."""

    key: str
    title: str
    url: str | None = None
    detail: str | None = None
    accessed: str = field(default_factory=lambda: date.today().isoformat())


@dataclass
class Item:
    """One fact: free text, optionally labeled, optionally cited."""

    text: str
    label: str | None = None
    source: str | None = None


@dataclass
class Block:
    """A titled group of items inside an SDS section."""

    heading: str
    items: list[Item] = field(default_factory=list)


@dataclass
class Component:
    name: str
    cas: str | None = None
    ec: str | None = None
    percent: str | None = None
    formula: str | None = None


@dataclass
class Ghs:
    pictograms: list[tuple[str, str]] = field(default_factory=list)  # (code, name)
    signal_word: str | None = None
    hazard_statements: list[tuple[str, str]] = field(default_factory=list)  # (code, text)
    precautionary_codes: list[str] = field(default_factory=list)
    source: str | None = None


@dataclass
class SdsDocument:
    """Everything needed to render one SDS note."""

    name: str
    category: str
    cas: str | None = None
    ec: str | None = None
    cid: int | None = None
    formula: str | None = None
    molecular_weight: str | None = None
    iupac_name: str | None = None
    un_number: str | None = None
    synonyms: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    description: list[Item] = field(default_factory=list)
    uses: list[Item] = field(default_factory=list)
    ghs: Ghs = field(default_factory=Ghs)
    nfpa: dict[str, str] = field(default_factory=dict)
    composition: list[Component] = field(default_factory=list)
    properties: dict[str, list[Item]] = field(default_factory=dict)
    sections: dict[int, list[Block]] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    related: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    supplier_sds: list[str] = field(default_factory=list)  # source keys
    wikipedia: str | None = None  # source key of the Wikipedia article, if any

    def add_block(self, section: int, block: Block) -> None:
        """Append a block, merging into an existing block with the same heading."""
        if not block.items:
            return
        blocks = self.sections.setdefault(section, [])
        for existing in blocks:
            if existing.heading == block.heading:
                existing.items.extend(block.items)
                return
        blocks.append(block)
