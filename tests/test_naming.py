from sds.naming import choose_name, is_abbreviation


def test_is_abbreviation():
    for name in ["ABCN", "DMTMM", "EPI-001", "PyBOP", "X-Gluc", "P4-t-Bu", "G418", "TosMIC"]:
        assert is_abbreviation(name), name
    for name in ["Sulfuric acid", "Tebbe's reagent", "Methyllithium", "Ninhydrin"]:
        assert not is_abbreviation(name), name


def test_choose_name_order_and_rejections():
    # Wikidata label is just the abbreviation -> PubChem title wins.
    assert choose_name("ABCN", "ABCN", "1,1'-Azobis(cyclohexanecarbonitrile)", []) == "1,1'-Azobis(cyclohexanecarbonitrile)"
    # Lowercase Wikidata label is capitalised.
    assert choose_name("G418", "geneticin", "Geneticin", []) == "Geneticin"
    # Case-variant title and single-word trade-name synonym are skipped.
    assert choose_name("TEMPO", "TEMPO", "Tempo", ["Tanane", "2,2,6,6-Tetramethyl-1-piperidinyloxy"]) == (
        "2,2,6,6-Tetramethyl-1-piperidinyloxy"
    )
    # CAS-index inversions and mixtures are skipped.
    assert choose_name("HBTU", None, "Methanaminium, N-(x)-, hexafluorophosphate", ["HBTU", "O-(Benzotriazol-1-yl)uronium PF6"]) == (
        "O-(Benzotriazol-1-yl)uronium PF6"
    )
    assert choose_name("MoOPH", "MoOPH", "a;b;c", []) is None
