"""Command-line entry point: `sds import | validate | index | add | assets | wiki-sync`."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

from .http import fetch_bytes
from .linker import Linker
from .manifest import Manifest, load_manifest
from .merge import build_document
from .model import SECTION_TITLES
from .render import GAP_TEXT, Renderer
from .sources.pubchem import load_ghs_codes, lookup_cid
from .sources.wikipedia import SyncConfig, build_entries

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "chemicals.yaml"
VAULT = ROOT / "SDS"
ASSETS = ROOT / "assets" / "ghs"
GHS_SVG = "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS{n:02d}.svg"


def note_path(name: str, category: str) -> Path:
    return VAULT / category / f"{name}.md"


def build_linker(manifest: Manifest) -> Linker:
    aliases: dict[str, str] = {}
    for chem in manifest.chemicals:
        for alias in [chem.name, *chem.aliases]:
            aliases[alias.lower()] = chem.name
    return Linker(aliases)


def cmd_assets(_: argparse.Namespace) -> int:
    """Download the nine GHS pictograms used by note embeds."""
    ASSETS.mkdir(parents=True, exist_ok=True)
    for n in range(1, 10):
        path = fetch_bytes(GHS_SVG.format(n=n), str(ROOT / "cache"), f"ghs/GHS{n:02d}.svg")
        (ASSETS / f"GHS{n:02d}.svg").write_bytes(path.read_bytes())
    print(f"Wrote 9 pictograms to {ASSETS.relative_to(ROOT)}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    manifest = load_manifest(MANIFEST)
    if args.all:
        targets = manifest.chemicals
    else:
        targets = []
        for name in args.names:
            chem = manifest.get(name)
            if chem is None:
                print(f"error: '{name}' is not in any manifest (try `sds add \"{name}\"`)", file=sys.stderr)
                return 1
            targets.append(chem)
    if not targets:
        print("Nothing to import: pass chemical names or --all", file=sys.stderr)
        return 1

    if not any(ASSETS.glob("GHS*.svg")):
        cmd_assets(args)
    renderer = Renderer(build_linker(manifest), load_ghs_codes(str(ROOT / "cache")), manifest.emergency_contacts)
    failures: list[str] = []
    for n, chem in enumerate(targets, 1):
        prefix = f"[{n}/{len(targets)}]" if len(targets) > 1 else ""
        try:
            doc = build_document(chem, manifest, ROOT, refresh=args.refresh)
            path = note_path(chem.name, chem.category)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(renderer.render(doc))
        except Exception as err:  # keep going: one bad record shouldn't stop a bulk import
            failures.append(f"{chem.name}: {type(err).__name__}: {err}")
            print(f"{prefix} ✗ {chem.name}: {err}", flush=True)
            continue
        gaps = [s for s in SECTION_TITLES if not doc.sections.get(s) and s not in (1, 2, 3, 9, 16)]
        gap_note = f" (data gaps in sections {', '.join(map(str, gaps))})" if gaps else ""
        print(f"{prefix} ✓ {path.relative_to(ROOT)}{gap_note}", flush=True)
    if args.all:
        prune_stale(manifest, delete=args.prune)
    write_index(manifest)
    if failures:
        print(f"\n{len(failures)} failed:\n  " + "\n  ".join(failures))
    return 1 if failures else 0


def prune_stale(manifest: Manifest, delete: bool) -> None:
    """Report (or with --prune, delete) generated notes no manifest lists any more.

    Hand-written notes (tagged `manual`) are never touched.
    """
    expected = {note_path(c.name, c.category) for c in manifest.chemicals}
    for path in sorted(VAULT.rglob("*.md")):
        if path in expected or path.name == "SDS Index.md":
            continue
        fm = read_frontmatter(path.read_text())
        if "manual" in (fm.get("tags") or []) or "generated" not in fm:
            continue
        rel = path.relative_to(ROOT)
        if delete:
            path.unlink()
            print(f"pruned {rel}")
        else:
            print(f"stale: {rel} (no longer in a manifest; re-run with --prune to delete)")


def read_frontmatter(text: str) -> dict:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return yaml.safe_load(match.group(1)) if match else {}


def write_index(manifest: Manifest) -> None:
    """Regenerate the SDS index note and the Obsidian Base view."""
    rows = []
    for chem in sorted(manifest.chemicals, key=lambda c: (c.category, c.name)):
        path = note_path(chem.name, chem.category)
        if not path.exists():
            continue
        fm = read_frontmatter(path.read_text())
        pictos = " ".join(f"![[{p}.svg|24]]" for p in fm.get("ghs_pictograms", []))
        rows.append(
            f"| [[{chem.name}]] | {chem.category} | {fm.get('cas', '')} | {fm.get('un_number', '')} "
            f"| {fm.get('signal_word', '')} | {pictos} |"
        )
    index = [
        "---",
        "tags: [sds-index]",
        "---",
        "",
        "# SDS Index",
        "",
        "Generated by `sds import`. Do not edit by hand.",
        "",
        "| Chemical | Category | CAS | UN | Signal word | Pictograms |",
        "| --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
        "Open [[SDS.base]] for a sortable and filterable table view.",
        "",
    ]
    (VAULT / "SDS Index.md").write_text("\n".join(index))
    base = {
        "filters": {"and": ['file.hasTag("sds")', 'file.inFolder("SDS")']},
        "views": [
            {
                "type": "table",
                "name": "All SDS",
                "order": ["file.name", "category", "cas", "un_number", "signal_word", "hazard_codes", "nfpa_health", "nfpa_fire", "nfpa_instability"],
                "groupBy": {"property": "category", "direction": "ASC"},
            }
        ],
    }
    (VAULT / "SDS.base").write_text(yaml.safe_dump(base, sort_keys=False))


def cmd_validate(args: argparse.Namespace) -> int:
    """Check every generated note against the vault conventions."""
    manifest = load_manifest(MANIFEST)
    notes = {p.stem for p in VAULT.rglob("*.md")} | {p.name for p in VAULT.rglob("*.base")}
    assets = {p.name for p in ASSETS.glob("*.svg")}
    errors: list[str] = []
    warnings: list[str] = []
    expected = {note_path(c.name, c.category): c for c in manifest.chemicals}
    for path, chem in expected.items():
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing (run `sds import \"{chem.name}\"`)")
    # Hand-written notes (made from Templates/SDS.md) follow the same rules.
    manual = [p for p in VAULT.rglob("*.md") if p not in expected and p.name != "SDS Index.md"]
    for path in [p for p in expected if p.exists()] + manual:
        rel = path.relative_to(ROOT)
        text = path.read_text()
        try:
            fm = read_frontmatter(text)
        except yaml.YAMLError as err:
            errors.append(f"{rel}: frontmatter does not parse ({err})")
            fm = {}
        for key in ("category", "tags"):
            if not fm.get(key):
                errors.append(f"{rel}: frontmatter missing '{key}'")
        if not fm.get("cas"):
            warnings.append(f"{rel}: no CAS number found")
        for n, title in SECTION_TITLES.items():
            if f"## {n}. {title}" not in text:
                errors.append(f"{rel}: missing section heading '## {n}. {title}'")
        if "\n## Sources" not in text:
            errors.append(f"{rel}: missing '## Sources'")
        refs = set(re.findall(r"\[\^(\d+)\](?!:)", text))
        defs = set(re.findall(r"^\[\^(\d+)\]:", text, re.M))
        if not defs:
            errors.append(f"{rel}: no sources cited")
        for missing in sorted(refs - defs, key=int):
            errors.append(f"{rel}: footnote [^{missing}] has no definition")
        for target in re.findall(r"\[\[([^\]|#]+)", text):
            if target not in notes and target not in assets:
                errors.append(f"{rel}: broken link [[{target}]]")
        sections = re.split(r"^## ", text, flags=re.M)
        for sec in sections:
            if GAP_TEXT in sec:
                warnings.append(f"{rel}: data gap in section {sec.split('.', 1)[0]}")
    if args.verbose:
        for w in warnings:
            print(f"warning: {w}")
    else:
        kinds = Counter(re.sub(r"^.*?: ", "", w).split(" in section")[0] for w in warnings)
        for kind, count in kinds.most_common():
            print(f"warning: {count} × {kind} (use --verbose to list)")
    for e in errors:
        print(f"error: {e}")
    checked = sum(1 for p in expected if p.exists()) + len(manual)
    print(f"{checked} notes checked ({len(manual)} hand-written), {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def cmd_index(_: argparse.Namespace) -> int:
    write_index(load_manifest(MANIFEST))
    print("Wrote SDS/SDS Index.md and SDS/SDS.base")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Append a manifest stub for a new chemical after resolving its CID."""
    manifest = load_manifest(MANIFEST)
    if manifest.get(args.name):
        print(f"'{args.name}' is already in chemicals.yaml")
        return 1
    cid = lookup_cid(args.name, str(ROOT / "cache"))
    if cid is None:
        print(f"PubChem has no compound named '{args.name}'. Add it by hand with a CID or supplier SDS.", file=sys.stderr)
        return 1
    # `chemicals:` is the last key in the manifest, so appending keeps it valid.
    with MANIFEST.open("a") as fh:
        fh.write(f"\n  - name: {args.name}\n    category: {args.category}\n    pubchem_cid: {cid}\n")
    print(f"Added '{args.name}' (CID {cid}) to chemicals.yaml. Fill in cas/un_number, then run `sds import \"{args.name}\"`.")
    return 0


