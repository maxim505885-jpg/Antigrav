"""Independent, immutable column-reference snapshots and annotation checks."""
from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any, Mapping

from ..geometry.bounds import derive_bbox


FACE_IDS = {"u+", "u-", "v+", "v-", "unknown"}
ANNOTATION_STATES = {"labeled", "unknown", "excluded"}
MEASUREMENT_SOURCES = {"manual_cloud", "field_measurement"}
SHAPE_LABELS = {"rectangular_solid", "built_up", "stepped", "circular", "other", "unknown"}
STRUCTURAL_ROLES = {"column", "crane_column", "other", "unknown"}
CLOUD_SNAPSHOT_FIELDS = (
    "sha256", "source_format", "size_bytes", "point_count", "ingested_count", "decimated",
    "origin_x", "origin_y", "origin_z", "bbox_min_x", "bbox_min_y", "bbox_min_z",
    "bbox_max_x", "bbox_max_y", "bbox_max_z", "has_color", "has_intensity",
)


def column_cloud_manifest(cloud_metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if cloud_metadata is None:
        return None
    return {key: cloud_metadata.get(key) for key in CLOUD_SNAPSHOT_FIELDS}


def column_snapshot_sha256(elements: list[Mapping[str, Any]],
                           cloud_metadata: Mapping[str, Any] | None = None) -> str:
    """Hash measured source fields for a deterministic set of column candidates."""
    columns = []
    seen: set[str] = set()
    for item in elements:
        if item.get("class_name") != "column":
            continue
        element_id = item.get("id")
        if not isinstance(element_id, str) or not element_id or element_id in seen:
            raise ValueError("column snapshot requires unique, non-empty element IDs")
        seen.add(element_id)
        bbox = item.get("bbox")
        geometry = item.get("geometry") or {}
        if not isinstance(bbox, Mapping) or "min" not in bbox or "max" not in bbox:
            if geometry.get("kind") not in {"oriented_box", "member", "slab"}:
                raise ValueError(f"column snapshot element {element_id!r} has no derivable bbox")
            bbox = derive_bbox(geometry)
        columns.append({
            "id": element_id, "class_name": "column", "geometry": geometry,
            "bbox": bbox, "dimensions": item.get("dimensions"),
            "measured": item.get("measured"), "inferred": item.get("inferred"),
            "source": item.get("source"),
        })
    if not columns:
        raise ValueError("snapshot has no column candidates")
    snapshot = {
        "schema": "scan.column-candidate-snapshot/1",
        "cloud": column_cloud_manifest(cloud_metadata),
        "columns": sorted(columns, key=lambda row: row["id"]),
    }
    serialized = json.dumps(snapshot, sort_keys=True,
                            ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return sha256(serialized.encode("utf-8")).hexdigest()


def empty_annotation(element_id: str) -> dict[str, Any]:
    """Return empty manual-reference fields without copying recognition guesses."""
    return {
        "element_id": element_id,
        "state": "pending",
        "physical_instance_id": None,
        "type_label": None,
        "shape_label": None,
        "structural_role": None,
        "sides_m": None,
        "measurement_source": None,
        "z_measurements": [],
        "algorithm_suggestions_verified": False,
        "visible_faces": [],
        "hidden_faces": [],
        "confidence": None,
        "reason_unknown": "",
        "note": "",
        "revision": 0,
        "annotator": None,
        "created_at": None,
    }


def validate_column_annotation(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize and validate one reviewer-authored independent annotation."""
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
    type_label = payload.get("type_label")
    type_label = str(type_label).strip() if type_label is not None else None
    reason_unknown = str(payload.get("reason_unknown") or "").strip()
    note = str(payload.get("note") or "").strip()
    if state == "labeled" and (not physical_id or not type_label):
        raise ValueError("labeled annotations require physical_instance_id and type_label")
    if state != "labeled" and type_label is not None:
        raise ValueError("unknown and excluded annotations must not have a type_label")
    if state in {"unknown", "excluded"} and not (reason_unknown or note):
        raise ValueError("unknown and excluded annotations require a reason")

    shape_label = payload.get("shape_label")
    if shape_label not in SHAPE_LABELS | {None}:
        raise ValueError("unsupported shape_label")
    structural_role = payload.get("structural_role")
    if structural_role not in STRUCTURAL_ROLES | {None}:
        raise ValueError("unsupported structural_role")
    measurement_source = payload.get("measurement_source")
    if measurement_source not in MEASUREMENT_SOURCES | {None}:
        raise ValueError("unsupported measurement_source")

    def sides(value: Any, label: str) -> dict[str, float] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping) or set(value) != {"long", "short"}:
            raise ValueError(f"{label} must contain long and short")
        long_side, short_side = value["long"], value["short"]
        if (isinstance(long_side, bool) or isinstance(short_side, bool)
                or not isinstance(long_side, (int, float)) or not isinstance(short_side, (int, float))
                or not math.isfinite(long_side) or not math.isfinite(short_side)
                or short_side <= 0 or long_side < short_side):
            raise ValueError(f"{label} must contain finite positive long/short measurements in order")
        return {"long": float(long_side), "short": float(short_side)}

    measured_sides = sides(payload.get("sides_m"), "sides_m")
    if measured_sides is not None and measurement_source is None:
        raise ValueError("measured sides require measurement_source")

    z_rows = payload.get("z_measurements", [])
    if not isinstance(z_rows, list):
        raise ValueError("z_measurements must be a list")
    normalized_z = []
    seen_heights: set[float] = set()
    has_point_linked_suggestions = False
    for row in z_rows:
        if not isinstance(row, Mapping):
            raise ValueError("each z measurement must be an object")
        z_value = row.get("z_m")
        if isinstance(z_value, bool) or not isinstance(z_value, (int, float)) or not math.isfinite(z_value):
            raise ValueError("each z measurement requires a finite z_m")
        z_value = float(z_value)
        if z_value in seen_heights:
            raise ValueError("z measurement heights must be unique")
        seen_heights.add(z_value)
        row_sides = sides(row.get("sides_m"), "z measurement sides_m")
        if row_sides is not None and measurement_source is None:
            raise ValueError("z measurements require measurement_source")
        normalized_row = {"z_m": z_value, "sides_m": row_sides, "note": str(row.get("note") or "").strip()}
        provenance = row.get("source_provenance")
        if provenance is not None:
            expected_provenance_fields = {
                "source_point_row_id_count", "source_point_row_id_sample",
                "source_index_space", "analysis_algorithm",
            }
            if not isinstance(provenance, Mapping) or set(provenance) != expected_provenance_fields:
                raise ValueError("source_provenance must contain point-row count, sample, index space and algorithm")
            count = provenance["source_point_row_id_count"]
            sample = provenance["source_point_row_id_sample"]
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise ValueError("source point row count must be a positive integer")
            if (not isinstance(sample, list) or not sample or len(sample) > min(count, 100)
                    or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in sample)
                    or len(set(sample)) != len(sample)):
                raise ValueError("source point row sample must contain up to 100 unique non-negative integers")
            if provenance["source_index_space"] != "derived_positions_row_index/1":
                raise ValueError("unsupported source point row index space")
            algorithm = provenance["analysis_algorithm"]
            if not isinstance(algorithm, str) or not algorithm.strip() or len(algorithm) > 200:
                raise ValueError("source provenance requires an analysis algorithm identifier")
            normalized_row["source_provenance"] = {
                "source_point_row_id_count": count,
                "source_point_row_id_sample": list(sample),
                "source_index_space": "derived_positions_row_index/1",
                "analysis_algorithm": algorithm.strip(),
            }
            has_point_linked_suggestions = True
        normalized_z.append(normalized_row)

    suggestions_verified = payload.get("algorithm_suggestions_verified", False)
    if not isinstance(suggestions_verified, bool):
        raise ValueError("algorithm_suggestions_verified must be a boolean")
    if has_point_linked_suggestions and not suggestions_verified:
        raise ValueError("point-linked algorithm suggestions require explicit human verification")
    if suggestions_verified and not has_point_linked_suggestions:
        raise ValueError("algorithm verification requires point-linked section provenance")

    def faces(field: str) -> list[str]:
        value = payload.get(field, [])
        if not isinstance(value, list) or any(item not in FACE_IDS - {"unknown"} for item in value):
            raise ValueError(f"{field} must list observed face IDs")
        return sorted(set(value))

    confidence = payload.get("confidence")
    if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                                  or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        raise ValueError("confidence must be between 0 and 1")

    return {
        "state": state,
        "annotator": annotator,
        "physical_instance_id": physical_id,
        "type_label": type_label,
        "shape_label": shape_label,
        "structural_role": structural_role,
        "sides_m": measured_sides,
        "measurement_source": measurement_source,
        "z_measurements": sorted(normalized_z, key=lambda item: item["z_m"]),
        "algorithm_suggestions_verified": suggestions_verified,
        "visible_faces": faces("visible_faces"),
        "hidden_faces": faces("hidden_faces"),
        "confidence": float(confidence) if confidence is not None else None,
        "reason_unknown": reason_unknown,
        "note": note,
    }


def annotation_reference_document(dataset_id: str, source_hash: str, elements: list[Mapping[str, Any]],
                                  latest_annotations: Mapping[str, Mapping[str, Any]],
                                  cloud_metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the existing evaluator's input; predictions never fill reference fields."""
    annotations = []
    annotators = set()
    measurement_sources = set()
    for item in sorted(elements, key=lambda row: str(row.get("id", ""))):
        if item.get("class_name") != "column":
            continue
        element_id = item["id"]
        annotation = dict(latest_annotations.get(element_id) or empty_annotation(element_id))
        if annotation.get("annotator"):
            annotators.add(annotation["annotator"])
        has_measurements = annotation.get("sides_m") is not None or any(
            isinstance(row, Mapping) and row.get("sides_m") is not None
            for row in annotation.get("z_measurements", []))
        if has_measurements and annotation.get("measurement_source"):
            measurement_sources.add(annotation["measurement_source"])
        annotation["element_id"] = element_id
        annotation["note"] = annotation.get("reason_unknown") or annotation.get("note", "")
        annotations.append(annotation)
    reference_kind = next(iter(measurement_sources)) if len(measurement_sources) == 1 else (
        "mixed" if measurement_sources else "manual_cloud")
    return {
        "schema": "scan.column-type-reference/1",
        "dataset_id": dataset_id,
        "source_snapshot_sha256": source_hash,
        "annotation_origin": "independent_manual",
        "source_cloud_manifest": column_cloud_manifest(cloud_metadata),
        "reference_kind": reference_kind,
        "annotator": ", ".join(sorted(annotators)) or None,
        "engineering_tolerance_m": None,
        "annotations": annotations,
    }
