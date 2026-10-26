from sds.ghs_fallback import HEADING, fill_from_ghs, h_section, p_section
from sds.model import Block, Ghs, Item, SdsDocument


def test_statement_routing():
    assert p_section("P301+P330+P331") == 4
    assert p_section("P370+P378") == 5
    assert p_section("P391") == 6
    assert p_section("P280") == 8
    assert p_section("P231+P232") == 7
    assert p_section("P402+P404") == 7
    assert p_section("P501") == 13
    assert h_section("H260") == 10
    assert h_section("EUH014") == 10
    assert h_section("H314") == 11
    assert h_section("H410") == 12


def test_fill_only_empty_sections_and_cite_ghs_source():
    doc = SdsDocument(name="X", category="Y")
    doc.ghs = Ghs(
        hazard_statements=[("H314", "Causes severe skin burns")],
        precautionary_codes=["P280", "P301+P330"],
        source="ghs",
    )
    doc.add_block(8, Block("PPE", [Item("Gloves", source="a")]))
    fill_from_ghs(doc, {"P280": "Wear gloves.", "P301": "IF SWALLOWED:", "P330": "Rinse mouth."})

    assert [b.heading for b in doc.sections[8]] == ["PPE"]  # existing data untouched
    (first_aid,) = doc.sections[4]
    assert first_aid.heading == HEADING
    assert first_aid.items[0].text == "IF SWALLOWED: Rinse mouth."
    assert first_aid.items[0].source == "ghs"
    assert doc.sections[11][0].items[0].label == "H314"


def test_no_ghs_source_means_no_fill():
    doc = SdsDocument(name="X", category="Y")
    doc.ghs = Ghs(precautionary_codes=["P280"])
    fill_from_ghs(doc, {"P280": "Wear gloves."})
    assert not doc.sections


def test_ghs_from_supplier_text_uses_official_texts_and_pictograms():
    from sds.ghs_fallback import ghs_from_text

    text = (
        "Signal word Danger Hazard statement(s) H314 Causes burns. H302 Harmful if swallowed. "
        "H331 Toxic if inhaled. P301 + P330 + P331 IF SWALLOWED: rinse."
    )
    codes = {"H314": "Causes severe skin burns and eye damage", "H302": "Harmful if swallowed", "H331": "Toxic if inhaled"}
    pictos = {"H314": ["GHS05"], "H302": ["GHS07"], "H331": ["GHS06"]}
    ghs = ghs_from_text(text, codes, pictos, "sds")
    assert ghs.signal_word == "Danger"
    assert ghs.hazard_statements[0] == ("H314", "Causes severe skin burns and eye damage")
    assert ghs.precautionary_codes == ["P301+P330+P331"]
    assert [p for p, _ in ghs.pictograms] == ["GHS05", "GHS06"]  # GHS07 dropped next to GHS06
    assert ghs.source == "sds"
