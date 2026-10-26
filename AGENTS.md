# AGENTS.md

Guidance for AI agents working in this repository.

## What this is

An [Obsidian](https://obsidian.md) vault of Safety Data Sheets (SDS) written as Markdown, plus the
Python tool (`sds`) that generates them. Every note follows the 16-section layout from OSHA's
HazCom brief ([OSHA 3514](https://www.osha.gov/sites/default/files/publications/OSHA3514.pdf)) and
cites the sources for its facts.

```
chemicals.yaml         curated manifest (wins over generated ones) + `wikipedia_sync` config
manifests/             generated manifests (`sds wiki-sync`); never edit by hand
gap-sources.yaml       curated supplier SDS PDFs / alternate PubChem CIDs, applied by note name
Templates/             Obsidian templates: SDS.md (full sheet), SDS data gap.md, SDS source.md
tools/sds/             generator package (PubChem / supplier-PDF / Wikipedia adapters, merge, render, CLI)
tools/sds/templates/   sds.md.j2, the Jinja renderer that fills the Templates/SDS.md layout
SDS/<Category>/        notes (generated + hand-written); SDS Index.md and SDS.base
assets/ghs/            GHS pictogram SVGs embedded by notes
cache/                 raw API responses and downloaded PDFs (gitignored)
tests/                 pytest suite
.claude/skills/        agent skills (sds-import, sds-review, obsidian-markdown, obsidian-bases)
```

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'   # one-time setup
.venv/bin/sds import --all              # regenerate every note (uses cache/)
.venv/bin/sds import "Sulfuric acid"    # regenerate one note
.venv/bin/sds import --all --refresh    # re-download all sources
.venv/bin/sds add "Acetone" --category Solvents   # PubChem lookup + manifest stub
.venv/bin/sds wiki-sync                 # rebuild manifests/ from the Wikipedia categories in chemicals.yaml
.venv/bin/sds validate [-v]             # structure, links, citations, data-gap report
.venv/bin/pytest                        # unit tests
```

## Rules

1. **Never hand-edit generated notes** (anything listed in a manifest). They are overwritten on the
   next import. Fix data in `chemicals.yaml` (`overrides`, `exclude_sources`, `ghs_source`,
   `supplier_sds`) or the generator, then re-run `sds import`. To customise a generated
   (`manifests/`) entry, copy it into `chemicals.yaml`; curated entries win.
   Chemicals with no PubChem record (named mixtures, media) are written by hand from
   `Templates/SDS.md`, tagged `manual`, and are never overwritten.
2. **Never invent hazard data.** Every fact must come from a source. Manual facts go in
   `overrides` and must cite a key from the manifest's `sources:` block, with a URL.
   If you cannot find a source, leave the gap. The note will show a data-gap callout.
3. **All 16 sections always render.** Missing data shows a `[!warning] Data gap` callout and is
   never silently dropped.
4. **Mixtures and grades differ from the pure compound.** For solutions and grades (e.g. 68% nitric
   acid, RFNA, 32–38% HCl), set `composition`, choose the matching `ghs_source`, and use
   `exclude_sources` / `exclude_property_sources` to drop data about other grades. PubChem often
   mixes the anhydrous gas, spent acid or fuming grades into one record.
5. **Prefer primary and regulatory sources:** CAMEO Chemicals, NIOSH, ILO ICSC, ECHA / EC 1272/2008,
   ERG, then HSDB. Supplier SDS PDFs fill gaps. Cite them, but don't commit the PDFs (they stay in `cache/`).
6. Run `sds validate` (it must report 0 errors) and `pytest` before finishing.

## Note conventions

`Templates/SDS.md` is the source of truth for the layout. The generator reads its section headings,
non-mandatory markers, Section 9 rows and frontmatter key order. `SDS data gap.md` and
`SDS source.md` define the gap callout and the citation line. To change the layout, edit the
template, then run `pytest` and `sds import --all`.

- Path: `SDS/<category>/<name>.md`. The note name is the manifest `name`, which is also the wikilink target.
- Frontmatter: `title, aliases, cas, ec_number, pubchem_cid, formula, un_number, category,
  signal_word, ghs_pictograms, hazard_codes, nfpa_*, tags (always includes sds), generated`.
- Headings: `## 1. Identification` … `## 16. Other Information`, then optional `## Related`,
  then `## Sources`, which holds the footnote definitions `[^n]`.
- Cross-links: the first mention of another vault chemical in each section becomes a
  `[[wikilink]]`. Names come from each manifest entry's `name` and `aliases`.
- Obsidian syntax (callouts, embeds, properties, Bases) is covered by the `obsidian-markdown` and
  `obsidian-bases` skills.

## Code style

Python ≥ 3.11, type hints, dataclasses, small modules. Match the existing docstring and comment
density. Keep comments short. Section and property mappings live in data tables
(`SECTION_MAP`, `PROPERTY_MAP`, `PROPERTY_RULES`). Extend those instead of adding special cases.
