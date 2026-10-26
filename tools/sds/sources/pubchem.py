"""PubChem PUG-View adapter.

PubChem aggregates CAMEO Chemicals, NIOSH, ILO ICSC, HSDB, ECHA, ERG and more,
and tags every annotation with a ReferenceNumber. This module maps those
annotations onto the 16 OSHA SDS sections and keeps the per-fact citation.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ..http import fetch_json, fetch_text
from ..model import Block, Ghs, Item, SdsDocument, Source

PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON"
PUG_NAME = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/cids/JSON"
GHS_CODES = "https://pubchem.ncbi.nlm.nih.gov/ghs/ghscode_11.txt"
COMPOUND_URL = "https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"

# Contributors that add noise to an SDS (mixture incident reports, screening
# levels, cosmetics/food listings). Matched against "SourceName | Name".
DEFAULT_EXCLUDES = [
    r"Pistoia Alliance",
    r"ToxValDB",
    r"Regional (Screening|Removal)",
    r"Chemical Data Reporting",
    r"\bAICIS\b|Industrial Chemicals Introduction",
    r"California Safe Cosmetics",
    r"EFSA",
    r"Liver Toxicity",
    r"Safer Choice",
    r"T3DB|Toxin and Toxin Target",
    r"NITE-CMC",
    r"Chemical Safety and Hazard Investigation Board",
    r"New Zealand",
    r"Drug Enforcement",
]

# Lower number = preferred when a block is capped.
SOURCE_PRIORITY = [
    (r"CAMEO", 0),
    (r"ILO-WHO|ICSC", 1),
    (r"NIOSH", 2),
    (r"Occupational Safety and Health Administration", 3),
    (r"Emergency Response Guidebook|49 CFR", 4),
    (r"European Chemicals Agency|Regulation \(EC\)", 5),
    (r"Acute Exposure Guideline|PAC Chemical", 5),
    (r"Haz-Map", 6),
    (r"HSDB|Hazardous Substances Data Bank", 8),
]


@dataclass(frozen=True)
class Target:
    section: int
    heading: str
    cap: int


# PubChem TOCHeading -> where it lands in the SDS. Unlisted headings are skipped.
SECTION_MAP: dict[str, Target] = {
    # 2 - Hazards
    "Hazard Classes and Categories": Target(2, "Hazard classes and categories", 3),
    "Hazards Summary": Target(2, "Hazards summary", 2),
    "Health Hazards": Target(2, "Health hazards", 2),
    "Fire Hazards": Target(2, "Fire hazards", 2),
    "Fire Potential": Target(2, "Fire potential", 1),
    "Physical Dangers": Target(2, "Physical dangers", 1),
    "Skin, Eye, and Respiratory Irritations": Target(2, "Skin, eye and respiratory irritation", 2),
    "Highly Hazardous Substance": Target(2, "Highly hazardous substance", 1),
    # 4 - First aid
    "First Aid Measures": Target(4, "First aid by exposure route", 6),
    "First Aid": Target(4, "First aid", 3),
    "Antidote and Emergency Treatment": Target(4, "Notes to physician", 2),
    # 5 - Fire fighting
    "Fire Fighting": Target(5, "Fire fighting", 3),
    "Fire Fighting Procedures": Target(5, "Fire fighting procedures", 3),
    "Firefighting Hazards": Target(5, "Fire fighting hazards", 2),
    "Explosive Limits and Potential": Target(5, "Explosion hazards", 2),
    "Toxic Combustion Products": Target(5, "Hazardous combustion products", 2),
    # 6 - Accidental release
    "Accidental Release Measures": Target(6, "Accidental release", 3),
    "Isolation and Evacuation": Target(6, "Isolation and evacuation", 3),
    "Nonfire Spill Response": Target(6, "Non-fire spill response", 2),
    "Spillage Disposal": Target(6, "Spillage disposal", 1),
    "Cleanup Methods": Target(6, "Cleanup methods", 3),
    # 7 - Handling and storage
    "Preventive Measures": Target(7, "Precautions for safe handling", 3),
    "Fire Prevention": Target(7, "Fire prevention", 1),
    "Safe Storage": Target(7, "Safe storage", 2),
    "Storage Conditions": Target(7, "Storage conditions", 3),
    # 8 - Exposure controls / PPE
    "Exposure Control and Personal Protection": Target(8, "Exposure controls", 3),
    "Permissible Exposure Limit (PEL)": Target(8, "OSHA permissible exposure limit (PEL)", 2),
    "Recommended Exposure Limit (REL)": Target(8, "NIOSH recommended exposure limit (REL)", 2),
    "Threshold Limit Values (TLV)": Target(8, "ACGIH threshold limit value (TLV)", 2),
    "Immediately Dangerous to Life or Health (IDLH)": Target(8, "IDLH", 2),
    "Occupational Exposure Limits (OEL)": Target(8, "Other occupational exposure limits", 3),
    "OSHA Standards": Target(8, "OSHA standards", 2),
    "NIOSH Recommendations": Target(8, "NIOSH recommendations", 2),
    "AEGLs Table": Target(8, "Acute Exposure Guideline Levels (AEGLs)", 6),
    "Protective Action Criteria (PAC)": Target(8, "Protective Action Criteria (PAC)", 4),
    "Emergency Response Planning Guidelines": Target(8, "Emergency response guidelines (ERG / ERPG)", 3),
    "Personal Protective Equipment (PPE)": Target(8, "Personal protective equipment", 4),
    "Respirator Recommendations": Target(8, "Respirator recommendations", 1),
    "Exposure Prevention": Target(8, "Exposure prevention", 1),
    "Inhalation Prevention": Target(8, "Exposure prevention", 1),
    "Skin Prevention": Target(8, "Exposure prevention", 1),
    "Eye Prevention": Target(8, "Exposure prevention", 1),
    "Ingestion Prevention": Target(8, "Exposure prevention", 1),
    # 10 - Stability and reactivity
    "Chemical Dangers": Target(10, "Chemical dangers", 2),
    "Air and Water Reactions": Target(10, "Air and water reactions", 2),
    "Reactive Group": Target(10, "Reactive groups", 2),
    "Reactivity Profile": Target(10, "Reactivity profile", 2),
    "Hazardous Reactivities and Incompatibilities": Target(10, "Hazardous reactions and incompatibilities", 4),
    "Stability/Shelf Life": Target(10, "Chemical stability", 2),
    "Decomposition": Target(10, "Hazardous decomposition", 2),
    "Polymerization": Target(10, "Polymerization", 1),
    "Other Hazardous Reactions": Target(10, "Other hazardous reactions", 1),
    "Corrosivity": Target(10, "Corrosivity", 2),
    # 11 - Toxicology
    "Toxicity Summary": Target(11, "Toxicity summary", 1),
    "Exposure Routes": Target(11, "Routes of exposure", 2),
    "Inhalation Risk": Target(11, "Inhalation risk", 1),
    "Signs and Symptoms": Target(11, "Signs and symptoms", 3),
    "Effects of Short Term Exposure": Target(11, "Short-term exposure", 1),
    "Effects of Long Term Exposure": Target(11, "Long-term exposure", 1),
    "Target Organs": Target(11, "Target organs", 1),
    "Acute Effects": Target(11, "Acute effects", 1),
    "Health Effects": Target(11, "Health effects", 1),
    "Carcinogen Classification": Target(11, "Carcinogenicity", 3),
    "Evidence for Carcinogenicity": Target(11, "Carcinogenicity", 1),
    "Lethal Dose": Target(11, "Acute toxicity values", 2),
    "Lethal Concentration": Target(11, "Acute toxicity values", 2),
    "Human Toxicity Values": Target(11, "Acute toxicity values", 2),
    "Non-Human Toxicity Values": Target(11, "Acute toxicity values", 4),
    "Human Toxicity Excerpts": Target(11, "Human toxicity", 2),
    "Populations at Special Risk": Target(11, "Populations at special risk", 1),
    "Medical Surveillance": Target(11, "Medical surveillance", 1),
    # 12 - Ecology
    "ICSC Environmental Data": Target(12, "Environmental hazards", 1),
    "Environmental Fate/Exposure Summary": Target(12, "Environmental fate summary", 1),
    "Ecotoxicity Values": Target(12, "Ecotoxicity", 4),
    "Environmental Fate": Target(12, "Persistence and degradability", 2),
    "Environmental Abiotic Degradation": Target(12, "Persistence and degradability", 1),
    "Environmental Bioconcentration": Target(12, "Bioaccumulative potential", 1),
    "Soil Adsorption/Mobility": Target(12, "Mobility in soil", 1),
    # 13 - Disposal
    "Disposal Methods": Target(13, "Disposal methods", 3),
    "EPA Hazardous Waste Number": Target(13, "EPA hazardous waste number", 2),
    # 14 - Transport
    "DOT Hazard Classification": Target(14, "DOT hazard classification", 3),
    "DOT ID and Guide": Target(14, "DOT ID and ERG guide", 3),
    "Shipping Name/ Number DOT/UN/NA/IMO": Target(14, "Proper shipping name", 3),
    "DOT Label": Target(14, "DOT label", 2),
    "UN Classification": Target(14, "UN classification", 1),
    "EC Classification": Target(14, "EC classification", 1),
    "Packaging and Labelling": Target(14, "Packaging and labelling", 1),
    "Shipment Methods and Regulations": Target(14, "Shipment methods and regulations", 2),
    "DOT Emergency Guidelines": Target(14, "Emergency response guide", 2),
    # 15 - Regulatory
    "Regulatory Information": Target(15, "Regulatory listings", 8),
    "CERCLA Reportable Quantities": Target(15, "CERCLA reportable quantities", 2),
    "Clean Water Act Requirements": Target(15, "Clean Water Act", 1),
    "RCRA Requirements": Target(15, "RCRA", 1),
    "DHS Chemicals of Interest (COI)": Target(15, "DHS Chemicals of Interest (CFATS)", 4),
    "FIFRA Requirements": Target(15, "FIFRA", 1),
    "FDA Requirements": Target(15, "FDA", 1),
    "Atmospheric Standards": Target(15, "Atmospheric standards", 1),
    "Federal Drinking Water Guidelines": Target(15, "Drinking water guidelines", 1),
    "Other Standards Regulations and Guidelines": Target(15, "Other standards and guidelines", 2),
}

# Experimental property heading -> Section 9 row.
PROPERTY_MAP: dict[str, str] = {
    "Color/Form": "Appearance",
    "Odor": "Odor",
    "Odor Threshold": "Odor threshold",
    "pH": "pH",
    "Melting Point": "Melting / freezing point",
    "Boiling Point": "Boiling point",
    "Flash Point": "Flash point",
    "Flammable Limits": "Explosive limits (LEL / UEL)",
    "Lower Explosive Limit (LEL)": "Explosive limits (LEL / UEL)",
    "Upper Explosive Limit (UEL)": "Explosive limits (LEL / UEL)",
    "Vapor Pressure": "Vapor pressure",
    "Vapor Density": "Vapor density",
    "Density": "Relative density",
    "Solubility": "Solubility",
    "LogP": "Partition coefficient (log Kow)",
    "Autoignition Temperature": "Auto-ignition temperature",
    "Viscosity": "Viscosity",
    "Dissociation Constants": "Dissociation constant (pKa)",
    "Refractive Index": "Refractive index",
    "Surface Tension": "Surface tension",
    "Heat of Vaporization": "Heat of vaporization",
    "Critical Temperature and Pressure": "Critical temperature / pressure",
}
PROPERTY_CAP = 2
# Numbers without a unit are only meaningful for dimensionless properties.
BARE_NUMBER = re.compile(r"^-?[\d.,\s]+$")
UNITLESS_ROWS = {"pH", "Partition coefficient (log Kow)", "Relative density", "Refractive index", "Vapor density", "Dissociation constant (pKa)"}
MAX_ITEM_CHARS = 700


PUG_CAS = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/xref/RN/{cas}/cids/JSON"
PUG_SAFETY = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON?heading=Safety+and+Hazards"


def safety_score(record: dict[str, Any]) -> int:
    """Number of annotations under "Safety and Hazards" (0 if the record has none)."""

    def count(section: dict[str, Any]) -> int:
        return len(section.get("Information", [])) + sum(count(s) for s in section.get("Section", []))

    return count(record.get("Record", {})) if isinstance(record, dict) else 0


def has_ghs(record: dict[str, Any]) -> bool:
    return '"GHS Classification"' in json.dumps(record) if record else False


def best_alternate_cid(
    current: int,
    cas: str | None,
    name: str,
    cache: str,
    refresh: bool = False,
    limit: int = 8,
) -> int:
    """Pick the CID with the best safety data among those sharing `cas` or `name`.

    PubChem often files hazard data under a different CID than the one
    Wikipedia/Wikidata link (an aggregate, salt or formula-unit form of the
    same substance). Candidates rank by having a GHS classification, then by
    the amount of safety data.
    """
    candidates = [current]
    lookups = [(PUG_NAME.format(name=name), f"pubchem/name-{name}.json")]
    if cas:
        lookups.insert(0, (PUG_CAS.format(cas=cas), f"pubchem/cas-{cas}.json"))
    for url, key in lookups:
        data = fetch_json(url, cache, key, refresh)
        for cid in data.get("IdentifierList", {}).get("CID", []) if isinstance(data, dict) else []:
            if cid not in candidates:
                candidates.append(cid)
    best, best_rank = current, (False, -1)
    for cid in candidates[:limit]:
        view = fetch_json(PUG_SAFETY.format(cid=cid), cache, f"pubchem/safety-{cid}.json", refresh)
        rank = (has_ghs(view), safety_score(view))
        if rank > best_rank:
            best, best_rank = cid, rank
    return best


def lookup_cid(name: str, cache: str, refresh: bool = False) -> int | None:
    """Resolve a chemical name to its PubChem CID (first match)."""
    data = fetch_json(PUG_NAME.format(name=name), cache, f"pubchem/name-{name}.json", refresh)
    cids = data.get("IdentifierList", {}).get("CID", []) if isinstance(data, dict) else []
    return cids[0] if cids else None


def load_ghs_codes(cache: str, refresh: bool = False) -> dict[str, str]:
    """Return {H/P code: statement text} from PubChem's GHS code table."""
    text = fetch_text(GHS_CODES, cache, "pubchem/ghscode_11.txt", refresh)
    codes: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0].strip():
            codes[cols[0].strip()] = cols[1].strip()
    return codes


