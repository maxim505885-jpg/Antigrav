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
