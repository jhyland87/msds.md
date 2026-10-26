"""Load and validate `chemicals.yaml` plus generated manifests in `manifests/`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SupplierSds:
    supplier: str
    url: str | None = None
    path: str | None = None


@dataclass
class Chemical:
    name: str
    category: str
    pubchem_cid: int | None = None
    cas: str | None = None
    un_number: str | None = None
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    composition: list[dict[str, Any]] = field(default_factory=list)
    supplier_sds: list[SupplierSds] = field(default_factory=list)
    exclude_sources: list[str] = field(default_factory=list)
    exclude_property_sources: list[str] = field(default_factory=list)
    ghs_source: str | None = None
    wikipedia: str | None = None
    # PubChem record to read safety data from instead of `pubchem_cid` (e.g. the commercial salt).
    safety_cid: int | None = None
    safety_cid_reason: str | None = None
    # Hand-curated, cited facts: {"properties": {...}, "sections": {...}, "identity": {...}}
    overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "-")


@dataclass
class Manifest:
    chemicals: list[Chemical]
    sources: dict[str, dict[str, str]]
    emergency_contacts: list[dict[str, str]]
    wikipedia_sync: list[dict[str, Any]] = field(default_factory=list)

    def get(self, name: str) -> Chemical | None:
        lowered = name.lower()
        for chem in self.chemicals:
            if chem.name.lower() == lowered or lowered in (a.lower() for a in chem.aliases):
                return chem
        return None


def parse_chemicals(entries: list[dict[str, Any]]) -> list[Chemical]:
    chemicals = []
    for entry in entries:
        sds = [SupplierSds(**s) for s in entry.pop("supplier_sds", [])]
        chemicals.append(Chemical(**entry, supplier_sds=sds))
    return chemicals


def apply_gap_sources(path: Path, chemicals: list[Chemical]) -> None:
    """Attach curated gap-filling sources (gap-sources.yaml) to chemicals by name.

    Kept outside the manifests so they survive `sds wiki-sync` regenerating manifests/.
    """
    if not path.exists():
        return
    raw = yaml.safe_load(path.read_text()) or {}
    # Match aliases too, so entries survive a note being renamed (e.g. G418 -> Geneticin).
    by_name = {alias.lower(): c for c in chemicals for alias in [*c.aliases, c.name]}

    def lookup(name: str) -> Chemical:
        chem = by_name.get(name.lower())
        if chem is None:
            raise ValueError(f"{path.name}: '{name}' is not a chemical in any manifest")
        return chem

    for name, sheets in (raw.get("supplier_sds") or {}).items():
        chem = lookup(name)
        known = {s.url for s in chem.supplier_sds}
        chem.supplier_sds.extend(SupplierSds(**s) for s in sheets if s.get("url") not in known)
    for name, entry in (raw.get("safety_cid") or {}).items():
        chem = lookup(name)
        chem.safety_cid = int(entry["cid"])
        chem.safety_cid_reason = entry.get("reason")


def load_manifest(path: Path, include_generated: bool = True) -> Manifest:
    """Load the hand-curated manifest, then generated ones from `manifests/`.

    Curated entries win: a generated entry whose name or PubChem CID is
    already curated is dropped.
    """
    raw = yaml.safe_load(path.read_text()) or {}
    chemicals = parse_chemicals(raw.get("chemicals", []))
    names = [c.name for c in chemicals]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"Duplicate chemical names in manifest: {sorted(dupes)}")

    if include_generated:
        taken_names = {n.lower() for n in names}
        taken_cids = {c.pubchem_cid for c in chemicals if c.pubchem_cid}
        for generated in sorted((path.parent / "manifests").glob("*.yaml")):
            for chem in parse_chemicals((yaml.safe_load(generated.read_text()) or {}).get("chemicals", [])):
                if chem.name.lower() in taken_names or chem.pubchem_cid in taken_cids:
                    continue
                taken_names.add(chem.name.lower())
                if chem.pubchem_cid:
                    taken_cids.add(chem.pubchem_cid)
                chemicals.append(chem)

    if include_generated:
        apply_gap_sources(path.parent / "gap-sources.yaml", chemicals)

    return Manifest(
        chemicals=chemicals,
        sources=raw.get("sources", {}),
        emergency_contacts=raw.get("emergency_contacts", []),
        wikipedia_sync=raw.get("wikipedia_sync", []),
    )
