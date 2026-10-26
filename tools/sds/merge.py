"""Combine manifest overrides, supplier PDFs and PubChem into one SdsDocument."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .ghs_fallback import fill_from_ghs, ghs_from_text
from .http import fetch_bytes, fetch_json
from .manifest import Chemical, Manifest
from .model import Block, Component, Item, SdsDocument, Source
from .sources.pdf_sds import parse_sds_pdf, property_row
from .sources.pubchem import PUG_VIEW, PubChemRecord, best_alternate_cid, load_ghs_codes, load_ghs_pictograms


def manifest_source(manifest: Manifest, key: str, accessed: str) -> Source:
    meta = manifest.sources.get(key)
    if meta is None:
        raise ValueError(f"Override cites unknown source '{key}' (add it under `sources:` in chemicals.yaml)")
    return Source(key=key, title=meta["title"], url=meta.get("url"), detail=meta.get("detail"), accessed=meta.get("accessed", accessed))


def override_item(raw: dict[str, str] | str, manifest: Manifest, doc: SdsDocument, accessed: str) -> Item:
    """Build an Item from a manifest override, registering its cited source."""
    if isinstance(raw, str):
        raise ValueError(f"Override '{raw}' has no source; use {{text: ..., source: <key>}}")
    source = raw.get("source")
    if not source:
        raise ValueError(f"Override '{raw}' has no source")
    doc.sources.setdefault(source, manifest_source(manifest, source, accessed))
    return Item(text=raw.get("text") or raw.get("value", ""), label=raw.get("label"), source=source)


def absorb_properties(doc: SdsDocument, items: list[Item]) -> list[Item]:
    """Move supplier Section 9 values into the property table; return leftovers."""
    leftovers = []
    for it in items:
        row = property_row(it.label or "")
        if row is None:
            leftovers.append(it)
            continue
        values = doc.properties.setdefault(row, [])
        if len(values) < 2:
            label = f"{it.label}: " if row == "Appearance" and it.label else ""
            values.append(Item(text=f"{label}{it.text}", source=it.source))
    return leftovers


def build_document(chem: Chemical, manifest: Manifest, root: Path, refresh: bool = False) -> SdsDocument:
    """Fetch every configured source for `chem` and merge them."""
    cache = str(root / "cache")
    accessed = date.today().isoformat()
    doc = SdsDocument(
        name=chem.name,
        category=chem.category,
        cas=chem.cas,
        un_number=chem.un_number,
        related=list(chem.related),
        notes=list(chem.notes),
        tags=list(chem.tags),
        aliases=list(chem.aliases),
    )
    overrides = chem.overrides or {}

    for key, value in (overrides.get("identity") or {}).items():
        setattr(doc, key, value)

    # Curated overrides go first so they lead each section.
    for row, raw in (overrides.get("properties") or {}).items():
        doc.properties[row] = [override_item(raw, manifest, doc, accessed)]
    for section, blocks in (overrides.get("sections") or {}).items():
        for raw_block in blocks:
            items = [override_item(i, manifest, doc, accessed) for i in raw_block["items"]]
            doc.add_block(int(section), Block(raw_block["heading"], items))

    for index, sds in enumerate(chem.supplier_sds):
        key = f"sds-{chem.slug}-{index}"
        if sds.path:
            pdf = root / sds.path
        elif sds.url:
            safe = re.sub(r"[^a-z0-9]+", "-", sds.supplier.lower())
            pdf = fetch_bytes(sds.url, cache, f"pdfs/{chem.slug}-{safe}.pdf", refresh)
        else:
            continue
        doc.sources[key] = Source(key=key, title=f"{sds.supplier}: Safety Data Sheet, {chem.name}", url=sds.url, accessed=accessed)
        doc.supplier_sds.append(key)
        for section, blocks in parse_sds_pdf(pdf, sds.supplier, key).items():
            for block in blocks:
                if section == 9:
                    block.items = absorb_properties(doc, block.items)
                doc.add_block(section, block)

    if chem.pubchem_cid:
        cid = chem.safety_cid or chem.pubchem_cid
        record = fetch_json(PUG_VIEW.format(cid=cid), cache, f"pubchem/{cid}.json", refresh)
        if chem.safety_cid:
            reason = f" ({chem.safety_cid_reason})" if chem.safety_cid_reason else ""
            doc.notes.append(f"Safety data taken from PubChem CID {cid} instead of CID {chem.pubchem_cid}{reason}.")
        # No GHS classification on this CID: try other CIDs registered for the same CAS.
        elif not PubChemRecord(record, [], accessed).infos("Hazards Identification", "GHS Classification"):
            better = best_alternate_cid(cid, chem.cas, chem.name, cache, refresh)
            if better != cid:
                doc.notes.append(
                    f"Safety data taken from PubChem CID {better}, which shares this substance's CAS number "
                    f"or name with the linked CID {cid} (that record has no hazard classification)."
                )
                cid = better
                record = fetch_json(PUG_VIEW.format(cid=cid), cache, f"pubchem/{cid}.json", refresh)
        pubchem = PubChemRecord(record, chem.exclude_sources, accessed, chem.exclude_property_sources)
        pubchem.populate(doc, load_ghs_codes(cache, refresh), chem.ghs_source)
        doc.sources["pubchem-ghs-codes"] = Source(
            key="pubchem-ghs-codes",
            title="PubChem GHS Classification: hazard and precautionary statement texts",
            url="https://pubchem.ncbi.nlm.nih.gov/ghs/",
            accessed=accessed,
        )
        for source in pubchem.sources():
            doc.sources.setdefault(source.key, source)

    ghs_codes = load_ghs_codes(cache, refresh)
    if not doc.ghs.hazard_statements and doc.supplier_sds:
        # No GHS label on PubChem: read it from the first supplier SDS's Section 2.
        key = doc.supplier_sds[0]
        section_2 = " ".join(
            f"{b.heading} " + " ".join(f"{it.label or ''} {it.text}" for it in b.items if it.source == key)
            for b in doc.sections.get(2, [])
            if any(it.source == key for it in b.items)
        )
        doc.ghs = ghs_from_text(section_2, ghs_codes, load_ghs_pictograms(cache, refresh), key)
    fill_from_ghs(doc, ghs_codes)

    if chem.composition:
        doc.composition = [Component(**c) for c in chem.composition]
    else:
        doc.composition = [Component(name=doc.name, cas=doc.cas, ec=doc.ec, percent="100 (single substance)", formula=doc.formula)]

    if chem.wikipedia:
        doc.sources["wikipedia"] = Source(key="wikipedia", title=f"Wikipedia: {chem.name}", url=chem.wikipedia, accessed=accessed)
        doc.wikipedia = "wikipedia"

    for contact in manifest.emergency_contacts:
        if contact.get("source"):
            doc.sources.setdefault(contact["source"], manifest_source(manifest, contact["source"], accessed))
    return doc
