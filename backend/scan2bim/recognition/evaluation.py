"""Evaluate recognition output against an explicitly supplied reference set.

This module never manufactures workshop truth. Metrics describe only the
reference annotations passed by the caller; synthetic fixtures test the metric
implementation and are not evidence of field accuracy.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment


def _valid_bbox(value: Any, name: str) -> dict[str, list[float]]:
    if not isinstance(value, dict) or not {"min", "max"}.issubset(value):
        raise ValueError(f"{name} must contain min and max")
    result: dict[str, list[float]] = {}
    for bound in ("min", "max"):
        raw = value[bound]
        if not isinstance(raw, (list, tuple)) or len(raw) != 3:
            raise ValueError(f"{name}.{bound} must be a finite 3D point")
        if any(isinstance(item, bool) for item in raw):
            raise ValueError(f"{name}.{bound} must be a finite 3D point")
        try:
            coords = [float(item) for item in raw]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{name}.{bound} must be a finite 3D point") from exc
        if not all(math.isfinite(item) for item in coords):
            raise ValueError(f"{name}.{bound} must be a finite 3D point")
        result[bound] = coords
    if any(result["max"][index] <= result["min"][index] for index in range(3)):
        raise ValueError(f"{name} must have positive volume")
    return result


def _records(items: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError(f"{name} must be a list")
    clean = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{name}[{index}] must be an object")
        record_id = item.get("id")
        class_name = item.get("class_name")
        if not isinstance(record_id, str) or not record_id.strip() or record_id in seen:
            raise ValueError(f"{name}[{index}].id must be unique and non-empty")
        if not isinstance(class_name, str) or not class_name.strip():
            raise ValueError(f"{name}[{index}].class_name must be non-empty")
        seen.add(record_id)
        clean.append({
            "id": record_id,
            "class_name": class_name,
            "bbox": _valid_bbox(item.get("bbox"), f"{name}[{index}].bbox"),
        })
    return clean


def compute_3d_box_iou(bbox_a: dict[str, list[float]], bbox_b: dict[str, list[float]]) -> float:
    """Compute axis-aligned 3D box intersection over union."""
    a = _valid_bbox(bbox_a, "bbox_a")
    b = _valid_bbox(bbox_b, "bbox_b")
    min_a, max_a = np.asarray(a["min"]), np.asarray(a["max"])
    min_b, max_b = np.asarray(b["min"]), np.asarray(b["max"])
    inter_dims = np.maximum(0.0, np.minimum(max_a, max_b) - np.maximum(min_a, min_b))
    intersection = float(np.prod(inter_dims))
    volume_a = float(np.prod(max_a - min_a))
    volume_b = float(np.prod(max_b - min_b))
    union = volume_a + volume_b - intersection
    return intersection / union if union > 0 else 0.0


def evaluate_recognition(
    detected_candidates: list[dict[str, Any]],
    reference_elements: list[dict[str, Any]],
    iou_threshold: float = 0.50,
    reference_set_id: str | None = None,
    reference_kind: str = "unspecified",
) -> dict[str, Any]:
    """Measure one-to-one box matches against caller-supplied reference labels.

    `reference_elements` must contain `{id, class_name, bbox: {min, max}}`.
    The caller is responsible for the independence and provenance of those
    references. This function does not assert that they are physical survey data.
    """
    if isinstance(iou_threshold, bool) or not isinstance(iou_threshold, (int, float)):
        raise ValueError("iou_threshold must be finite and within (0, 1]")
    threshold = float(iou_threshold)
    if not math.isfinite(threshold) or not 0.0 < threshold <= 1.0:
        raise ValueError("iou_threshold must be finite and within (0, 1]")
    if not isinstance(reference_kind, str) or not reference_kind.strip():
        raise ValueError("reference_kind must be non-empty")
    if reference_set_id is not None and (not isinstance(reference_set_id, str) or not reference_set_id.strip()):
        raise ValueError("reference_set_id must be non-empty when supplied")

    detections = _records(detected_candidates, "detected_candidates")
    references = _records(reference_elements, "reference_elements")
    classes = sorted({record["class_name"] for record in detections + references})
    per_class: dict[str, dict[str, Any]] = {}
    total_tp = total_fp = total_fn = 0
    matched_ious: list[float] = []

    for class_name in classes:
        refs = [record for record in references if record["class_name"] == class_name]
        dets = [record for record in detections if record["class_name"] == class_name]
        ious = np.zeros((len(dets), len(refs)), dtype=np.float64)
        for det_idx, det in enumerate(dets):
            for ref_idx, ref in enumerate(refs):
                ious[det_idx, ref_idx] = compute_3d_box_iou(det["bbox"], ref["bbox"])

        # First maximize the number of matches over threshold, then maximize
        # IoU among those matches. Greedy detection order can lose valid matches.
        if ious.size:
            weights = np.where(ious >= threshold, 1_000_000.0 + ious, -1_000_000.0)
            det_indices, ref_indices = linear_sum_assignment(weights, maximize=True)
            matched = [
                (int(det_idx), int(ref_idx), float(ious[det_idx, ref_idx]))
                for det_idx, ref_idx in zip(det_indices, ref_indices)
                if ious[det_idx, ref_idx] >= threshold
            ]
        else:
            matched = []

        tp = len(matched)
        fp = len(dets) - tp
        fn = len(refs) - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        matched_ious.extend(iou for _det, _ref, iou in matched)
        per_class[class_name] = {
            "reference_count": len(refs),
            "detected_count": len(dets),
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

    precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else 0.0
    recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "metric_scope": "caller_supplied_reference_annotations_only",
        "reference_set_id": reference_set_id,
        "reference_kind": reference_kind,
        "reference_element_count": len(references),
        "total_detected_candidates": len(detections),
        "iou_threshold": threshold,
        "mean_matched_iou": round(float(np.mean(matched_ious)), 4) if matched_ious else 0.0,
        "overall_precision": round(precision, 4),
        "overall_recall": round(recall, 4),
        "overall_f1": round(f1, 4),
        "per_class": per_class,
    }
