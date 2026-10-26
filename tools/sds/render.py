"""Render an SdsDocument to Obsidian-flavoured Markdown."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import yaml
from jinja2 import Environment, PackageLoader, StrictUndefined

from . import __version__
from .linker import Linker
from .model import LAYOUT, NON_MANDATORY_SECTIONS, REQUIRED_PROPERTIES, SECTION_TITLES, Item, SdsDocument
from .sources.pubchem import statement_text
from .vault_templates import format_source

GAP_TEXT = LAYOUT.gap_text

CALLOUTS = {"danger": "danger", "warning": "warning"}


class Renderer:
    def __init__(self, linker: Linker, ghs_codes: dict[str, str], emergency_contacts: list[dict[str, str]]):
        self.linker = linker
        self.ghs_codes = ghs_codes
        self.emergency_contacts = emergency_contacts
        self.env = Environment(
            loader=PackageLoader("sds", "templates"),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def render(self, doc: SdsDocument) -> str:
        cite_order: dict[str, int] = {}
        linked: dict[int, set[str]] = {}

        def cite(key: str | None) -> str:
            if not key or key not in doc.sources:
                return ""
            number = cite_order.setdefault(key, len(cite_order) + 1)
            return f"[^{number}]"

        def text(value: str, section: int, table: bool = False, raw: bool = False) -> str:
            out = value.replace("<", "&lt;").replace("\n", " ")
            # Source text (e.g. IUPAC names) may contain "[[", which Obsidian reads as a link.
            if not raw:
                out = out.replace("[", "\\[").replace("]", "\\]")
            if table:
                out = out.replace("|", "\\|")
            return self.linker.link(out, doc.name, linked.setdefault(section, set()))

        def item(it: Item, section: int, table: bool = False) -> str:
            body = text(it.text, section, table) + cite(it.source)
            if it.label and not table:
                return f"**{text(it.label, section)}:** {body}"
            return body

        template = self.env.get_template("sds.md.j2")
        body = template.render(
            doc=doc,
            titles=SECTION_TITLES,
            non_mandatory=NON_MANDATORY_SECTIONS,
            required_properties=REQUIRED_PROPERTIES,
            extra_properties=[p for p, v in doc.properties.items() if v and p not in REQUIRED_PROPERTIES],
            gap_callout=LAYOUT.gap_callout,
            cite=cite,
            text=text,
            item=item,
            h_statements=doc.ghs.hazard_statements,
            p_statements=[(c, statement_text(c, self.ghs_codes)) for c in doc.ghs.precautionary_codes],
            callout=self.callout(doc)[0],
            headline=self.callout(doc)[1],
            contacts=self.emergency_contacts,
            today=date.today().isoformat(),
            version=__version__,
        )
        # Footnote definitions come last so Obsidian/GitHub list them under "Sources".
        sources = [doc.sources[k] for k in cite_order]
        footnotes = "\n".join(
            format_source(LAYOUT, n, s.title + (f" — {s.detail}" if s.detail else ""), s.url, s.accessed)
            for n, s in enumerate(sources, 1)
        )
        body = re.sub(r"\n{3,}", "\n\n", body).rstrip()
        return self.frontmatter(doc) + body + "\n\n" + footnotes + "\n"

    @staticmethod
    def explicitly_unclassified(doc: SdsDocument) -> bool:
        """True when a source states the substance is not classified (vs. no data found)."""
        phrases = ("not classified", "not considered hazardous", "not a hazardous substance")
        return any(p in it.text.lower() for b in doc.sections.get(2, []) for it in b.items for p in phrases)

    def callout(self, doc: SdsDocument) -> tuple[str, str]:
        """(callout type, headline) for the hazard box at the top of the note."""
        signal = (doc.ghs.signal_word or "").lower()
        if signal in CALLOUTS:
            return CALLOUTS[signal], signal.upper()
        if doc.ghs.hazard_statements:
            return "warning", "HAZARDOUS"
        if self.explicitly_unclassified(doc):
            return "info", "NOT CLASSIFIED"
        return "warning", "NO GHS DATA FOUND"

    @staticmethod
    def frontmatter(doc: SdsDocument) -> str:
        data: dict[str, Any] = {
            "title": doc.name,
            "aliases": doc.aliases,
            "cas": doc.cas,
            "ec_number": doc.ec,
            "pubchem_cid": doc.cid,
            "formula": doc.formula,
            "un_number": doc.un_number,
            "category": doc.category,
            "signal_word": doc.ghs.signal_word or "None",
            "ghs_pictograms": [code for code, _ in doc.ghs.pictograms],
            "hazard_codes": [code for code, _ in doc.ghs.hazard_statements],
            "nfpa_health": doc.nfpa.get("health"),
            "nfpa_fire": doc.nfpa.get("fire"),
            "nfpa_instability": doc.nfpa.get("instability"),
            "tags": ["sds", *doc.tags],
            "generated": date.today().isoformat(),
        }
        # Follow the property order of the Obsidian template; extra keys go last.
        order = {key: i for i, key in enumerate(LAYOUT.frontmatter_keys)}
        clean = {k: v for k, v in sorted(data.items(), key=lambda kv: order.get(kv[0], len(order))) if v not in (None, [], "")}
        return "---\n" + yaml.safe_dump(clean, sort_keys=False, allow_unicode=True, width=1000) + "---\n\n"
