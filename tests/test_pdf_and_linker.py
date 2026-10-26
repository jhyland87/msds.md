from sds.linker import Linker
from sds.sources.pdf_sds import lines_to_blocks, property_row, split_sections, strip_repeated_lines


def test_strip_repeated_lines_drops_headers_and_page_counters():
    pages = [
        "ACME SDS\nSECTION 1: Identification\nTrade name : Foo\nwww.acme.com 1/3",
        "ACME SDS\nSECTION 2: Hazards\nSignal word : Danger\nwww.acme.com 2/3",
        "ACME SDS\nSECTION 3: Composition\nCAS No : 1-2-3\nwww.acme.com 3/3",
    ]
    lines = strip_repeated_lines(pages)
    assert "ACME SDS" not in lines
    assert not any(line.startswith("www.acme.com") for line in lines)
    assert split_sections(lines) == {1: ["Trade name : Foo"], 2: ["Signal word : Danger"], 3: ["CAS No : 1-2-3"]}


def test_lines_to_blocks_groups_subsections_and_joins_wrapped_lines():
    lines = [
        "4.1. Description of first aid measures",
        "After inhalation : Remove person to fresh air and keep",
        "comfortable for breathing.",
        "After ingestion : No data available",
        "4.2. Symptoms",
        "No additional information available",
    ]
    blocks = lines_to_blocks(lines, "ACME SDS", "src")
    assert len(blocks) == 1
    assert blocks[0].heading == "Description of first aid measures (ACME SDS)"
    (item,) = blocks[0].items
    assert item.label == "After inhalation"
    assert item.text == "Remove person to fresh air and keep comfortable for breathing."


def test_property_row_mapping():
    assert property_row("Odour threshold") == "Odor threshold"
    assert property_row("Colour") == "Appearance"
    assert property_row("Relative vapour density at 20 °C") == "Vapor density"
    assert property_row("Log Pow") == "Partition coefficient (log Kow)"
    assert property_row("Oxidising properties") is None


def test_linker_links_first_mention_once_and_skips_self():
    linker = Linker({"water": "Water", "nitric acid": "Nitric acid", "red fuming nitric acid": "Red fuming nitric acid"})
    linked: set[str] = set()
    out = linker.link("Add red fuming nitric acid to water, then more water.", "Nitric acid", linked)
    assert out == "Add [[Red fuming nitric acid|red fuming nitric acid]] to [[Water|water]], then more water."
    assert linker.link("nitric acid", "Nitric acid", set()) == "nitric acid"


def test_linker_ignores_hyphenated_words_and_urls():
    linker = Linker({"water": "Water"})
    assert linker.link("WATER-REACTIVE", "X", set()) == "WATER-REACTIVE"
    assert linker.link("see https://example.com/water", "X", set()) == "see https://example.com/water"


def test_split_sections_accepts_supplier_heading_styles():
    lines = [
        "1. Identification", "Product Name Foo",
        "* 2 Hazard(s) identification", "Signal Word",
        "3. Wash hands thoroughly",  # numbered instruction, not a section
        "10Stability and reactivity", "Stable.",
    ]
    assert split_sections(lines) == {
        1: ["Product Name Foo"],
        2: ["Signal Word", "3. Wash hands thoroughly"],
        10: ["Stable."],
    }
