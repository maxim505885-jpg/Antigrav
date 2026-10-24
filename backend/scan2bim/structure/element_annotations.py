"""Independent, immutable semantic annotations for structural candidates."""
from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any, Mapping

from ..geometry.bounds import derive_bbox
from .column_annotations import column_cloud_manifest
from .roles import role_matches_class


ELEMENT_CLASSES = {
    "wall", "column", "beam", "girder", "slab", "roof", "truss", "brace",
    "stair", "opening", "pipe", "duct", "equipment", "other", "unknown",
}
STRUCTURAL_ROLES = {
    "column", "crane_column", "beam", "crane_girder", "roof_beam", "rail",
    "floor_beam", "purlin", "truss_member", "truss_top_chord", "truss_bottom_chord",
    "truss_post", "truss_web", "brace", "pipe", "duct", "cable_tray", "other", "unknown",
}
ANNOTATION_STATES = {"labeled", "unknown", "excluded"}
INVALIDATED_SOURCE = "invalidated_synthetic_ground_truth"


def _box(item: Mapping[str, Any]) -> Mapping[str, Any]:
    bbox = item.get("bbox")
    if not isinstance(bbox, Mapping) or "min" not in bbox or "max" not in bbox:
        geometry = item.get("geometry") or {}
        if not isinstance(geometry, Mapping) or geometry.get("kind") not in {"oriented_box", "member", "slab"}:
            raise ValueError(f"element {item.get('id')!r} has no derivable bbox")
        bbox = derive_bbox(geometry)
    bounds = {}
    for name in ("min", "max"):
        value = bbox[name]
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(f"element {item.get('id')!r} bbox.{name} must be a 3D point")
        if any(isinstance(component, bool) for component in value):
            raise ValueError(f"element {item.get('id')!r} bbox.{name} must be numeric coordinates")
        try:
            coords = [float(component) for component in value]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"element {item.get('id')!r} bbox.{name} must be finite") from exc
        if not all(math.isfinite(component) for component in coords):
            raise ValueError(f"element {item.get('id')!r} bbox.{name} must be finite")
        bounds[name] = coords
    if any(bounds["max"][axis] < bounds["min"][axis] for axis in range(3)):
        raise ValueError(f"element {item.get('id')!r} bbox bounds must be ordered")
    return bounds


def element_snapshot_sha256(elements: list[Mapping[str, Any]],
                            cloud_metadata: Mapping[str, Any] | None = None) -> str:
    """Fingerprint the complete eligible candidate set and its measured geometry."""
    candidates = []
    seen: set[str] = set()
    for item in elements:
        if item.get("source") == INVALIDATED_SOURCE:
            continue
        element_id = item.get("id")
        if not isinstance(element_id, str) or not element_id.strip() or element_id in seen:
            raise ValueError("element snapshot requires unique, non-empty element IDs")
        class_name = item.get("class_name")
        if class_name not in ELEMENT_CLASSES:
            raise ValueError(f"element {element_id!r} has unsupported class_name")
        seen.add(element_id)
        candidates.append({
            "id": element_id,
            "class_name": class_name,
            "source": item.get("source"),
            "geometry": item.get("geometry") or {},
            "bbox": _box(item),
            "dimensions": item.get("dimensions") or {},
            "measured": item.get("measured"),
            "inferred": item.get("inferred"),
        })
    if not candidates:
        raise ValueError("snapshot has no structural candidates")
    snapshot = {
        "schema": "scan.element-candidate-snapshot/1",
        "cloud": column_cloud_manifest(cloud_metadata),
        "elements": sorted(candidates, key=lambda row: row["id"]),
    }
    serialized = json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":"), allow_nan=False)
    return sha256(serialized.encode("utf-8")).hexdigest()


def empty_element_annotation(element_id: str) -> dict[str, Any]:
    return {
        "element_id": element_id, "state": "pending", "annotator": None,
        "physical_instance_id": None, "class_label": None, "role_label": None,
        "type_label": None, "reason": "", "note": "", "revision": 0,
        "created_at": None,
    }


def _classification_metrics(pairs: list[tuple[str, str | None]]) -> dict[str, Any]:
    labels = sorted({label for truth, prediction in pairs for label in (truth, prediction) if label})
    per_class: dict[str, dict[str, Any]] = {}
    for label in labels:
        tp = sum(truth == label and prediction == label for truth, prediction in pairs)
        fp = sum(truth != label and prediction == label for truth, prediction in pairs)
        fn = sum(truth == label and prediction != label for truth, prediction in pairs)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (2 * precision * recall / (precision + recall)
              if precision is not None and recall is not None and precision + recall else None)
        per_class[label] = {
            "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1": round(f1, 4) if f1 is not None else None,
        }
    count = len(pairs)
    correct = sum(truth == prediction for truth, prediction in pairs)
    return {
        "evaluated_count": count,
        "correct_count": correct,
        "accuracy": round(correct / count, 4) if count else None,
        "per_class": per_class,
    }


