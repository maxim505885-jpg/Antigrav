"""Catalog reuse must remain an explained proposal, never a geometry edit."""
from copy import deepcopy

import pytest

from scan2bim.structure.column_type_matching import match_project_column_types


def column(element_id, *, project="p", cloud="scan-new", length=0.502, short=0.4, morphology="solid", coverage=0.9):
    return {"id": element_id, "project_id": project, "cloud_id": cloud, "class_name": "column",
        "measured": True, "inferred": False, "review_status": "unreviewed",
        "geometry": {"kind": "oriented_box", "center": [1, 2, 3], "rotation_z": 1.5707963267948966,
            "sizes": {"length": length, "thickness": short, "height": 6}},
        "dimensions": {"column_type": morphology, "section_coverage": coverage}}


def catalog(type_id="t1", mark="К1"):
    return {"id": type_id, "mark": mark, "project_id": "p", "status": "confirmed",
        "member_element_ids": ["source"], "prototype": {"morphology": "solid",
            "representative_sides_m": {"long": 0.5, "short": 0.4}}}


def run(target, types=None, sources=None):
    return match_project_column_types("p", [target], types or [catalog()],
        sources if sources is not None else [column("source", cloud="scan-old", length=0.5)],
        linear_tolerance_m=0.005, relative_tolerance=0.01)


def test_same_project_catalog_proposes_reuse_with_residuals_and_source_without_mutation():
    target = column("target")
    original = deepcopy(target)
    result = run(target)
    item = result["suggestions"][0]
    assert item["status"] == "match"
    assert item["review_required"] is True
    match = item["matches"][0]
    assert match["type_id"] == "t1" and match["mark"] == "К1"
    assert match["residuals_m"]["long_side_m"] == pytest.approx(0.002)
    assert match["source_cloud_ids"] == ["scan-old"]
    assert item["evidence_coverage"] == 0.9
    assert target == original


def test_foreign_projects_and_unconfirmed_types_are_never_reused():
    foreign = catalog(); foreign["project_id"] = "elsewhere"
    unconfirmed = catalog("t2"); unconfirmed["status"] = "proposed"
    assert run(column("target"), [foreign, unconfirmed])["suggestions"][0]["matches"] == []
    assert run(column("target", project="elsewhere"))["suggestions"] == []


@pytest.mark.parametrize("coverage", [0.1, None])
def test_incomplete_visibility_stays_a_review_item(coverage):
    item = run(column("target", coverage=coverage))["suggestions"][0]
    assert item["status"] == "insufficient_evidence"
    assert item["matches"][0]["type_id"] == "t1"
    assert item["review_required"] is True


def test_two_confirmed_labels_with_same_section_remain_ambiguous():
    result = run(column("target"), [catalog(), catalog("t2", "К2")])
    item = result["suggestions"][0]
    assert item["status"] == "ambiguous"
    assert {m["type_id"] for m in item["matches"]} == {"t1", "t2"}


@pytest.mark.parametrize("change", ["deleted", "rejected", "profile", "dimensions"])
def test_stale_source_members_block_catalog_reuse(change):
    source = column("source", cloud="scan-old", length=0.5)
    if change == "rejected": source["review_status"] = "rejected"
    if change == "profile": source["dimensions"]["column_type"] = "stepped"
    if change == "dimensions": source["geometry"]["sizes"]["length"] = 0.8
    result = run(column("target"), sources=[] if change == "deleted" else [source])
    assert result["suggestions"][0]["matches"] == []
    assert result["catalog_issues"][0]["type_id"] == "t1"


def test_assigned_rejected_inferred_and_incompatible_targets_are_not_recommended():
    assert run(column("source"))["suggestions"] == []
    target = column("target", morphology="stepped")
    assert run(target)["suggestions"][0]["status"] == "unknown"
    target["review_status"] = "rejected"
    assert run(target)["suggestions"] == []
    target["review_status"] = "unreviewed"; target["inferred"] = True
    assert run(target)["suggestions"][0]["status"] == "ineligible"


def test_reuse_is_deterministic_with_ambiguous_catalog_order():
    a, b = catalog(), catalog("t2", "К2")
    assert run(column("target"), [a, b]) == run(column("target"), [b, a])


def test_recognition_conflicts_remain_explicit_review_items():
    target = column("target")
    target["dimensions"]["review_conflict_with"] = ["human-corrected-column"]
    item = run(target)["suggestions"][0]
    assert item["status"] == "insufficient_evidence"
    assert "recognition_conflict" in item["reasons"]
