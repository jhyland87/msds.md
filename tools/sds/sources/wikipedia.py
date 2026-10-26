"""Build a manifest from a Wikipedia category tree.

Pages are resolved to PubChem CIDs and CAS numbers through Wikidata (P662 and P231).
Pages without a CID (mixtures, culture media, concept articles) are skipped.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import requests

from ..http import USER_AGENT, fetch_json
from ..naming import choose_name, is_abbreviation

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
PAGE_URL = "https://en.wikipedia.org/wiki/{title}"
PUG_SYNONYMS = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON"
PUG_TITLE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/Title/JSON"
# Characters Obsidian can't use in note names or wikilinks.
UNSAFE_NAME = re.compile(r'[\\/:*?"<>|#^\[\]]')


@dataclass
class SyncConfig:
    """One `wikipedia_sync` entry from chemicals.yaml."""

    category: str
    output: str
    folder: str = "Reagents"
    exclude_categories: list[str] = field(default_factory=list)
    # Wikipedia category -> vault folder (relative to `folder`).
    folders: dict[str, str] = field(default_factory=dict)


@dataclass
class Page:
    title: str
    categories: list[str]
    qid: str | None = None
    cid: int | None = None
    cas: str | None = None
    label: str | None = None  # Wikidata English label


class WikiClient:
    """Minimal MediaWiki client: throttled, with 429 backoff."""

    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(6):
            time.sleep(self.delay)
            resp = self.session.get(url, params={**params, "format": "json"}, timeout=60)
            if resp.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"Rate limited by {url}")

    def category_members(self, category: str) -> list[dict[str, Any]]:
        members: list[dict[str, Any]] = []
        cont: dict[str, str] = {}
        while True:
            data = self.get(
                WIKIPEDIA_API,
                {"action": "query", "list": "categorymembers", "cmtitle": category, "cmlimit": 500, **cont},
            )
            members.extend(data["query"]["categorymembers"])
            if "continue" not in data:
                return members
            cont = data["continue"]


def crawl(client: WikiClient, root: str, exclude: set[str]) -> tuple[dict[str, Page], dict[str, str]]:
    """Walk a category tree. Returns (pages by title, parent category of each category)."""
    pages: dict[str, Page] = {}
    parents: dict[str, str] = {}
    seen: set[str] = set()
    stack = [root]
    while stack:
        cat = stack.pop()
        if cat in seen or cat in exclude:
            continue
        seen.add(cat)
        for member in client.category_members(cat):
            title = member["title"]
            if member["ns"] == 14:
                parents.setdefault(title, cat)
                stack.append(title)
            elif member["ns"] == 0:
                pages.setdefault(title, Page(title, [])).categories.append(cat)
    return pages, parents


def chunks(items: list[str], size: int = 50) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def resolve(client: WikiClient, pages: dict[str, Page]) -> None:
    """Fill in Wikidata QID, PubChem CID and CAS for each page."""
    for batch in chunks(sorted(pages)):
        data = client.get(
            WIKIPEDIA_API,
            {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item", "titles": "|".join(batch)},
        )
        normalized = {n["to"]: n["from"] for n in data["query"].get("normalized", [])}
        for page in data["query"]["pages"].values():
            title = normalized.get(page["title"], page["title"])
            if title in pages:
                pages[title].qid = page.get("pageprops", {}).get("wikibase_item")

    by_qid = {p.qid: p for p in pages.values() if p.qid}
    for batch in chunks(sorted(by_qid)):
        data = client.get(
            WIKIDATA_API,
            {"action": "wbgetentities", "ids": "|".join(batch), "props": "claims|labels", "languages": "en"},
        )
        for qid, entity in data.get("entities", {}).items():
            page = by_qid[qid]
            cids = claim_values(entity, "P662")
            cas = claim_values(entity, "P231")
            page.cid = int(cids[0]) if cids and cids[0].isdigit() else None
            page.cas = cas[0] if cas else None
            page.label = entity.get("labels", {}).get("en", {}).get("value")


def claim_values(entity: dict[str, Any], prop: str) -> list[str]:
    values = []
    for claim in entity.get("claims", {}).get(prop, []):
        value = claim["mainsnak"].get("datavalue", {}).get("value")
        if isinstance(value, str):
            values.append(value)
    return values


def depth(category: str, parents: dict[str, str]) -> int:
    n = 0
    while category in parents:
        category = parents[category]
        n += 1
    return n


def folder_for(page: Page, parents: dict[str, str], config: SyncConfig) -> str:
    """Vault folder from the page's most specific category."""
    category = max(page.categories, key=lambda c: depth(c, parents))
    # Use the nearest mapped ancestor so related subcategories share a folder.
    node: str | None = category
    while node is not None:
        if node in config.folders:
            return f"{config.folder}/{config.folders[node]}" if config.folders[node] else config.folder
        node = parents.get(node)
    return f"{config.folder}/{category.removeprefix('Category:').capitalize()}"


def note_name(title: str) -> str:
    return UNSAFE_NAME.sub("-", title).strip()


def full_name(page: Page, title: str, cache: str) -> str | None:
    """Readable name for an abbreviation-titled page (see naming.choose_name)."""
    data = fetch_json(PUG_SYNONYMS.format(cid=page.cid), cache, f"pubchem/synonyms-{page.cid}.json")
    info = data.get("InformationList", {}).get("Information", [{}]) if isinstance(data, dict) else [{}]
    synonyms = info[0].get("Synonym", [])[:25]
    props = fetch_json(PUG_TITLE.format(cid=page.cid), cache, f"pubchem/title-{page.cid}.json")
    rows = props.get("PropertyTable", {}).get("Properties", [{}]) if isinstance(props, dict) else [{}]
    return choose_name(title, page.label, rows[0].get("Title"), synonyms)


def build_entries(
    config: SyncConfig,
    taken_names: set[str],
    taken_cids: set[int],
    cache: str,
) -> tuple[list[dict[str, Any]], int]:
    """Crawl, resolve and return manifest entries plus the count of skipped pages."""
    client = WikiClient()
    pages, parents = crawl(client, config.category, set(config.exclude_categories))
    resolve(client, pages)
    entries: list[dict[str, Any]] = []
    skipped = 0
    names = {n.lower() for n in taken_names}
    cids = set(taken_cids)
    for title in sorted(pages):
        page = pages[title]
        name = note_name(title)
        aliases: list[str] = []
        if page.cid is not None and is_abbreviation(title):
            better = full_name(page, title, cache)
            if better:
                name, aliases = note_name(better), [title]
        if page.cid is None or page.cid in cids or name.lower() in names:
            skipped += 1
            continue
        cids.add(page.cid)
        names.add(name.lower())
        entry: dict[str, Any] = {
            "name": name,
            "category": folder_for(page, parents, config),
            "pubchem_cid": page.cid,
        }
        if aliases:
            entry["aliases"] = aliases
        if page.cas:
            entry["cas"] = page.cas
        entry["wikipedia"] = PAGE_URL.format(title=title.replace(" ", "_"))
        entry["tags"] = ["reagent"]
        entries.append(entry)
    return entries, skipped
