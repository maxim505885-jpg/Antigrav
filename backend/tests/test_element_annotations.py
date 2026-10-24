from __future__ import annotations

import pytest

from scan2bim.structure.element_annotations import (
    element_snapshot_sha256,
    evaluate_element_annotations,
    validate_element_annotation,
)


def element(element_id="e-1", class_name="beam", source="geometric"):
    return {
        "id": element_id,
        "class_name": class_name,
        "source": source,
        "bbox": {"min": [0, 0, 0], "max": [6, 0.4, 0.5]},
        "geometry": {"kind": "member", "axis_start": [0, 0.2, 0.25], "axis_end": [6, 0.2, 0.25]},
        "dimensions": {"span_m": 6},
    }


def labeled(**overrides):
    return {
        "annotator": "engineer",
        "state": "labeled",
        "physical_instance_id": "B-01",
        "class_label": "beam",
        "role_label": "crane_girder",
        "type_label": "KB-1",
        "reason": "",
        "note": "reviewed against source cloud",
        **overrides,
    }


def test_validate_independent_beam_role_labels_without_copying_recognition():
    result = validate_element_annotation(labeled())

    assert result["class_label"] == "beam"
    assert result["role_label"] == "crane_girder"
    assert result["physical_instance_id"] == "B-01"


def test_validate_rejects_role_that_conflicts_with_independent_class():
    with pytest.raises(ValueError, match="incompatible"):
        validate_element_annotation(labeled(class_label="column", role_label="crane_girder"))


@pytest.mark.parametrize(("class_label", "role_label"), [
    ("column", "crane_column"),
    ("girder", "crane_girder"),
    ("truss", "truss_web"),
    ("duct", "cable_tray"),
])
def test_validate_accepts_compatible_independent_class_and_role(class_label, role_label):
    assert validate_element_annotation(labeled(class_label=class_label, role_label=role_label))["role_label"] == role_label


@pytest.mark.parametrize("payload", [
    labeled(physical_instance_id=None),
    labeled(class_label="made_up"),
    labeled(class_label="unknown"),
    labeled(role_label="invented_role"),
    labeled(state="unknown", class_label=None, role_label=None, type_label=None, reason=""),
    labeled(state="excluded", class_label=None, role_label=None, type_label=None, note=""),
])
def test_validate_requires_complete_known_independent_labels(payload):
    with pytest.raises(ValueError):
        validate_element_annotation(payload)


def test_snapshot_is_order_independent_and_excludes_invalidated_synthetic_rows():
    rows = [element("a"), element("b", "column"), element("fake", "column", "invalidated_synthetic_ground_truth")]
    digest = element_snapshot_sha256(rows, {"sha256": "cloud-hash"})

    assert digest == element_snapshot_sha256(list(reversed(rows)), {"sha256": "cloud-hash"})
    assert digest != element_snapshot_sha256(rows[:2], {"sha256": "other-cloud"})


def test_snapshot_rejects_duplicate_ids_and_missing_candidates():
    with pytest.raises(ValueError, match="unique"):
        element_snapshot_sha256([element("same"), element("same", "column")])
    with pytest.raises(ValueError, match="no structural"):
        element_snapshot_sha256([element("invalid", source="invalidated_synthetic_ground_truth")])


def test_snapshot_rejects_boolean_coordinates():
    candidate = element()
    candidate["bbox"]["min"][0] = True
    with pytest.raises(ValueError, match="numeric coordinates"):
        element_snapshot_sha256([candidate])


def test_snapshot_accepts_zero_extent_candidate_bounds_for_review():
    candidate = element()
    candidate["bbox"]["max"][1] = candidate["bbox"]["min"][1]

    digest = element_snapshot_sha256([candidate])

    assert len(digest) == 64


def test_role_evaluation_reports_candidate_classification_without_claiming_detector_recall():
    annotations = [
        {"state": "labeled", "class_label": "beam", "role_label": "crane_girder",
         "candidate_context": {"class_name": "beam", "predicted_role": "crane_girder"}},
        {"state": "labeled", "class_label": "beam", "role_label": "rail",
         "candidate_context": {"class_name": "beam", "predicted_role": "crane_girder"}},
        {"state": "excluded", "candidate_context": {"class_name": "duct", "predicted_role": None}},
        {"state": "pending", "candidate_context": {"class_name": "column", "predicted_role": "column"}},
    ]

    report = evaluate_element_annotations(annotations)

    assert report["scope"] == "reviewed_existing_candidates_only"
    assert report["holdout_status"] == "not_declared"
    assert report["reviewed_counts"] == {"labeled": 2, "unknown": 0, "excluded": 1, "pending": 1}
    assert report["candidate_validity"]["reviewed_candidate_validity_rate"] == 0.6667
    assert report["class_metrics"]["accuracy"] == 1.0
    assert report["role_metrics"]["accuracy"] == 0.5
    assert report["role_metrics"]["per_class"]["rail"]["false_negatives"] == 1


def test_role_evaluation_keeps_metrics_null_when_no_candidates_are_labeled():
    report = evaluate_element_annotations([
        {"state": "pending", "candidate_context": {"class_name": "beam", "predicted_role": "crane_girder"}},
        {"state": "unknown", "candidate_context": {"class_name": "beam", "predicted_role": "crane_girder"}},
    ])

    assert report["reviewed_counts"] == {"labeled": 0, "unknown": 1, "excluded": 0, "pending": 1}
    assert report["candidate_validity"]["reviewed_candidate_validity_rate"] is None
    assert report["class_metrics"]["accuracy"] is None
    assert report["role_metrics"]["accuracy"] is None
