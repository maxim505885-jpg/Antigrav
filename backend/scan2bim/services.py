"""Domain services shared by the REST API and plugins."""
from __future__ import annotations

import math
from typing import Any

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .db import dumps, execute, loads, new_id, one, rows, utcnow
from .learning.features import features_from_element
from .learning.store import create_sample


def element_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "cloud_id": row["cloud_id"],
        "parent_id": row.get("parent_id"),
        "class_name": row["class_name"],
        "geometry": loads(row.get("geometry_json"), {}),
        "bbox": loads(row.get("bbox_json"), {}),
        "confidence": row["confidence"],
        "confidence_kind": row["confidence_kind"],
        "measured": bool(row["measured"]),
        "inferred": bool(row["inferred"]),
        "source": row["source"],
        "review_status": row["review_status"],
        "dimensions": loads(row.get("dimensions_json"), {}),
        "metadata": loads(row.get("metadata_json"), {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "features": features_from_element(
            {
                "geometry": loads(row.get("geometry_json"), {}),
                "bbox": loads(row.get("bbox_json"), {}),
                "dimensions": loads(row.get("dimensions_json"), {}),
                "confidence": row["confidence"],
            }
        ),
    }


def get_element(element_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM elements WHERE id = ?", (element_id,))
    if not row:
        raise KeyError(f"element {element_id} not found")
    return element_from_row(row)


def list_elements(cloud_id: str) -> list[dict[str, Any]]:
    return [element_from_row(r) for r in rows("SELECT * FROM elements WHERE cloud_id = ? ORDER BY class_name, id", (cloud_id,))]


def derive_bbox(geometry: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    kind = geometry.get("kind")
    if kind == "oriented_box":
        cx, cy, cz = (float(v) for v in geometry["center"])
        length = float(geometry["sizes"]["length"])
        thickness = float(geometry["sizes"]["thickness"])
        height = float(geometry["sizes"]["height"])
        angle = float(geometry.get("rotation_z", 0.0))
        ca, sa = math.cos(angle), math.sin(angle)
        xs, ys = [], []
        for lx, ly in (
            (-length / 2, -thickness / 2),
            (length / 2, -thickness / 2),
            (length / 2, thickness / 2),
            (-length / 2, thickness / 2),
        ):
            xs.append(cx + lx * ca - ly * sa)
            ys.append(cy + lx * sa + ly * ca)
        return {
            "min": [round(min(xs), 3), round(min(ys), 3), round(cz - height / 2, 3)],
            "max": [round(max(xs), 3), round(max(ys), 3), round(cz + height / 2, 3)],
        }
    if kind == "member" and geometry.get("p0") and geometry.get("p1"):
        section = float(geometry.get("section_m", 0.15))
        p0 = [float(v) for v in geometry["p0"]]
        p1 = [float(v) for v in geometry["p1"]]
        half = section / 2
        return {
            "min": [round(min(p0[0], p1[0]) - half, 3), round(min(p0[1], p1[1]) - half, 3), round(min(p0[2], p1[2]) - half, 3)],
            "max": [round(max(p0[0], p1[0]) + half, 3), round(max(p0[1], p1[1]) + half, 3), round(max(p0[2], p1[2]) + half, 3)],
        }
    if kind == "slab" and geometry.get("polygon"):
        pts = geometry["polygon"]
        z = float(geometry.get("z", 0.0))
        half = float(geometry.get("assumed_thickness", 0.2)) / 2
        return {
            "min": [
                round(min(float(p[0]) for p in pts), 3),
                round(min(float(p[1]) for p in pts), 3),
                round(z - half, 3),
            ],
            "max": [
                round(max(float(p[0]) for p in pts), 3),
                round(max(float(p[1]) for p in pts), 3),
                round(z + half, 3),
            ],
        }
    return fallback or {"min": [0, 0, 0], "max": [0, 0, 0]}


def _update_element(element_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if not updates:
        return get_element(element_id)
    fields, values = [], []
    for key, value in updates.items():
        if key in {"geometry", "bbox", "dimensions", "metadata"}:
            fields.append(f"{key}_json = ?")
            values.append(dumps(value))
        else:
            fields.append(f"{key} = ?")
            values.append(value)
    fields.append("updated_at = ?")
    values.append(utcnow())
    values.append(element_id)
    execute(f"UPDATE elements SET {', '.join(fields)} WHERE id = ?", tuple(values))
    return get_element(element_id)


def _feedback(
    element: dict[str, Any],
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
    engineer: str,
    note: str,
) -> str:
    feedback_id = new_id()
    execute(
        """
        INSERT INTO feedback
        (id, project_id, element_id, cloud_id, action, before_json, after_json, engineer, note, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            feedback_id,
            element["project_id"],
            element["id"],
            element["cloud_id"],
            action,
            dumps(before),
            dumps(after),
            engineer,
            note,
            utcnow(),
        ),
    )
    return feedback_id


def _ensure_sample(element: dict[str, Any], class_name: str, source: str = "engineer") -> dict[str, Any] | None:
    existing = one(
        "SELECT id FROM training_samples WHERE element_id = ? AND class_name = ? LIMIT 1",
        (element["id"], class_name),
    )
    if existing:
        return None
    try:
        return create_sample(
            element["project_id"],
            element["cloud_id"],
            element,
            class_name=class_name,
            source=source,
            element_id=element["id"],
        )
    except Exception:
        return None


def review_element(
    element_id: str,
    action: str,
    class_name: str | None = None,
    geometry: dict[str, Any] | None = None,
    engineer: str = "",
    note: str = "",
) -> dict[str, Any]:
    element = get_element(element_id)
    before = {
        "class_name": element["class_name"],
        "geometry": element["geometry"],
        "review_status": element["review_status"],
    }
    updates: dict[str, Any] = {}
    if action == "confirm":
        updates["review_status"] = "confirmed"
    elif action == "reclassify":
        if not class_name:
            raise ValueError("reclassify requires class_name")
        updates["class_name"] = class_name
        updates["review_status"] = "corrected"
    elif action == "adjust_boundary":
        if not geometry:
            raise ValueError("adjust_boundary requires geometry")
        updates["geometry"] = geometry
        updates["bbox"] = derive_bbox(geometry, element["bbox"])
        updates["measured"] = 0
        updates["inferred"] = 1
        updates["review_status"] = "corrected"
    elif action == "reject":
        updates["review_status"] = "rejected"
    else:
        raise ValueError(f"unsupported action {action} for this endpoint")

    updated = _update_element(element_id, updates)
    feedback_id = _feedback(
        element, action, before, {**updates, "id": element_id}, engineer, note
    )
    sample = None
    if action in {"confirm", "reclassify", "adjust_boundary"}:
        sample = _ensure_sample(updated, updated["class_name"])
    return {"element": updated, "feedback_id": feedback_id, "sample": sample}


def merge_elements(
    element_id: str,
    other_element_id: str,
    class_name: str | None = None,
    engineer: str = "",
    note: str = "",
) -> dict[str, Any]:
    if element_id == other_element_id:
        raise ValueError("cannot merge an element with itself")
    target = get_element(element_id)
    other = get_element(other_element_id)
    if target["cloud_id"] != other["cloud_id"]:
        raise ValueError("elements belong to different clouds")
    before = {"target": target, "other": other}
    target_bbox = target["bbox"]
    other_bbox = other["bbox"]
    try:
        merged_bbox = {
            "min": [min(target_bbox["min"][i], other_bbox["min"][i]) for i in range(3)],
            "max": [max(target_bbox["max"][i], other_bbox["max"][i]) for i in range(3)],
        }
    except Exception as exc:
        raise ValueError("both elements need valid bounding boxes") from exc

    if target["geometry"].get("kind") == "slab" and other["geometry"].get("kind") == "slab":
        polys = []
        for el in (target, other):
            pts = el["geometry"].get("polygon") or []
            if len(pts) >= 3:
                polys.append(Polygon(pts))
        merged_poly = unary_union(polys) if polys else None
        if merged_poly is not None and not merged_poly.is_empty:
            if merged_poly.geom_type == "MultiPolygon":
                merged_poly = max(merged_poly.geoms, key=lambda g: g.area)
            geometry = {
                **target["geometry"],
                "polygon": [[round(x, 4), round(y, 4)] for x, y in merged_poly.exterior.coords],
                "note": "merged by engineer; polygon union",
            }
        else:
            geometry = target["geometry"]
    else:
        cx = (merged_bbox["min"][0] + merged_bbox["max"][0]) / 2
        cy = (merged_bbox["min"][1] + merged_bbox["max"][1]) / 2
        cz = (merged_bbox["min"][2] + merged_bbox["max"][2]) / 2
        length = merged_bbox["max"][0] - merged_bbox["min"][0]
        thickness = merged_bbox["max"][1] - merged_bbox["min"][1]
        height = merged_bbox["max"][2] - merged_bbox["min"][2]
        geometry = {
            "kind": "oriented_box",
            "center": [round(cx, 4), round(cy, 4), round(cz, 4)],
            "sizes": {
                "length": round(length, 3),
                "thickness": round(thickness, 3),
                "height": round(height, 3),
            },
            "rotation_z": 0.0,
            "note": "merged by engineer; axis-aligned union of bounds (inferred)",
        }

    updated = _update_element(
        element_id,
        {
            "class_name": class_name or target["class_name"],
            "geometry": geometry,
            "bbox": merged_bbox,
            "dimensions": {
                "length_m": round(merged_bbox["max"][0] - merged_bbox["min"][0], 3),
                "thickness_m": round(merged_bbox["max"][1] - merged_bbox["min"][1], 3),
                "height_m": round(merged_bbox["max"][2] - merged_bbox["min"][2], 3),
            },
            "review_status": "corrected",
            "measured": 0,
            "inferred": 1,
            "metadata": {
                **target.get("metadata", {}),
                "merged_from": [element_id, other_element_id],
                "merge_method": "bounds/polygon union (inferred)",
            },
        },
    )
    _update_element(
        other_element_id,
        {
            "review_status": "rejected",
            "metadata": {
                **other.get("metadata", {}),
                "merged_into": element_id,
            },
        },
    )
    feedback_id = _feedback(
        target, "merge", before, {"merged_id": element_id, "removed_id": other_element_id}, engineer, note
    )
    return {"element": updated, "feedback_id": feedback_id}


def split_element(
    element_id: str,
    axis: str,
    value: float,
    engineer: str = "",
    note: str = "",
) -> dict[str, Any]:
    element = get_element(element_id)
    if axis not in {"x", "y", "z"}:
        raise ValueError("split axis must be x, y or z")
    bbox = element["bbox"]
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    lo, hi = float(bbox["min"][idx]), float(bbox["max"][idx])
    if not (lo + 0.01 < value < hi - 0.01):
        raise ValueError("split value must lie inside the element bounds")
    before = element
    children = []
    for part, (a, b) in enumerate(((lo, value), (value, hi))):
        part_bbox = {
            "min": list(bbox["min"]),
            "max": list(bbox["max"]),
        }
        part_bbox["min"][idx] = round(a, 4)
        part_bbox["max"][idx] = round(b, 4)
        cx = (part_bbox["min"][0] + part_bbox["max"][0]) / 2
        cy = (part_bbox["min"][1] + part_bbox["max"][1]) / 2
        cz = (part_bbox["min"][2] + part_bbox["max"][2]) / 2
        geometry = {
            "kind": "oriented_box",
            "center": [round(cx, 4), round(cy, 4), round(cz, 4)],
            "sizes": {
                "length": round(part_bbox["max"][0] - part_bbox["min"][0], 3),
                "thickness": round(part_bbox["max"][1] - part_bbox["min"][1], 3),
                "height": round(part_bbox["max"][2] - part_bbox["min"][2], 3),
            },
            "rotation_z": 0.0,
            "note": "split by engineer; axis-aligned bounds (inferred)",
        }
        child_id = new_id()
        now = utcnow()
        execute(
            """
            INSERT INTO elements
            (id, project_id, cloud_id, parent_id, class_name, geometry_json, bbox_json,
             confidence, confidence_kind, measured, inferred, source, review_status,
             dimensions_json, metadata_json, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                child_id,
                element["project_id"],
                element["cloud_id"],
                element_id,
                element["class_name"],
                dumps(geometry),
                dumps(part_bbox),
                element["confidence"],
                element["confidence_kind"],
                0,
                1,
                "manual",
                "corrected",
                dumps(
                    {
                        "length_m": geometry["sizes"]["length"],
                        "thickness_m": geometry["sizes"]["thickness"],
                        "height_m": geometry["sizes"]["height"],
                    }
                ),
                dumps(
                    {
                        **element.get("metadata", {}),
                        "split_from": element_id,
                        "split_axis": axis,
                        "split_value": value,
                    }
                ),
                now,
                now,
            ),
        )
        children.append(get_element(child_id))
    _update_element(
        element_id,
        {
            "review_status": "rejected",
            "metadata": {**element.get("metadata", {}), "split_into": [c["id"] for c in children]},
        },
    )
    feedback_id = _feedback(
        element,
        "split",
        before,
        {"children": [c["id"] for c in children], "axis": axis, "value": value},
        engineer,
        note,
    )
    return {"children": children, "feedback_id": feedback_id}


def set_review_status(element_id: str, status: str, engineer: str = "", note: str = "") -> dict[str, Any]:
    action = "confirm" if status == "confirmed" else "reject"
    return review_element(element_id, action, engineer=engineer, note=note)
