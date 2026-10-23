"""Integration and benchmark evaluation tests for Stage 6 (AI & Geometric Recognition).

Tests:
1. 3D Bounding Box IoU calculation correctness.
2. Full evaluation against 106-element workshop ground truth benchmark.
3. Realistic noisy detection scenario testing precision, recall, and IoU thresholds.
"""
from __future__ import annotations

import copy
import pytest
import numpy as np

from scan2bim.learning.ground_truth import generate_workshop_ground_truth_catalog
from scan2bim.recognition.evaluation import (
    compute_3d_box_iou,
    evaluate_recognition_against_ground_truth,
)


def test_compute_3d_box_iou():
    box_a = {"min": [0.0, 0.0, 0.0], "max": [2.0, 2.0, 2.0]}  # vol = 8.0
    box_b = {"min": [1.0, 0.0, 0.0], "max": [3.0, 2.0, 2.0]}  # vol = 8.0, overlap = 1*2*2 = 4.0
    # union = 8 + 8 - 4 = 12, iou = 4 / 12 = 1/3
    iou = compute_3d_box_iou(box_a, box_b)
    assert np.isclose(iou, 1.0 / 3.0, atol=1e-5)

    # Disjoint boxes
    box_c = {"min": [5.0, 5.0, 5.0], "max": [6.0, 6.0, 6.0]}
    assert compute_3d_box_iou(box_a, box_c) == 0.0


def test_evaluate_recognition_against_ground_truth_perfect():
    catalog = generate_workshop_ground_truth_catalog()
    assert len(catalog) == 106

    candidates = []
    for elem in catalog:
        d = elem.to_dict("proj_test", "cloud_test")
        candidates.append({
            "id": elem.element_id,
            "class_name": elem.class_name,
            "bbox": d["bbox"],
            "confidence": elem.confidence,
        })

    metrics = evaluate_recognition_against_ground_truth(candidates, iou_threshold=0.50)
    assert metrics["benchmark_dataset_elements"] == 106
    assert metrics["total_detected_candidates"] == 106
    assert metrics["overall_precision"] == 1.0
    assert metrics["overall_recall"] == 1.0
    assert metrics["overall_f1"] == 1.0
    assert metrics["mean_matched_iou"] == 1.0

    for cls_name, cls_metrics in metrics["per_class"].items():
        assert cls_metrics["precision"] == 1.0
        assert cls_metrics["recall"] == 1.0
        assert cls_metrics["f1"] == 1.0


def test_evaluate_recognition_with_noise_and_drift():
    catalog = generate_workshop_ground_truth_catalog()

    # Create slightly perturbed candidates (simulating real detector output with up to 5cm drift)
    noisy_candidates = []
    np.random.seed(42)

    for elem in catalog:
        d = elem.to_dict("proj_test", "cloud_test")
        bbox = copy.deepcopy(d["bbox"])
        # Add slight position offset
        shift = np.random.uniform(-0.03, 0.03, 3)
        bbox["min"] = [coord + shift[i] for i, coord in enumerate(bbox["min"])]
        bbox["max"] = [coord + shift[i] for i, coord in enumerate(bbox["max"])]
        noisy_candidates.append({
            "id": elem.element_id,
            "class_name": elem.class_name,
            "bbox": bbox,
            "confidence": elem.confidence,
        })

    # Add 2 false positive spurious noise candidates
    noisy_candidates.append({
        "id": "spurious_col_fp",
        "class_name": "column",
        "bbox": {"min": [100.0, 100.0, 0.0], "max": [100.3, 100.3, 4.0]},
        "confidence": 0.35,
    })

    metrics = evaluate_recognition_against_ground_truth(noisy_candidates, iou_threshold=0.50)
    assert metrics["overall_recall"] == 1.0  # All 106 real elements detected
    assert metrics["overall_precision"] >= 0.95
    assert metrics["overall_f1"] >= 0.95
    assert metrics["mean_matched_iou"] >= 0.70
