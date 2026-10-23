import pytest

from scan2bim.structure.gost_catalog import GOST_STEEL_CATALOG, match_steel_profile


def test_catalog_is_a_cited_partial_excerpt_of_current_i_beam_standard():
    assert len(GOST_STEEL_CATALOG) >= 10
    assert {profile.standard for profile in GOST_STEEL_CATALOG} == {"ГОСТ 35087-2024"}
    assert all(profile.source_url.startswith("https://protect.gost.ru/") for profile in GOST_STEEL_CATALOG)
    assert all(profile.review_required for profile in GOST_STEEL_CATALOG)


def test_30k1_dimensions_and_mass_match_gost_35087_2024():
    profile = next(item for item in GOST_STEEL_CATALOG if item.designation == "30К1")
    assert (profile.height_mm, profile.width_mm) == (298.0, 299.0)
    assert (profile.web_thickness_mm, profile.flange_thickness_mm) == (9.0, 14.0)
    assert profile.mass_kg_m == 87.0


def test_match_returns_review_only_candidates_without_fake_confidence():
    matches = match_steel_profile(298.0, 299.0, 9.0, 14.0, profile_type="i_beam")

    assert matches
    assert matches[0]["profile"]["designation"] == "30К1"
    assert matches[0]["review_required"] is True
    assert matches[0]["catalog_status"] == "base_edition_only_latest_corrections_unverified"
    assert matches[0]["ranking_score_mm"] == 0.0
    assert "match_confidence" not in matches[0]


def test_match_refuses_non_finite_or_non_positive_dimensions():
    for dims in ((0.0, 100.0), (-1.0, 100.0), (float("nan"), 100.0), (100.0, float("inf"))):
        with pytest.raises(ValueError, match="finite positive"):
            match_steel_profile(*dims)


def test_match_refuses_invalid_search_window():
    with pytest.raises(ValueError, match="search windows"):
        match_steel_profile(298.0, 299.0, max_height_diff_mm=-1.0)


def test_box_tube_profiles_are_not_claimed_before_a_cited_assortment_is_added():
    assert match_steel_profile(140.0, 140.0, profile_type="box_tube") == []
