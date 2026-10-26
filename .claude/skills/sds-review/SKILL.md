---
name: sds-review
description: Audit generated SDS notes in this vault for correctness. Checks hazard classification, UN numbers, exposure limits and mixture/grade mix-ups against the cited sources, and fixes problems through chemicals.yaml. Use when asked to review, verify, audit or sanity-check SDS notes, or after importing new chemicals.
---

# SDS review

Read `AGENTS.md` first. Fixes go through `chemicals.yaml` or the generator, never by editing `SDS/`.

## Steps

1. Run `.venv/bin/sds validate` and `.venv/bin/pytest`. Fix every error before reviewing content.
2. For each note under review, check these against the cited sources (open the footnote URLs):
   - **Identity:** CAS, EC and UN numbers match the product and grade. The composition table is
     right for mixtures.
   - **Section 2:** the signal word, pictograms and H-statements belong to the right
     concentration or grade. Watch for PubChem classifications of the anhydrous gas, spent acid,
     oleum or fuming grades showing up on a solution's note.
   - **Section 8:** PEL, REL, TLV and IDLH values and units are plausible and agree across sources.
   - **Section 9:** the values describe this product. Gas-phase data on a solution, or 100% data on
     a 68% solution, means a mix-up.
   - **Section 14:** the UN number and proper shipping name agree with the frontmatter `un_number`.
   - **Contradictions:** when two sources disagree on a value, say so. Don't pick one silently.
   - **CID swaps:** notes whose Section 16 says "Safety data taken from PubChem CID …" borrowed
     data from another record with the same CAS number or name. Confirm that record is the same
     substance (`grep -rl "Safety data taken" SDS`).
   - **"NO GHS DATA FOUND" headers** mean no classification was found, not that the substance
     is safe. These are the first candidates for a `supplier_sds` entry.
3. Fix the cause:
   - Off-grade data → `exclude_sources` / `exclude_property_sources` / `ghs_source`.
   - Wrong or missing fact → a cited `overrides` entry.
   - Systematic mapping problem → `SECTION_MAP` / `PROPERTY_MAP` in `tools/sds/sources/pubchem.py`
     (add a test).
4. Re-run `sds import` and `sds validate`, then report what changed and what remains uncertain.

Report findings as a short list per note: the issue, the evidence (source and value), and the fix
applied or proposed.
