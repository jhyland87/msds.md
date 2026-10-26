import re

from sds.linker import Linker
from sds.model import SECTION_TITLES, Block, Item, SdsDocument, Source
from sds.render import GAP_TEXT, Renderer


def render(doc):
    renderer = Renderer(Linker({"water": "Water"}), {}, [{"name": "Poison", "phone": "123", "source": "pc"}])
    return renderer.render(doc)


def make_doc():
    doc = SdsDocument(name="Testacid", category="Acids", cas="1-2-3")
    doc.sources = {
        "a": Source(key="a", title="Source A", url="https://a.example"),
        "pc": Source(key="pc", title="Poison Control"),
    }
    doc.add_block(4, Block("First aid", [Item("Rinse with water.", source="a")]))
    return doc


def test_all_sixteen_sections_present_with_gap_callouts():
    text = render(make_doc())
    for n, title in SECTION_TITLES.items():
        assert f"## {n}. {title}" in text
    assert GAP_TEXT in text.split("## 5.")[1].split("## 6.")[0]
    assert GAP_TEXT not in text.split("## 4.")[1].split("## 5.")[0]


def test_every_citation_has_a_footnote_under_sources():
    text = render(make_doc())
    refs = set(re.findall(r"\[\^(\d+)\](?!:)", text))
    defs = set(re.findall(r"^\[\^(\d+)\]:", text, re.M))
    assert refs and refs == defs
    assert text.index("## Sources") < text.index("[^1]: ")


def test_frontmatter_and_links():
    text = render(make_doc())
    assert text.startswith("---\ntitle: Testacid\n")
    assert "Rinse with [[Water|water]]." in text
