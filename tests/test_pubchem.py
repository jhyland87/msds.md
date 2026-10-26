from sds.model import SdsDocument
from sds.sources.pubchem import PubChemRecord, statement_text


def swm(text, markup=None):
    return {"StringWithMarkup": [{"String": text, **({"Markup": markup} if markup else {})}]}


def section(heading, info=None, children=None):
    sec = {"TOCHeading": heading}
    if info:
        sec["Information"] = info
    if children:
        sec["Section"] = children
    return sec


RECORD = {
    "Record": {
        "RecordNumber": 1,
        "RecordTitle": "Testacid",
        "Reference": [
            {"ReferenceNumber": 1, "SourceName": "CAMEO Chemicals", "Name": "TESTACID", "URL": "https://cameo.example/1"},
            {"ReferenceNumber": 2, "SourceName": "CAMEO Chemicals", "Name": "TESTACID, SPENT", "URL": "https://cameo.example/2"},
            {"ReferenceNumber": 3, "SourceName": "European Chemicals Agency (ECHA)", "Name": "Testacid", "URL": "https://echa.example"},
            {"ReferenceNumber": 4, "SourceName": "Pistoia Alliance Chemical Safety Library", "Name": "X + Testacid"},
        ],
        "Section": [
            section(
                "Chemical and Physical Properties",
                children=[
                    section(
                        "Experimental Properties",
                        children=[
                            section(
                                "Boiling Point",
                                [
                                    {"ReferenceNumber": 1, "Value": swm("337 °C")},
                                    {"ReferenceNumber": 2, "Value": swm("300 °C")},
                                    {"ReferenceNumber": 3, "Value": {"Number": [337]}},
                                ],
                            )
                        ],
                    )
                ],
            ),
            section(
                "Safety and Hazards",
                children=[
                    section(
                        "Hazards Identification",
                        children=[
                            section(
                                "GHS Classification",
                                [
                                    {
                                        "ReferenceNumber": 3,
                                        "Name": "Pictogram(s)",
                                        "Value": swm(" ", [{"URL": "https://pubchem.ncbi.nlm.nih.gov/images/ghs/GHS05.svg", "Extra": "Corrosive"}]),
                                    },
                                    {"ReferenceNumber": 3, "Name": "Signal", "Value": swm("Danger")},
                                    {
                                        "ReferenceNumber": 3,
                                        "Name": "GHS Hazard Statements",
                                        "Value": swm("H314 (98.5%): Causes severe skin burns and eye damage [Danger Skin corrosion]"),
                                    },
                                    {
                                        "ReferenceNumber": 3,
                                        "Name": "Precautionary Statement Codes",
                                        "Value": swm("P260, P301+P330+P331, and P501 (click each P-code to see the statement)"),
                                    },
                                ],
                            )
                        ],
                    ),
                    section(
                        "First Aid Measures",
                        children=[
                            section(
                                "First Aid",
                                [
                                    {"ReferenceNumber": 1, "Value": swm("Flush with water.")},
                                    {"ReferenceNumber": 4, "Value": swm("Incident report text.")},
                                ],
                            )
                        ],
                    ),
                ],
            ),
        ],
    }
}


def make_doc(excludes=None):
    doc = SdsDocument(name="Testacid", category="Acids")
    record = PubChemRecord(RECORD, excludes or [], "2026-01-01")
    record.populate(doc, {"P260": "Do not breathe dust.", "P501": "Dispose of contents."})
    return doc, record


def test_ghs_parsing_strips_notification_share():
    doc, _ = make_doc()
    assert doc.ghs.signal_word == "Danger"
    assert doc.ghs.pictograms == [("GHS05", "Corrosive")]
    code, text = doc.ghs.hazard_statements[0]
    assert code == "H314"
    assert text == "Causes severe skin burns and eye damage (98.5% of ECHA notifications)"
    assert doc.ghs.precautionary_codes == ["P260", "P301+P330+P331", "P501"]


def test_first_aid_maps_to_section_4_and_skips_default_excludes():
    doc, _ = make_doc()
    texts = [i.text for b in doc.sections[4] for i in b.items]
    assert texts == ["Flush with water."]


def test_manifest_excludes_and_unitless_numbers_are_filtered():
    doc, record = make_doc(excludes=["SPENT"])
    values = [i.text for i in doc.properties["Boiling point"]]
    assert values == ["337 °C"]
    assert all(s.key != "pubchem-1-ref2" for s in record.sources())


def test_sources_only_include_used_references():
    _, record = make_doc()
    keys = {s.key for s in record.sources()}
    assert "pubchem-1-ref1" in keys
    assert "pubchem-1-ref4" not in keys


def test_combined_precautionary_statement_text():
    codes = {"P301": "IF SWALLOWED:", "P330": "Rinse mouth."}
    assert statement_text("P301+P330", codes) == "IF SWALLOWED: Rinse mouth."


def test_best_alternate_cid_prefers_ghs_then_most_safety_data(monkeypatch):
    from sds.sources import pubchem

    views = {
        "cas-1-2-3.json": {"IdentifierList": {"CID": [10, 20, 30]}},
        "name-Foo.json": {"IdentifierList": {"CID": [40]}},
        "safety-10.json": {},
        "safety-20.json": {"Record": {"Section": [{"Information": [1, 2, 3]}]}},
        "safety-30.json": {"Record": {"Section": [{"Information": [1]}]}},
        "safety-40.json": {"Record": {"Section": [{"TOCHeading": "GHS Classification", "Information": [1]}]}},
    }
    monkeypatch.setattr(pubchem, "fetch_json", lambda url, cache, key, refresh=False: views[key.split("/")[-1]])
    assert pubchem.best_alternate_cid(10, "1-2-3", "Foo", "unused") == 40
    views["safety-40.json"] = {}
    assert pubchem.best_alternate_cid(10, "1-2-3", "Foo", "unused") == 20
