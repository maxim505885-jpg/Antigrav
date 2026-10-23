import pytest
from scan2bim.structure.gost_catalog import match_steel_profile, GOST_STEEL_CATALOG


def test_gost_catalog_entries():
    assert len(GOST_STEEL_CATALOG) >= 20
    # Spot check 30K1
    k30 = [p for p in GOST_STEEL_CATALOG if p.designation == "30К1"]
    assert len(k30) == 1
    assert k30[0].height_mm == 296.0
    assert k30[0].width_mm == 299.0


def test_match_steel_profile_exact_and_noisy():
    # Test column 30К1 with 2mm measurement error
    matches = match_steel_profile(298.0, 300.0, profile_type="i_beam")
    assert len(matches) > 0
    top = matches[0]
    assert top["profile"]["designation"] in ("30К1", "30К2")
    assert top["residual_mm"] < 10.0
    assert top["match_confidence"] > 0.7


def test_match_box_tube_truss():
    # Square tube 140x140
    matches = match_steel_profile(139.0, 141.0, profile_type="box_tube")
    assert len(matches) > 0
    assert matches[0]["profile"]["designation"] == "Гн.кв. 140х140х5"
