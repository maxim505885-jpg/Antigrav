"""Evaluate recognition output against an explicitly supplied reference set.

This module never manufactures workshop truth. Metrics describe only the
reference annotations passed by the caller; synthetic fixtures test the metric
implementation and are not evidence of field accuracy.
"""
from __future__ import annotations

import math
from collections import Counter
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


def _records(items: list[dict[str, Any]], name: str, *, allow_unscorable_bbox: bool = False) -> list[dict[str, Any]]:
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
        role_name = item.get("role_name", item.get("role_label"))
        if role_name is not None and (not isinstance(role_name, str) or not role_name.strip()):
            if name == "reference_elements":
                raise ValueError(f"{name}[{index}].role_label must be non-empty when supplied")
            role_name = None
        seen.add(record_id)
        try:
            bbox = _valid_bbox(item.get("bbox"), f"{name}[{index}].bbox")
            bbox_error = None
        except ValueError as exc:
            if not allow_unscorable_bbox:
                raise
            bbox = None
            bbox_error = str(exc)
        clean.append({
            "id": record_id,
            "class_name": class_name,
            "bbox": bbox,
            "bbox_error": bbox_error,
            "geometry": item.get("geometry"),
            "role_name": role_name.strip() if isinstance(role_name, str) else None,
        })
    return clean


def _member_centerline(value: Any) -> tuple[list[float], list[float]] | None:
    """Return a finite non-zero member centerline when geometry records one."""
    if not isinstance(value, dict) or value.get("kind") != "member":
        return None
    points = []
    for key in ("p0", "p1"):
        raw = value.get(key)
        if not isinstance(raw, (list, tuple)) or len(raw) != 3 or any(isinstance(item, bool) for item in raw):
            return None
        try:
            point = [float(item) for item in raw]
        except (TypeError, ValueError, OverflowError):
            return None
        if not all(math.isfinite(item) for item in point):
            return None
        points.append(point)
    return (points[0], points[1]) if any(a != b for a, b in zip(*points)) else None


