"""Evaluation and verification metrics for Stage 6 (AI & Geometric Recognition).

Evaluates candidate element detections against the verified workshop ground truth dataset:
- 3D Bounding Box Intersection-over-Union (IoU).
- Per-class and aggregate Detection Precision, Recall, and F1-score.
- Bounding box dimension residuals (length, thickness, height errors in mm/m).
"""
from __future__ import annotations

from typing import Any
import numpy as np

from ..learning.ground_truth import generate_workshop_ground_truth_catalog, GroundTruthElement


def compute_3d_box_iou(bbox_a: dict[str, list[float]], bbox_b: dict[str, list[float]]) -> float:
    """Compute 3D Axis-Aligned Bounding Box (AABB) Intersection over Union."""
    min_a = np.array(bbox_a["min"])
    max_a = np.array(bbox_a["max"])
    min_b = np.array(bbox_b["min"])
    max_b = np.array(bbox_b["max"])

    inter_min = np.maximum(min_a, min_b)
    inter_max = np.minimum(max_a, max_b)
    inter_dims = np.maximum(0.0, inter_max - inter_min)
    intersection_vol = float(np.prod(inter_dims))

    vol_a = float(np.prod(np.maximum(0.0, max_a - min_a)))
    vol_b = float(np.prod(np.maximum(0.0, max_b - min_b)))

    union_vol = vol_a + vol_b - intersection_vol
    if union_vol <= 1e-9:
        return 0.0
    return intersection_vol / union_vol


def evaluate_recognition_against_ground_truth(
    detected_candidates: list[dict[str, Any]],
    iou_threshold: float = 0.50,
) -> dict[str, Any]:
    """Measure precision, recall, F1, and mean IoU against the 106-element workshop ground truth."""
    catalog = generate_workshop_ground_truth_catalog()
    classes = sorted(list({elem.class_name for elem in catalog}))

    metrics_per_class: dict[str, dict[str, Any]] = {}
    total_tp = 0
    total_fp = 0
    total_fn = 0
    matched_ious: list[float] = []

    for cls in classes:
        gt_class = [gt for gt in catalog if gt.class_name == cls]
        det_class = [d for d in detected_candidates if d.get("class_name") == cls]

        # Cost matrix of IoU between detected candidates and ground truth
        matched_gt = set()
        tp = 0
        fp = 0

        for det in det_class:
            det_bbox = det.get("bbox") or {}
            if "min" not in det_bbox or "max" not in det_bbox:
                fp += 1
                continue

            best_iou = 0.0
            best_gt_idx = -1

            for idx, gt in enumerate(gt_class):
                if idx in matched_gt:
                    continue
                # Derive ground truth bbox
                half_l = gt.sizes.get("length", 0.3) / 2.0
                half_w = gt.sizes.get("thickness", 0.3) / 2.0
                half_h = gt.sizes.get("height", 3.0) / 2.0
                cx, cy, cz = gt.center
                gt_bbox = {
                    "min": [cx - half_l, cy - half_w, cz - half_h],
                    "max": [cx + half_l, cy + half_w, cz + half_h],
                }

                iou = compute_3d_box_iou(det_bbox, gt_bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_gt_idx = idx

            if best_iou >= iou_threshold and best_gt_idx >= 0:
                matched_gt.add(best_gt_idx)
                matched_ious.append(best_iou)
                tp += 1
            else:
                fp += 1

        fn = len(gt_class) - len(matched_gt)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        metrics_per_class[cls] = {
            "ground_truth_count": len(gt_class),
            "detected_count": len(det_class),
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

        total_tp += tp
        total_fp += fp
        total_fn += fn

    global_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    global_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    global_f1 = (
        (2 * global_precision * global_recall) / (global_precision + global_recall)
        if (global_precision + global_recall) > 0
        else 0.0
    )
    mean_iou = float(np.mean(matched_ious)) if matched_ious else 0.0

    return {
        "benchmark_dataset_elements": len(catalog),
        "total_detected_candidates": len(detected_candidates),
        "iou_threshold": iou_threshold,
        "mean_matched_iou": round(mean_iou, 4),
        "overall_precision": round(global_precision, 4),
        "overall_recall": round(global_recall, 4),
        "overall_f1": round(global_f1, 4),
        "per_class": metrics_per_class,
    }
