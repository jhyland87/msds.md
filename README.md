# msds.md

An [Obsidian](https://obsidian.md) vault of Safety Data Sheets (SDS/MSDS) in Markdown, generated
from public sources. Every sheet uses the same template. Every sheet contains all 16 sections from
OSHA's [HazCom SDS brief (OSHA 3514)](https://www.osha.gov/sites/default/files/publications/OSHA3514.pdf),
cites a source for each fact, and links to related chemicals.

> [!WARNING]
> These notes are aggregated reference material, **not** a substitute for the SDS that ships with
> your product. Grades, concentrations and suppliers differ. Always check the supplier's SDS.

## Using the vault

Open this folder as a vault in Obsidian. Start at **`SDS/SDS Index.md`**, or open `SDS/SDS.base`
for a sortable table. Each note has:

- a hazard callout with GHS pictograms, H-statements, UN number and NFPA 704 rating
- sections `1. Identification` through `16. Other Information` (sections with no data say so explicitly)
- frontmatter properties (`cas`, `un_number`, `signal_word`, `hazard_codes`, …) for search and Bases
- footnote citations, collected under **Sources** at the bottom
- `[[wikilinks]]` to other chemicals in the vault (e.g. reactivity notes link to [[Water]])

## Generating notes

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

.venv/bin/sds import --all            # regenerate every note from chemicals.yaml
.venv/bin/sds import "Sulfuric acid"  # one chemical
.venv/bin/sds validate                # check sections, links, citations; list data gaps
```

### Importing a whole Wikipedia category

`chemicals.yaml` → `wikipedia_sync` lists category trees to mirror (currently
[Category:Reagents](https://en.wikipedia.org/wiki/Category:Reagents), minus drug, warfare-agent and media
subcategories). `sds wiki-sync` crawls each tree, resolves pages to PubChem through Wikidata, and writes
`manifests/wikipedia-reagents.yaml`. Then run `sds import --all`. Pages without a single PubChem compound
are skipped.

### Writing a note by hand

For mixtures and products with no PubChem record, create a note in `SDS/` with Obsidian's
**Templates: Insert template → SDS** (the core Templates plugin is set to the `Templates/` folder).
Fill in the sections, replace the data-gap callouts you have data for, and cite each fact with
the **SDS source** template. Keep the `manual` tag. `sds validate` checks hand-written notes
with the same rules as generated ones.

### Adding a chemical

```bash
.venv/bin/sds add "Acetone" --category Solvents   # looks up the PubChem CID, appends to chemicals.yaml
.venv/bin/sds import "Acetone"
```

For solutions, commercial grades and mixtures, edit the entry in `chemicals.yaml`: add a
`composition`, a `ghs_source` for the right concentration, and `exclude_sources` for other grades.
Add a `supplier_sds` PDF URL to fill data gaps. The manifest header documents every key. AI agents
can do all of this through the `sds-import` skill.

## Data sources

| Source | Used for |
| --- | --- |
| [PubChem PUG-View](https://pubchem.ncbi.nlm.nih.gov/docs/pug-view) | Primary. It aggregates CAMEO Chemicals (NOAA), NIOSH, ILO ICSC, ECHA, ERG, HSDB and others, keeping each original source for citation. |
| Supplier SDS PDFs | Gap filling, parsed section by section (Loba Chemie, Apollo, Fisher/Acros, Cayman layouts). When PubChem has no GHS label, the sheet's Section 2 provides it. Listed in `chemicals.yaml` or `gap-sources.yaml`; PDFs are cached locally, not committed. |
| Manifest `overrides` | Hand-curated facts for grades and mixtures, each with a cited URL. |
| GHS label fallback | Sections 4–8 and 10–13 with no narrative data list the matching GHS precautionary and hazard statements, cited to the classification source. |
| Wikipedia + Wikidata | `sds wiki-sync` only: category membership, PubChem CID and CAS number. The article is linked in Section 16. |

If the linked PubChem CID has no hazard classification, the importer tries other CIDs with the same CAS
number or name (PubChem often files safety data under an aggregate or salt record) and says so in
Section 16.

## Layout

```
chemicals.yaml      curated manifest of chemicals (edit this)
manifests/          generated manifests (sds wiki-sync)
gap-sources.yaml    supplier SDS PDFs and alternate PubChem records that fill gaps, by note name
Templates/          Obsidian templates; Templates/SDS.md also defines the generated layout
SDS/                notes by category, plus SDS Index.md and SDS.base
assets/ghs/         GHS pictograms
tools/sds/          the generator (Python)
tests/              pytest suite
.claude/skills/     agent skills: sds-import, sds-review, obsidian-markdown, obsidian-bases
AGENTS.md           conventions and rules for AI agents (CLAUDE.md imports it)
```

The `obsidian-markdown` and `obsidian-bases` skills are vendored from
[kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) (MIT, commit `3ccff53`).