def _centerline_extent_iou(line: tuple[list[float], list[float]], bbox: dict[str, list[float]]) -> float | None:
    """Compare line extents on varying axes; require its center on zero-span axes to lie in the measured box."""
    scores = []
    for axis in range(3):
        line_min = min(line[0][axis], line[1][axis])
        line_max = max(line[0][axis], line[1][axis])
        box_min, box_max = bbox["min"][axis], bbox["max"][axis]
        if line_max - line_min <= 1e-12:
            if not box_min <= line_min <= box_max:
                return None
            continue
        intersection = max(0.0, min(line_max, box_max) - max(line_min, box_min))
        union = (line_max - line_min) + (box_max - box_min) - intersection
        scores.append(intersection / union if union > 0 else 0.0)
    return min(scores) if scores else None


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
    A candidate with `geometry: {kind: "member", p0, p1}` may match a
    measured box by minimum per-axis interval IoU on varying centerline axes;
    constant axes must pass through the box. Such matches are reported
    separately from volumetric 3D IoU.
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

    # Candidates with missing/degenerate geometry stay in the denominator as
    # false positives; malformed boxes must not make a real reference sweep
    # impossible. Independently measured reference boxes remain strict.
    detections = _records(detected_candidates, "detected_candidates", allow_unscorable_bbox=True)
    references = _records(reference_elements, "reference_elements")
    classes = sorted({record["class_name"] for record in detections + references})
    per_class: dict[str, dict[str, Any]] = {}
    total_tp = total_fp = total_fn = 0
    matched_ious: list[float] = []
    total_centerline_matches = 0
    matched_centerline_scores: list[float] = []
    role_references = [item for item in references if item["role_name"] not in (None, "unknown")]
    role_evaluated_classes = {item["class_name"] for item in role_references}
    role_reference_counts = Counter(item["role_name"] for item in role_references)
    role_prediction_counts = Counter(
        item["role_name"] for item in detections
        if item["class_name"] in role_evaluated_classes and item["role_name"] is not None
    )
    role_true_positive_counts: Counter[str] = Counter()

    for class_name in classes:
        refs = [record for record in references if record["class_name"] == class_name]
        dets = [record for record in detections if record["class_name"] == class_name]
        ious = np.zeros((len(dets), len(refs)), dtype=np.float64)
        centerline_scores = np.full((len(dets), len(refs)), -1.0, dtype=np.float64)
        for det_idx, det in enumerate(dets):
            if det["bbox"] is not None:
                for ref_idx, ref in enumerate(refs):
                    ious[det_idx, ref_idx] = compute_3d_box_iou(det["bbox"], ref["bbox"])
                continue
            line = _member_centerline(det["geometry"])
            if line is not None:
                for ref_idx, ref in enumerate(refs):
                    score = _centerline_extent_iou(line, ref["bbox"])
                    if score is not None:
                        centerline_scores[det_idx, ref_idx] = score

        # First maximize the number of matches over threshold, then maximize
        # IoU among volumetric matches. Centerline interval IoU is a separate
        # geometry-specific score and is never presented as 3D box IoU.
        if ious.size:
            iou_matches = ious >= threshold
            centerline_matches = centerline_scores >= threshold
            valid_matches = iou_matches | centerline_matches
            max_matches = max(len(dets), len(refs))
            volume_bonus = max_matches + 1
            cardinality_bonus = (max_matches + 1) ** 2
            weights = np.where(iou_matches, cardinality_bonus + volume_bonus + ious,
                      np.where(centerline_matches, cardinality_bonus + centerline_scores, -cardinality_bonus))
            det_indices, ref_indices = linear_sum_assignment(weights, maximize=True)
            matched = [
                (
                    int(det_idx),
                    int(ref_idx),
                    float(ious[det_idx, ref_idx]) if iou_matches[det_idx, ref_idx] else float(centerline_scores[det_idx, ref_idx]),
                    "box_iou" if iou_matches[det_idx, ref_idx] else "centerline_extent_iou",
                )
                for det_idx, ref_idx in zip(det_indices, ref_indices)
                if valid_matches[det_idx, ref_idx]
            ]
        else:
            matched = []

        tp = len(matched)
        centerline_tp = sum(method == "centerline_extent_iou" for _det, _ref, _iou, method in matched)
        for det_idx, ref_idx, _score, _method in matched:
            det_role = dets[det_idx]["role_name"]
            ref_role = refs[ref_idx]["role_name"]
            if ref_role not in (None, "unknown") and det_role == ref_role:
                role_true_positive_counts[ref_role] += 1
        fp = len(dets) - tp
        fn = len(refs) - tp
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else None
        )
        matched_ious.extend(score for _det, _ref, score, method in matched if method == "box_iou")
        matched_centerline_scores.extend(score for _det, _ref, score, method in matched if method == "centerline_extent_iou")
        per_class[class_name] = {
            "reference_count": len(refs),
            "detected_count": len(dets),
            "unscorable_detection_geometry_count": sum(det["bbox"] is None for det in dets),
            "true_positives": tp,
            "centerline_extent_match_count": centerline_tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1": round(f1, 4) if f1 is not None else None,
        }
        total_tp += tp
        total_fp += fp
        total_fn += fn
        total_centerline_matches += centerline_tp

    precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else None
    recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    role_names = sorted(set(role_reference_counts) | set(role_prediction_counts))
    role_total_tp = sum(role_true_positive_counts.values())
    role_total_fp = sum(role_prediction_counts.values()) - role_total_tp
    role_total_fn = sum(role_reference_counts.values()) - role_total_tp
    role_precision = role_total_tp / (role_total_tp + role_total_fp) if role_total_tp + role_total_fp else None
    role_recall = role_total_tp / (role_total_tp + role_total_fn) if role_total_tp + role_total_fn else None
    role_f1 = (
        2 * role_precision * role_recall / (role_precision + role_recall)
        if role_precision is not None and role_recall is not None and role_precision + role_recall
        else 0.0 if role_precision == 0.0 and role_recall == 0.0
        else None
    )
    per_role = {}
    for role_name in role_names:
        reference_count = role_reference_counts[role_name]
        predicted_count = role_prediction_counts[role_name]
        true_positives = role_true_positive_counts[role_name]
        false_positives = predicted_count - true_positives
        false_negatives = reference_count - true_positives
        precision = true_positives / predicted_count if predicted_count else None
        recall = true_positives / reference_count if reference_count else None
        role_score_f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else 0.0 if precision == 0.0 and recall == 0.0
            else None
        )
        per_role[role_name] = {
            "reference_count": reference_count,
            "predicted_count": predicted_count,
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1": round(role_score_f1, 4) if role_score_f1 is not None else None,
        }
    return {
        "metric_scope": "caller_supplied_reference_annotations_only",
        "reference_set_id": reference_set_id,
        "reference_kind": reference_kind,
        "reference_element_count": len(references),
        "total_detected_candidates": len(detections),
        "unscorable_detection_geometry_count": sum(item["bbox"] is None for item in detections),
        "unscorable_detection_ids": [item["id"] for item in detections if item["bbox"] is None],
        "unscorable_detection_reasons": {
            item["id"]: item["bbox_error"] for item in detections if item["bbox"] is None
        },
        "centerline_containment_match_count": total_centerline_matches,
        "iou_threshold": threshold,
        "mean_matched_iou": round(float(np.mean(matched_ious)), 4) if matched_ious else None,
        "centerline_extent_match_count": total_centerline_matches,
        "mean_matched_centerline_extent_iou": round(float(np.mean(matched_centerline_scores)), 4) if matched_centerline_scores else None,
        "role_metrics": {
            "evaluated_reference_count": len(role_references),
            "evaluated_detection_count": sum(item["class_name"] in role_evaluated_classes for item in detections),
            "unassigned_detection_count": sum(
                item["class_name"] in role_evaluated_classes and item["role_name"] is None for item in detections
            ),
            "correct_count": role_total_tp,
            "accuracy": round(role_total_tp / len(role_references), 4) if role_references else None,
            "precision": round(role_precision, 4) if role_precision is not None else None,
            "recall": round(role_recall, 4) if role_recall is not None else None,
            "f1": round(role_f1, 4) if role_f1 is not None else None,
            "per_role": per_role,
        },
        "overall_precision": round(precision, 4) if precision is not None else None,
        "overall_recall": round(recall, 4) if recall is not None else None,
        "overall_f1": round(f1, 4) if f1 is not None else None,
        "per_class": per_class,
    }