def evaluate_element_annotations(annotations: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Score proposed labels on reviewed existing candidates, never detector recall."""
    counts = {state: 0 for state in ("labeled", "unknown", "excluded", "pending")}
    class_pairs: list[tuple[str, str | None]] = []
    role_pairs: list[tuple[str, str | None]] = []
    for annotation in annotations:
        state = annotation.get("state")
        counts[state if state in counts else "pending"] += 1
        if state != "labeled":
            continue
        candidate = annotation.get("candidate_context") or {}
        truth_class = annotation.get("class_label")
        if isinstance(truth_class, str) and truth_class:
            predicted_class = candidate.get("class_name")
            class_pairs.append((truth_class, predicted_class if isinstance(predicted_class, str) else None))
        truth_role = annotation.get("role_label")
        if isinstance(truth_role, str) and truth_role:
            predicted_role = candidate.get("predicted_role")
            role_pairs.append((truth_role, predicted_role if isinstance(predicted_role, str) else None))
    validity_denominator = counts["labeled"] + counts["excluded"]
    return {
        "scope": "reviewed_existing_candidates_only",
        "holdout_status": "not_declared",
        "missed_physical_elements_included": False,
        "reviewed_counts": counts,
        "candidate_validity": {
            "reviewed_candidate_count": validity_denominator,
            "confirmed_real_candidate_count": counts["labeled"],
            "excluded_false_candidate_count": counts["excluded"],
            "reviewed_candidate_validity_rate": (
                round(counts["labeled"] / validity_denominator, 4) if validity_denominator else None
            ),
        },
        "class_metrics": _classification_metrics(class_pairs),
        "role_metrics": _classification_metrics(role_pairs),
    }


def validate_element_annotation(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("annotation must be an object")
    state = payload.get("state")
    if state not in ANNOTATION_STATES:
        raise ValueError("state must be labeled, unknown or excluded")
    annotator = str(payload.get("annotator") or "").strip()
    if not annotator:
        raise ValueError("annotator is required")
    physical_id = payload.get("physical_instance_id")
    physical_id = str(physical_id).strip() if physical_id is not None else None
    class_label = payload.get("class_label")
    role_label = payload.get("role_label")
    type_label = payload.get("type_label")
    class_label = str(class_label).strip() if class_label is not None else None
    role_label = str(role_label).strip() if role_label is not None else None
    type_label = str(type_label).strip() if type_label is not None else None
    reason = str(payload.get("reason") or "").strip()
    note = str(payload.get("note") or "").strip()
    if state == "labeled":
        if not physical_id or not class_label:
            raise ValueError("labeled annotations require physical_instance_id and class_label")
        if class_label not in ELEMENT_CLASSES:
            raise ValueError("unsupported class_label")
        if class_label == "unknown":
            raise ValueError("use state=unknown when the reference class cannot be determined")
        if role_label is not None and role_label not in STRUCTURAL_ROLES:
            raise ValueError("unsupported role_label")
        if role_label is not None and not role_matches_class(class_label, role_label):
            raise ValueError("role_label is incompatible with class_label")
        if type_label is not None and not type_label:
            type_label = None
    else:
        if class_label is not None or role_label is not None or type_label is not None or physical_id is not None:
            raise ValueError("unknown and excluded annotations must not contain reference labels")
        if not (reason or note):
            raise ValueError("unknown and excluded annotations require a reason")
    return {
        "annotator": annotator,
        "state": state,
        "physical_instance_id": physical_id,
        "class_label": class_label,
        "role_label": role_label,
        "type_label": type_label,
        "reason": reason,
        "note": note,
    }


def element_reference_document(dataset_id: str, source_hash: str,
                               elements: list[Mapping[str, Any]],
                               annotations: Mapping[str, Mapping[str, Any]],
                               cloud_metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    rows = []
    annotators: set[str] = set()
    for item in sorted(elements, key=lambda row: str(row.get("id", ""))):
        if item.get("source") == INVALIDATED_SOURCE:
            continue
        element_id = item["id"]
        row = {**empty_element_annotation(element_id), **dict(annotations.get(element_id) or {})}
        row["element_id"] = element_id
        dimensions = item.get("dimensions")
        if not isinstance(dimensions, Mapping):
            dimensions = {}
        row["candidate_context"] = {
            "class_name": item.get("class_name"),
            "source": item.get("source"),
            "predicted_role": dimensions.get("role"),
            "predicted_role_status": dimensions.get("role_status"),
            "bbox": _box(item),
            "geometry": item.get("geometry") or {},
        }
        if row.get("annotator"):
            annotators.add(row["annotator"])
        rows.append(row)
    return {
        "schema": "scan.element-role-reference/1",
        "dataset_id": dataset_id,
        "source_snapshot_sha256": source_hash,
        "annotation_origin": "independent_manual",
        "candidate_context_note": "candidate_context is recognizer output for locating the object; it is not an annotation or reference label",
        "source_cloud_manifest": column_cloud_manifest(cloud_metadata),
        "annotator": ", ".join(sorted(annotators)) or None,
        "annotations": rows,
        "classification_evaluation": evaluate_element_annotations(rows),
    }