def load_ghs_pictograms(cache: str, refresh: bool = False) -> dict[str, list[str]]:
    """Return {H code: [GHS pictogram codes]} from PubChem's GHS code table."""
    text = fetch_text(GHS_CODES, cache, "pubchem/ghscode_11.txt", refresh)
    table: dict[str, list[str]] = {}
    for line in text.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) >= 6 and cols[0].startswith("H"):
            table[cols[0].strip()] = re.findall(r"GHS\d\d", cols[5])
    return table


def statement_text(code: str, codes: dict[str, str]) -> str:
    """Text for a (possibly combined, e.g. P301+P330+P331) precautionary code."""
    if code in codes:
        return codes[code]
    parts = [codes.get(part, "") for part in code.split("+")]
    return " ".join(p for p in parts if p)


class PubChemRecord:
    """Wraps one PUG-View compound record and extracts SDS content from it."""

    def __init__(
        self,
        record: dict[str, Any],
        excludes: list[str],
        accessed: str,
        property_excludes: list[str] | None = None,
    ):
        self.record = record["Record"]
        self.cid: int = self.record["RecordNumber"]
        self.accessed = accessed
        self.exclude = re.compile("|".join(DEFAULT_EXCLUDES + excludes), re.IGNORECASE)
        # Extra filter for Section 9 only, e.g. gas-phase data on a solution.
        self.property_exclude = re.compile("|".join(property_excludes), re.I) if property_excludes else None
        self.refs = {r["ReferenceNumber"]: r for r in self.record.get("Reference", [])}
        self.used_refs: set[int] = set()

    # -- reference handling ------------------------------------------------

    def ref_label(self, ref_no: int | None) -> str:
        ref = self.refs.get(ref_no or -1, {})
        return f"{ref.get('SourceName', '')} | {ref.get('Name', '')}"

    def allowed(self, ref_no: int | None) -> bool:
        if ref_no is None:
            return True
        return not self.exclude.search(self.ref_label(ref_no))

    def priority(self, ref_no: int | None) -> int:
        label = self.ref_label(ref_no)
        for pattern, rank in SOURCE_PRIORITY:
            if re.search(pattern, label):
                return rank
        return 7

    def source_key(self, ref_no: int | None) -> str:
        if ref_no is None or ref_no not in self.refs:
            return f"pubchem-{self.cid}"
        self.used_refs.add(ref_no)
        return f"pubchem-{self.cid}-ref{ref_no}"

    def sources(self) -> list[Source]:
        """Sources for the record itself plus every reference that was used."""
        out = [
            Source(
                key=f"pubchem-{self.cid}",
                title=f"PubChem Compound Summary for CID {self.cid}, {self.record.get('RecordTitle', '')}",
                url=COMPOUND_URL.format(cid=self.cid),
                detail="National Center for Biotechnology Information",
                accessed=self.accessed,
            )
        ]
        for ref_no in sorted(self.used_refs):
            ref = self.refs[ref_no]
            out.append(
                Source(
                    key=f"pubchem-{self.cid}-ref{ref_no}",
                    title=f"{ref.get('SourceName', 'Unknown source')}: {ref.get('Name', '')}".strip(": "),
                    url=ref.get("URL"),
                    detail=f"via PubChem CID {self.cid}",
                    accessed=self.accessed,
                )
            )
        return out

    # -- traversal ---------------------------------------------------------

    def walk(self, section: dict[str, Any] | None = None, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
        """Yield (heading path, section) for every section in the record."""
        node = section if section is not None else self.record
        for child in node.get("Section", []):
            child_path = (*path, child["TOCHeading"])
            yield child_path, child
            yield from self.walk(child, child_path)

    def find(self, *path: str) -> dict[str, Any] | None:
        for p, sec in self.walk():
            if p[-len(path):] == path:
                return sec
        return None

    def infos(self, *path: str) -> list[dict[str, Any]]:
        sec = self.find(*path)
        return sec.get("Information", []) if sec else []

    def first_string(self, *path: str) -> str | None:
        for info in self.infos(*path):
            text = flatten(info.get("Value", {}))
            if text:
                return text
        return None

    # -- extraction --------------------------------------------------------

    def items_for(
        self,
        infos: list[dict[str, Any]],
        cap: int,
        heading: str,
        existing: list[Item] | None = None,
    ) -> list[Item]:
        """Filter, rank, dedupe and cap a list of PUG-View Information entries."""
        ranked = sorted(
            (
                i
                for i in infos
                if self.allowed(i.get("ReferenceNumber")) and not self.exclude.search(i.get("Name", ""))
            ),
            key=lambda i: self.priority(i.get("ReferenceNumber")),
        )
        items: list[Item] = []
        seen = {normalize(i.text) for i in existing or []}
        for info in ranked:
            text = clean(flatten(info.get("Value", {})))
            norm = normalize(text)
            # Treat "181 °F" and "181 °F at 760 mmHg (NIOSH)" as the same value.
            if not text or any(norm.startswith(s) or s.startswith(norm) for s in seen):
                continue
            seen.add(norm)
            name = info.get("Name")
            label = name if name and name != heading else None
            items.append(Item(text=truncate(text), label=label, source=self.source_key(info.get("ReferenceNumber"))))
            if len(items) >= cap:
                break
        return items

    def populate(self, doc: SdsDocument, ghs_codes: dict[str, str], ghs_source: str | None = None) -> None:
        """Fill an SdsDocument with everything this record offers."""
        doc.cid = self.cid
        rec_key = f"pubchem-{self.cid}"
        doc.iupac_name = doc.iupac_name or self.first_string("Computed Descriptors", "IUPAC Name")
        doc.formula = doc.formula or self.first_string("Names and Identifiers", "Molecular Formula")
        mw = self.first_string("Computed Properties", "Molecular Weight")
        doc.molecular_weight = doc.molecular_weight or (f"{mw} g/mol" if mw else None)
        doc.ec = doc.ec or self.first_string("Other Identifiers", "European Community (EC) Number")
        doc.cas = doc.cas or self.first_string("Other Identifiers", "CAS")
        if not doc.un_number:
            un = self.first_string("Other Identifiers", "UN Number")
            match = re.search(r"\b(\d{4})\b", un or "")
            doc.un_number = f"UN{match.group(1)}" if match else None
        if not doc.synonyms:
            doc.synonyms = self.synonyms()

        desc = self.items_for(self.infos("Experimental Properties", "Physical Description"), 2, "")
        doc.description.extend(desc)
        doc.uses.extend(self.items_for(self.infos("Use and Manufacturing", "Uses"), 3, "Uses"))

        if not doc.ghs.hazard_statements:
            doc.ghs = self.ghs(ghs_source)
        self.nfpa(doc)

        for path, sec in self.walk():
            heading = path[-1]
            if path[0] not in ("Safety and Hazards", "Toxicity", "Chemical and Physical Properties"):
                continue
            if heading in PROPERTY_MAP and "Experimental Properties" in path:
                row = PROPERTY_MAP[heading]
                existing = doc.properties.setdefault(row, [])
                room = PROPERTY_CAP - len(existing)
                if room > 0:
                    infos = [
                        i
                        for i in sec.get("Information", [])
                        if not (self.property_exclude and self.property_exclude.search(self.ref_label(i.get("ReferenceNumber"))))
                    ]
                    short = [
                        i
                        for i in infos
                        if len(flatten(i.get("Value", {}))) < 200
                        and (row in UNITLESS_ROWS or not BARE_NUMBER.match(flatten(i.get("Value", {}))))
                    ]
                    existing.extend(self.items_for(short or infos, room, heading, existing))
                continue
            target = SECTION_MAP.get(heading)
            if target is None or not sec.get("Information"):
                continue
            label_heading = target.heading
            items = self.items_for(sec["Information"], target.cap, label_heading)
            if target.heading == "Exposure prevention":
                for item in items:
                    item.label = item.label or heading.replace(" Prevention", "")
            doc.add_block(target.section, Block(target.heading, items))

        if doc.molecular_weight and "Molecular weight" not in doc.properties:
            doc.properties["Molecular weight"] = [Item(doc.molecular_weight, source=rec_key)]

    def synonyms(self, limit: int = 12) -> list[str]:
        info = self.infos("Synonyms", "Depositor-Supplied Synonyms")
        if not info:
            return []
        names = [s["String"] for s in info[0]["Value"].get("StringWithMarkup", [])]
        # Skip registry-style identifiers (CAS, EC, UNII, catalogue codes).
        id_like = re.compile(
            r"^[\d\-]+$|^[A-Z0-9]{8,}$|^(EINECS|EC|UNII|DTXSID|CHEBI|NSC|UN|CAS)[\s:\-]|^[A-Z]{1,4}-?\d{3,}$|[:;]|kappa|\(\d?[+-]\)|\(T-4\)",
            re.I,
        )
        out: list[str] = []
        for name in names:
            # Also skip OCR-style misspellings of names already kept.
            if id_like.search(name) or any(similar(name, o) for o in [self.record.get("RecordTitle", ""), *out]):
                continue
            out.append(name)
            if len(out) >= limit:
                break
        return out

    def ghs(self, prefer: str | None) -> Ghs:
        """GHS label from one contributor (first by default, or `prefer` regex)."""
        infos = self.infos("Hazards Identification", "GHS Classification")
        groups: dict[int, list[dict[str, Any]]] = {}
        for info in infos:
            groups.setdefault(info.get("ReferenceNumber", -1), []).append(info)
        if not groups:
            return Ghs()
        chosen = next(iter(groups))
        if prefer:
            for ref_no in groups:
                if re.search(prefer, self.ref_label(ref_no), re.I):
                    chosen = ref_no
                    break
        ghs = Ghs(source=self.source_key(chosen))
        for info in groups[chosen]:
            name = info.get("Name", "")
            swm = info.get("Value", {}).get("StringWithMarkup", [])
            if name == "Pictogram(s)":
                for s in swm:
                    for m in s.get("Markup", []):
                        code = re.search(r"(GHS\d\d)", m.get("URL", ""))
                        if code:
                            ghs.pictograms.append((code.group(1), m.get("Extra", "")))
            elif name == "Signal":
                ghs.signal_word = flatten(info["Value"]) or None
            elif name == "GHS Hazard Statements":
                for s in swm:
                    match = re.match(r"(H\d{3}[A-Za-z+H\d]*|EUH\d{3})[:\s]+(.*)", s["String"])
                    if match:
                        text = re.sub(r"\s*\[.*?\]\s*$", "", match.group(2)).strip()
                        # ECHA aggregates prefix the share of notifiers, e.g. "(38.3%): ...".
                        share = re.match(r"^\((\d+(?:\.\d+)?%)\):\s*(.*)$", text)
                        if share:
                            text = f"{share.group(2)} ({share.group(1)} of ECHA notifications)"
                        ghs.hazard_statements.append((match.group(1), text))
            elif name == "Precautionary Statement Codes":
                text = flatten(info["Value"])
                ghs.precautionary_codes = re.findall(r"P\d{3}(?:\+P\d{3})*", text)
        return ghs

    def nfpa(self, doc: SdsDocument) -> None:
        infos = [i for i in self.infos("Hazards Identification", "NFPA Hazard Classification") if self.allowed(i.get("ReferenceNumber"))]
        items: list[Item] = []
        for info in infos:
            name = info.get("Name", "")
            text = clean(flatten(info.get("Value", {})))
            key = {"NFPA Health Rating": "health", "NFPA Fire Rating": "fire", "NFPA Instability Rating": "instability", "NFPA Specific Notice": "special"}.get(name)
            if key and key not in doc.nfpa:
                match = re.match(r"^(\d)", text)
                doc.nfpa[key] = match.group(1) if match else text
                items.append(Item(text=truncate(text, 300), label=name.replace("NFPA ", ""), source=self.source_key(info.get("ReferenceNumber"))))
        doc.add_block(2, Block("NFPA 704 rating", items))


def similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.88


def flatten(value: dict[str, Any]) -> str:
    """Render a PUG-View Value as plain text."""
    if "StringWithMarkup" in value:
        return " ".join(s.get("String", "").strip() for s in value["StringWithMarkup"]).strip()
    if "Number" in value:
        nums = ", ".join(str(n) for n in value["Number"])
        return f"{nums} {value.get('Unit', '')}".strip()
    if "Boolean" in value:
        return ", ".join("Yes" if b else "No" for b in value["Boolean"])
    return ""


def clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("(click each P-code to see the statement)", "").strip()
    # Some ICSC values lose their superscript ("0.2 mg/m3" arrives as "0.2 mg/m").
    text = re.sub(r"\bmg/m$", "mg/m³", text)
    # Drop truncated values such as "Vapor pressure, Pa at 20 °C:".
    return "" if text.endswith(":") else text


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())[:200]


def truncate(text: str, limit: int = MAX_ITEM_CHARS) -> str:
    """Cut long excerpts at a sentence boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind(". ")
    return (cut[: end + 1] if end > limit // 2 else cut.rstrip()) + " …"
