from __future__ import annotations

import numpy as np
import pytest

from scan2bim.recognition.evaluation import compute_3d_box_iou, evaluate_recognition


def box(x: float, y: float = 0.0, z: float = 0.0, size: float = 1.0):
    half = size / 2.0
    return {
        "min": [x - half, y - half, z - half],
        "max": [x + half, y + half, z + half],
    }


def record(record_id: str, class_name: str, bbox: dict):
    return {"id": record_id, "class_name": class_name, "bbox": bbox}


def test_compute_3d_box_iou():
    a = {"min": [0, 0, 0], "max": [2, 2, 2]}
    b = {"min": [1, 0, 0], "max": [3, 2, 2]}
    assert np.isclose(compute_3d_box_iou(a, b), 1.0 / 3.0, atol=1e-5)
    assert compute_3d_box_iou(a, {"min": [5, 5, 5], "max": [6, 6, 6]}) == 0.0


def test_evaluate_recognition_uses_only_explicit_synthetic_references():
    references = [
        record("fixture-column-1", "column", box(0)),
        record("fixture-column-2", "column", box(4)),
        record("fixture-beam-1", "beam", box(10, size=2)),
    ]
    detections = [
        record("det-column-1", "column", box(0)),
        record("det-column-2", "column", box(4)),
        record("det-beam-1", "beam", box(10, size=2)),
    ]

    metrics = evaluate_recognition(
        detections, references, reference_set_id="test-fixture-v1", reference_kind="synthetic_fixture",
    )
    assert metrics["metric_scope"] == "caller_supplied_reference_annotations_only"
    assert metrics["reference_set_id"] == "test-fixture-v1"
    assert metrics["reference_kind"] == "synthetic_fixture"
    assert metrics["reference_element_count"] == 3
    assert metrics["overall_precision"] == metrics["overall_recall"] == metrics["overall_f1"] == 1.0
    assert metrics["mean_matched_iou"] == 1.0


def test_assignment_maximizes_valid_match_count_before_iou_score():
    references = [
        record("ref-1", "column", {"min": [-1, -0.5, -0.5], "max": [1, 0.5, 0.5]}),
        record("ref-2", "column", {"min": [0.2, -0.5, -0.5], "max": [2.2, 0.5, 0.5]}),
    ]
    detections = [
        record("det-exact-ref-1", "column", references[0]["bbox"]),
        record("det-shifted", "column", {"min": [-1.5, -0.5, -0.5], "max": [0.5, 0.5, 0.5]}),
    ]

    metrics = evaluate_recognition(detections, references, iou_threshold=0.2)
    assert metrics["overall_precision"] == 1.0
    assert metrics["overall_recall"] == 1.0
    assert metrics["per_class"]["column"]["true_positives"] == 2


def test_evaluate_recognition_counts_false_positive_and_false_negative_classes():
    metrics = evaluate_recognition(
        [record("pipe-extra", "pipe", box(100))],
        [record("column-missed", "column", box(0))],
        reference_kind="synthetic_fixture",
    )
    assert metrics["overall_precision"] == 0.0
    assert metrics["overall_recall"] == 0.0
    assert metrics["per_class"]["column"]["false_negatives"] == 1
    assert metrics["per_class"]["pipe"]["false_positives"] == 1


def test_degenerate_detection_geometry_counts_as_false_positive_instead_of_aborting_evaluation():
    detection = record("column-with-flat-box", "column", {
        "min": [0, 0, 0], "max": [0, 1, 2],
    })
    reference = record("physical-column-1", "column", box(0))

    metrics = evaluate_recognition([detection], [reference], reference_kind="field_measurement")

    assert metrics["total_detected_candidates"] == 1
    assert metrics["unscorable_detection_geometry_count"] == 1
    assert metrics["unscorable_detection_ids"] == ["column-with-flat-box"]
    assert "positive volume" in metrics["unscorable_detection_reasons"]["column-with-flat-box"]
    assert metrics["per_class"]["column"]["true_positives"] == 0
    assert metrics["per_class"]["column"]["false_positives"] == 1
    assert metrics["per_class"]["column"]["false_negatives"] == 1
    assert metrics["overall_precision"] == 0.0
    assert metrics["overall_recall"] == 0.0


def test_unscorable_candidate_does_not_displace_a_valid_one_to_one_match():
    reference = record("physical-column-1", "column", box(0))
    detections = [
        record("column-with-flat-box", "column", {"min": [0, 0, 0], "max": [0, 1, 2]}),
        record("column-valid", "column", box(0)),
    ]

    metrics = evaluate_recognition(detections, [reference], reference_kind="field_measurement")

    assert metrics["per_class"]["column"]["true_positives"] == 1
    assert metrics["per_class"]["column"]["false_positives"] == 1
    assert metrics["per_class"]["column"]["false_negatives"] == 0
    assert metrics["overall_precision"] == 0.5
    assert metrics["overall_recall"] == 1.0


