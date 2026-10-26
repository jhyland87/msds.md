---
name: sds-import
description: Add a chemical to the SDS vault, or refresh an existing one. Resolves it on PubChem, adds a manifest entry, finds a supplier SDS for data gaps, generates the 16-section note and validates it. Use when asked to "add/import an SDS/MSDS for X", "make a note for <chemical>", or to fill data gaps in an existing SDS note.
---

# SDS import

Read `AGENTS.md` first for the repo rules: never hand-edit `SDS/`, never invent data, cite everything.

## Steps

1. **Check the manifests.** Is the chemical already in `chemicals.yaml` or `manifests/*.yaml` (by
   name or alias)? If so, skip to step 5. To fix a generated entry, copy it into `chemicals.yaml`
   first, because curated entries win. With no PubChem compound at all (a named mixture or medium),
   write the note by hand from `Templates/SDS.md` (tag `manual`) and cite every fact.
2. **Identify the exact product.** Decide whether it is a pure substance, a solution or a
   commercial grade (e.g. "37% HCl", "red fuming"). A grade is its own note with its own name.
3. **Add the entry.**
   - Pure substance: `.venv/bin/sds add "<name>" --category "<Category>"`, then edit the stub.
   - Grade or mixture: add the entry by hand. Point `pubchem_cid` at the main component and add
     `composition`.
   - Fill in `cas`, `un_number`, `aliases` (common names and abbreviations that should
     wikilink here), `tags`, and `related` (other vault notes).
   - Reuse an existing `category` folder where one fits (`Acids`, `Reducing Agents`, `General`, …).
4. **Scope the PubChem data** for grades and mixtures:
   - `ghs_source`: a regex picking the right GHS classification. List the candidates with the
     snippet below and pick the entry for this concentration or grade.
   - `exclude_sources`: drop contributors describing other grades (e.g. `SPENT`, `ANHYDROUS`,
     `RED FUMING`). Matched against `"SourceName | Name"` and item labels.
   - `exclude_property_sources`: the same, but only for the Section 9 table.
5. **Import:** `.venv/bin/sds import "<name>"`. The output lists sections with data gaps.
6. **Fill gaps**, best first:
   - Find a supplier SDS PDF that downloads directly (Loba Chemie, Fisher, TCI, Alfa…; Sigma-Aldrich
     blocks scripts). An SDS lookup connector such as SDSentry, if one is connected, can locate one.
     Add it to `gap-sources.yaml` under `supplier_sds` (works for curated and generated entries),
     or as `supplier_sds: [{supplier: ..., url: ...}]` on a `chemicals.yaml` entry, and re-import.
     Name the grade in `supplier` when the sheet is for a solution (e.g. "1.6 M in diethyl ether").
     If PubChem files the hazard data under the commercial salt's record, add a `safety_cid`
     entry to `gap-sources.yaml` instead. The PDF is parsed into all 16
     sections, and its Section 9 values feed the property table.
   - For single facts, add `overrides` (`properties` or `sections`) that cite a `sources:` key. Add
     the source (title and URL) to the top-level `sources:` block.
   - If nothing reliable exists, leave the gap. The callout is the correct output.
7. **Verify:** `.venv/bin/sds validate` must report 0 errors. Read the generated note's header
   callout, Section 2, Section 3 and Section 14. Check them against the sources for the
   right grade, and fix the scoping in step 4 if they are off.

## Listing GHS candidates for a CID

```bash
.venv/bin/python - <<'EOF'
import json, sys; sys.path.insert(0, "tools")
from sds.sources.pubchem import PubChemRecord
r = PubChemRecord(json.load(open("cache/pubchem/<CID>.json")), [], "")
seen = {}
for i in r.infos("Hazards Identification", "GHS Classification"):
    if i.get("Name") == "GHS Hazard Statements":
        seen.setdefault(r.ref_label(i["ReferenceNumber"]), []).extend(s["String"][:5] for s in i["Value"]["StringWithMarkup"])
for label, codes in seen.items(): print(label, codes)
EOF
```

Run `sds import` once first so the record is cached.