def cmd_wiki_sync(_: argparse.Namespace) -> int:
    """Regenerate manifests from the `wikipedia_sync` entries in chemicals.yaml."""
    manifest = load_manifest(MANIFEST, include_generated=False)
    if not manifest.wikipedia_sync:
        print("No `wikipedia_sync` entries in chemicals.yaml", file=sys.stderr)
        return 1
    taken_names = {c.name for c in manifest.chemicals}
    taken_cids = {c.pubchem_cid for c in manifest.chemicals if c.pubchem_cid}
    for raw in manifest.wikipedia_sync:
        config = SyncConfig(**raw)
        print(f"Crawling {config.category} (this takes a few minutes)…", flush=True)
        entries, skipped = build_entries(config, taken_names, taken_cids, str(ROOT / "cache"))
        out = ROOT / config.output
        out.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# Generated by `sds wiki-sync` from {config.category}. Do not edit by hand:\n"
            "# fix entries by copying them into chemicals.yaml (curated entries win).\n"
        )
        out.write_text(header + yaml.safe_dump({"chemicals": entries}, sort_keys=False, allow_unicode=True, width=1000))
        taken_names |= {e["name"] for e in entries}
        taken_cids |= {e["pubchem_cid"] for e in entries}
        print(f"Wrote {len(entries)} chemicals to {config.output} ({skipped} pages skipped: no PubChem CID or duplicate)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sds", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="fetch sources and (re)generate notes")
    p_import.add_argument("names", nargs="*", help="chemical names from chemicals.yaml")
    p_import.add_argument("--all", action="store_true", help="import every chemical in the manifest")
    p_import.add_argument("--refresh", action="store_true", help="ignore the cache and re-download sources")
    p_import.add_argument("--prune", action="store_true", help="with --all, delete generated notes no manifest lists")
    p_import.set_defaults(func=cmd_import)

    p_add = sub.add_parser("add", help="add a chemical to chemicals.yaml via PubChem lookup")
    p_add.add_argument("name")
    p_add.add_argument("--category", default="Uncategorized")
    p_add.set_defaults(func=cmd_add)

    p_validate = sub.add_parser("validate", help="check notes for required sections, sources and links")
    p_validate.add_argument("-v", "--verbose", action="store_true", help="list every warning")
    p_validate.set_defaults(func=cmd_validate)
    sub.add_parser("index", help="regenerate the SDS index note and base").set_defaults(func=cmd_index)
    sub.add_parser("assets", help="download GHS pictograms").set_defaults(func=cmd_assets)
    sub.add_parser("wiki-sync", help="build manifests from Wikipedia categories (see chemicals.yaml)").set_defaults(func=cmd_wiki_sync)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