def test_member_centerline_extent_matches_independent_physical_bbox_without_claiming_3d_iou():
    detection = {
        **record("brace-axis", "brace", {"min": [1, 0.5, 0.2], "max": [3, 0.5, 2.8]}),
        "geometry": {"kind": "member", "p0": [1, 0.5, 0.2], "p1": [3, 0.5, 2.8]},
    }
    reference = record("physical-brace", "brace", {"min": [0, 0, 0], "max": [4, 1, 3]})

    metrics = evaluate_recognition([detection], [reference], reference_kind="field_measurement")

    assert metrics["per_class"]["brace"]["true_positives"] == 1
    assert metrics["per_class"]["brace"]["false_positives"] == 0
    assert metrics["per_class"]["brace"]["false_negatives"] == 0
    assert metrics["unscorable_detection_geometry_count"] == 1
    assert metrics["centerline_extent_match_count"] == 1
    assert metrics["mean_matched_centerline_extent_iou"] == 0.5
    assert metrics["mean_matched_iou"] is None


def test_member_centerline_outside_reference_bbox_remains_unmatched():
    detection = {
        **record("brace-axis", "brace", {"min": [1, 0.5, 0], "max": [3, 0.5, 3]}),
        "geometry": {"kind": "member", "p0": [1, 0.5, 0], "p1": [3, 0.5, 3]},
    }
    reference = record("physical-brace", "brace", {"min": [0, 0, 0], "max": [4, 1, 1]})

    metrics = evaluate_recognition([detection], [reference], reference_kind="field_measurement")

    assert metrics["per_class"]["brace"]["true_positives"] == 0
    assert metrics["per_class"]["brace"]["false_positives"] == 1
    assert metrics["per_class"]["brace"]["false_negatives"] == 1
    assert metrics["centerline_extent_match_count"] == 0


def test_volumetric_iou_match_is_preferred_over_a_centerline_match_to_the_same_reference():
    reference = record("physical-brace", "brace", box(0))
    line = {
        **record("brace-axis", "brace", {"min": [-0.5, 0, 0], "max": [0.5, 0, 0]}),
        "geometry": {"kind": "member", "p0": [-0.5, 0, 0], "p1": [0.5, 0, 0]},
    }
    volumetric = record("brace-volume", "brace", reference["bbox"])

    metrics = evaluate_recognition([line, volumetric], [reference], reference_kind="field_measurement")

    assert metrics["per_class"]["brace"]["true_positives"] == 1
    assert metrics["per_class"]["brace"]["false_positives"] == 1
    assert metrics["centerline_extent_match_count"] == 0
    assert metrics["mean_matched_iou"] == 1.0


def test_role_metrics_use_only_geometrically_matched_candidates_and_separate_confusions():
    reference = {**record("physical-beam", "beam", box(0, size=2)), "role_label": "crane_girder"}
    detection = {**record("candidate-beam", "beam", box(0, size=2)), "role_name": "purlin"}

    metrics = evaluate_recognition([detection], [reference], reference_kind="field_measurement")

    assert metrics["role_metrics"]["evaluated_reference_count"] == 1
    assert metrics["role_metrics"]["correct_count"] == 0
    assert metrics["role_metrics"]["accuracy"] == 0.0
    assert metrics["role_metrics"]["per_role"]["crane_girder"]["false_negatives"] == 1
    assert metrics["role_metrics"]["per_role"]["purlin"]["false_positives"] == 1


def test_role_metrics_are_undefined_when_physical_references_have_no_role_labels():
    metrics = evaluate_recognition(
        [record("candidate-beam", "beam", box(0))],
        [record("physical-beam", "beam", box(0))],
        reference_kind="field_measurement",
    )

    assert metrics["role_metrics"]["evaluated_reference_count"] == 0
    assert metrics["role_metrics"]["accuracy"] is None
    assert metrics["role_metrics"]["precision"] is None
    assert metrics["role_metrics"]["recall"] is None


def test_empty_reference_and_detection_sets_report_undefined_metrics():
    metrics = evaluate_recognition([], [], reference_kind="pending_reference")

    assert metrics["reference_element_count"] == 0
    assert metrics["total_detected_candidates"] == 0
    assert metrics["mean_matched_iou"] is None
    assert metrics["overall_precision"] is None
    assert metrics["overall_recall"] is None
    assert metrics["overall_f1"] is None


def test_per_class_metrics_are_undefined_when_their_denominator_is_empty():
    metrics = evaluate_recognition(
        [record("det-pipe", "pipe", box(0))], [], reference_kind="pending_reference",
    )

    assert metrics["overall_precision"] == 0.0
    assert metrics["overall_recall"] is None
    assert metrics["overall_f1"] is None
    assert metrics["per_class"]["pipe"]["precision"] == 0.0
    assert metrics["per_class"]["pipe"]["recall"] is None
    assert metrics["per_class"]["pipe"]["f1"] is None


@pytest.mark.parametrize("threshold", [-0.1, 0.0, 1.1, float("nan"), float("inf"), True])
def test_evaluator_rejects_invalid_threshold(threshold):
    with pytest.raises(ValueError, match="iou_threshold"):
        evaluate_recognition([], [], iou_threshold=threshold)


def test_evaluator_rejects_invalid_reference_boxes_and_duplicate_ids():
    with pytest.raises(ValueError, match="positive volume"):
        evaluate_recognition([], [record("ref", "column", {"min": [0, 0, 0], "max": [0, 1, 1]})])
    duplicate = record("same", "column", box(0))
    with pytest.raises(ValueError, match="unique"):
        evaluate_recognition([], [duplicate, duplicate])
