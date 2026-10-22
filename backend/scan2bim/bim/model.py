"""Neutral BIM model (JSON) shared by IFC export, Revit plugin and API clients."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ..geometry.bounds import derive_bbox
from ..structure.column_annotations import column_cloud_manifest


_BIM_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "scan2bim.bim-1.0.schema.json"
_BIM_SCHEMA = json.loads(_BIM_SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_BIM_SCHEMA)
_BIM_VALIDATOR = Draft202012Validator(_BIM_SCHEMA)


def _reject_nonfinite(value: Any, path: str = "model") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"BIM model contains a non-finite number at {path}")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_nonfinite(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_nonfinite(child, f"{path}[{index}]")


def validate_bim_model(model: dict[str, Any]) -> None:
    """Validate schema fields plus geometry invariants JSON Schema cannot express."""
    _reject_nonfinite(model)
    errors = sorted(_BIM_VALIDATOR.iter_errors(model), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "model"
        raise ValueError(f"BIM model contract violation at {path}: {error.message}")

    seen_ids: set[str] = set()
    for index, element in enumerate(model["elements"]):
        element_id = element["id"]
        if element_id in seen_ids:
            raise ValueError("BIM model requires unique, non-empty element IDs")
        seen_ids.add(element_id)
        for key in ("min", "max"):
            vector = element["bbox"][key]
            if not all(math.isfinite(float(value)) for value in vector):
                raise ValueError(f"BIM element {element_id!r} bbox.{key} must be finite")
        if any(low > high for low, high in zip(element["bbox"]["min"], element["bbox"]["max"])):
            raise ValueError(f"BIM element {element_id!r} bbox min must not exceed max")

        geometry = element["geometry"]
        kind = geometry["kind"]
        if kind == "oriented_box":
            sizes = geometry["sizes"]
            if any(not math.isfinite(float(sizes[key])) or float(sizes[key]) <= 0
                   for key in ("length", "thickness", "height")):
                raise ValueError(f"BIM element {element_id!r} oriented_box sizes must be finite and positive")
            if "rotation_z" in geometry and not math.isfinite(float(geometry["rotation_z"])):
                raise ValueError(f"BIM element {element_id!r} rotation_z must be finite")
        elif kind == "member":
            start, end = geometry["p0"], geometry["p1"]
            if math.dist(start, end) <= 1e-9:
                raise ValueError(f"BIM element {element_id!r} member axis must have non-zero length")
            if "section_m" in geometry and (not math.isfinite(float(geometry["section_m"]))
                                              or float(geometry["section_m"]) <= 0):
                raise ValueError(f"BIM element {element_id!r} section_m must be finite and positive")
        elif kind == "slab":
            polygon = geometry["polygon"]
            area2 = sum(polygon[i][0] * polygon[(i + 1) % len(polygon)][1]
                        - polygon[(i + 1) % len(polygon)][0] * polygon[i][1]
                        for i in range(len(polygon)))
            if abs(area2) <= 1e-12:
                raise ValueError(f"BIM element {element_id!r} slab polygon must have non-zero area")


def _element_for_exchange(element: dict[str, Any]) -> dict[str, Any]:
    geometry = element["geometry"]
    bbox = element.get("bbox")
    if not isinstance(bbox, dict) or "min" not in bbox or "max" not in bbox:
        if geometry.get("kind") not in {"oriented_box", "member", "slab"}:
            raise ValueError(f"BIM element {element.get('id')!r} has no bbox and its geometry cannot derive one")
        # Legacy rows may have an empty bbox. Derive it for this export only;
        # the persisted recognition record and source geometry stay untouched.
        bbox = derive_bbox(geometry)
    return {
        "id": element["id"],
        "class_name": element["class_name"],
        "geometry": geometry,
        "bbox": bbox,
        "confidence": element["confidence"],
        "confidence_kind": element.get("confidence_kind", "heuristic"),
        "measured": bool(element["measured"]),
        "inferred": bool(element.get("inferred")),
        "source": element.get("source", "geometric"),
        "review_status": element.get("review_status", "unreviewed"),
        "dimensions": element.get("dimensions", {}),
        # Recognition method, support counts, and any source-point references
        # are part of the review trail shared with IFC/Revit consumers.
        "metadata": element.get("metadata", {}),
    }


def build_model(
    project: dict[str, Any],
    cloud: dict[str, Any],
    elements: list[dict[str, Any]],
    levels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    storeys = []
    for level in levels or []:
        storeys.append(
            {
                "name": f"Level {level['z']:.2f}",
                "elevation": float(level["z"]),
                "confidence": level.get("confidence"),
                "method": level.get("method"),
            }
        )
    model = {
        "schema": "scan2bim.bim/1.0",
        "units": "m",
        "coordinate_frame": {
            "id": "source_cloud_world", "units": "m", "vertical_axis": "Z",
        },
        "project": {"id": project["id"], "name": project["name"]},
        "source": {
            "cloud_id": cloud["id"],
            "cloud_name": cloud["name"],
            "format": cloud["source_format"],
            "origin": [
                cloud.get("origin_x") or 0.0,
                cloud.get("origin_y") or 0.0,
                cloud.get("origin_z") or 0.0,
            ],
            "point_count": cloud.get("point_count", 0),
            "snapshot_manifest": column_cloud_manifest(cloud),
        },
        "levels": storeys,
        "elements": [_element_for_exchange(el) for el in elements],
        "notes": [
            "Measured geometry is separated from inferred geometry via measured/inferred flags.",
            "Confidence is a heuristic score, not a calibrated probability.",
            "No material or load-bearing property is inferred from shape.",
        ],
    }
    validate_bim_model(model)
    return model
