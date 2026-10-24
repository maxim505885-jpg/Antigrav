"""Domain services shared by the REST API and plugins."""
from __future__ import annotations

from typing import Any

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .db import dumps, execute, loads, new_id, one, rows, utcnow
from .geometry.bounds import derive_bbox
from .learning.features import features_from_element
from .learning.store import create_sample, validate_training_sample_source


def element_from_row(row: dict[str, Any]) -> dict[str, Any]:
    element = {
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
    if "source_cloud_sha256" in row:
        element["source_cloud_sha256"] = row.get("source_cloud_sha256")
    return element


def get_element(element_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM elements WHERE id = ?", (element_id,))
    if not row:
        raise KeyError(f"element {element_id} not found")
    return element_from_row(row)


def _assert_reviewable_source(element: dict[str, Any]) -> None:
    if element.get("source") == "invalidated_synthetic_ground_truth":
        raise ValueError("invalidated synthetic ground truth cannot be reviewed or used as project evidence")


def _element_state(element: dict[str, Any]) -> dict[str, Any]:
    return {
        key: element.get(key)
        for key in (
            "id", "project_id", "cloud_id", "parent_id", "class_name", "geometry", "bbox",
            "confidence", "confidence_kind", "measured", "inferred", "source", "review_status",
            "dimensions", "metadata",
        )
    }


def _restore_element_state(element_id: str, state: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "parent_id", "class_name", "geometry", "bbox", "confidence", "confidence_kind", "measured",
        "inferred", "source", "review_status", "dimensions", "metadata",
    )
    updates = {field: state[field] for field in fields if field in state and state[field] is not None}
    if "geometry" in updates and "bbox" not in updates:
        updates["bbox"] = derive_bbox(updates["geometry"], get_element(element_id)["bbox"])
    return _update_element(element_id, updates)


def list_elements(cloud_id: str) -> list[dict[str, Any]]:
    # Invalidated synthetic catalog rows remain in SQLite for audit, but must
    # never appear as live candidates or leak into downstream model exports.
    invalidated_source = "invalidated_synthetic_ground_truth"
    els = [element_from_row(r) for r in rows(
        "SELECT * FROM elements WHERE cloud_id = ? AND source != ? ORDER BY class_name, id",
        (cloud_id, invalidated_source),
    )]
    if not els:
        c_row = one("SELECT project_id FROM clouds WHERE id = ?", (cloud_id,))
        if c_row:
            els = [element_from_row(r) for r in rows(
                "SELECT * FROM elements WHERE project_id = ? AND source != ? ORDER BY class_name, id",
                (c_row["project_id"], invalidated_source),
            )]
    return els


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


def _ensure_sample(
    element: dict[str, Any],
    class_name: str,
    source: str = "engineer",
    physical_instance_id: str | None = None,
) -> dict[str, Any] | None:
    if (element.get("review_status") not in {"confirmed", "corrected"}
        or element.get("inferred")):
        return None
    existing = one(
        "SELECT id FROM training_samples WHERE element_id = ? AND class_name = ? "
        "AND source != 'undone' LIMIT 1",
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
            physical_instance_id=physical_instance_id,
        )
    except Exception:
        return None


def _supersede_training_samples(element_id: str) -> list[dict[str, str]]:
    previous = rows(
        "SELECT id,source FROM training_samples WHERE element_id=? AND source!='undone' ORDER BY created_at,id",
        (element_id,),
    )
    for sample in previous:
        execute("UPDATE training_samples SET source='undone' WHERE id=?", (sample["id"],))
    return [{"id": sample["id"], "source": sample["source"]} for sample in previous]


def review_element(
    element_id: str,
    action: str,
    class_name: str | None = None,
    geometry: dict[str, Any] | None = None,
    engineer: str = "",
    note: str = "",
    physical_instance_id: str | None = None,
) -> dict[str, Any]:
    element = get_element(element_id)
    _assert_reviewable_source(element)
    before = _element_state(element)
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
    training_sample_warning = None
    superseded_samples = []
    if action == "reclassify" and updated["class_name"] != element["class_name"]:
        superseded_samples = _supersede_training_samples(element_id)
    if action in {"confirm", "reclassify"}:
        if updated.get("review_status") in {"confirmed", "corrected"} and not updated.get("inferred"):
            try:
                validate_training_sample_source(updated["cloud_id"], updated)
            except ValueError as exc:
                training_sample_warning = str(exc)
        if training_sample_warning is None:
            sample = _ensure_sample(updated, updated["class_name"], physical_instance_id=physical_instance_id)
        if sample or superseded_samples:
            execute(
                "UPDATE feedback SET after_json = ? WHERE id = ?",
                (dumps({**updates, "id": element_id,
                    **({"sample_id": sample["id"]} if sample else {}),
                    **({"superseded_samples": superseded_samples} if superseded_samples else {})}), feedback_id),
            )
    result = {"element": updated, "feedback_id": feedback_id, "sample": sample}
    if training_sample_warning:
        result["training_sample_warning"] = training_sample_warning
    return result


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
    _assert_reviewable_source(target)
    _assert_reviewable_source(other)
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
        target,
        "merge",
        before,
        {
            "merged_id": element_id,
            "removed_id": other_element_id,
            "target_after": _element_state(updated),
            "other_after": _element_state(get_element(other_element_id)),
        },
        engineer,
        note,
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
    _assert_reviewable_source(element)
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
        {
            "children": [c["id"] for c in children],
            "children_state": [_element_state(child) for child in children],
            "axis": axis,
            "value": value,
        },
        engineer,
        note,
    )
    return {"children": children, "feedback_id": feedback_id}


def set_review_status(element_id: str, status: str, engineer: str = "", note: str = "") -> dict[str, Any]:
    action = "confirm" if status == "confirmed" else "reject"
    return review_element(element_id, action, engineer=engineer, note=note)


def undo_feedback(element_id: str, feedback_id: str, engineer: str = "") -> dict[str, Any]:
    entry = one("SELECT * FROM feedback WHERE id = ?", (feedback_id,))
    if not entry or entry.get("element_id") != element_id:
        raise KeyError(f"feedback {feedback_id} not found for element {element_id}")
    if entry["action"] == "undo":
        raise ValueError("an undo action cannot itself be undone")

    history = rows("SELECT rowid AS sequence, * FROM feedback WHERE element_id = ? ORDER BY rowid DESC", (element_id,))
    already_undone = {
        loads(item.get("after_json"), {}).get("undo_of")
        for item in history
        if item["action"] == "undo"
    }
    latest = next((item for item in history if item["action"] != "undo" and item["id"] not in already_undone), None)
    if not latest or latest["id"] != feedback_id:
        raise ValueError("only the latest not-yet-undone action can be undone")

    current = get_element(element_id)
    before = loads(entry.get("before_json"), {})
    after = loads(entry.get("after_json"), {})
    restored: list[dict[str, Any]] = []
    if entry["action"] == "merge":
        target_before = before.get("target")
        other_before = before.get("other")
        other_id = (after.get("other_after") or {}).get("id") or (after.get("removed_id"))
        if not target_before or not other_before or not other_id:
            raise ValueError("merge history lacks source snapshots and cannot be safely undone")
        other_current = get_element(other_id)
        expected_other = after.get("other_after")
        changed = (
            any(
                _element_state(other_current).get(key) != expected_other.get(key)
                for key in _element_state(other_current)
            )
            if expected_other
            else other_current.get("metadata", {}).get("merged_into") != element_id
        )
        if changed:
            raise ValueError("merged element changed after the merge; refusing to overwrite it")
        restored.append(_restore_element_state(element_id, target_before))
        restored.append(_restore_element_state(other_id, other_before))
    elif entry["action"] == "split":
        child_ids = after.get("children", [])
        expected_children = {item["id"]: item for item in after.get("children_state", [])}
        for child_id in child_ids:
            child = get_element(child_id)
            expected = expected_children.get(child_id)
            changed = expected and any(
                _element_state(child).get(key) != expected.get(key)
                for key in _element_state(child)
            )
            if not expected and rows("SELECT id FROM feedback WHERE element_id = ? LIMIT 1", (child_id,)):
                changed = True
            if child.get("parent_id") != element_id or child.get("metadata", {}).get("split_from") != element_id or changed:
                raise ValueError("a split fragment changed after the split; refusing to overwrite it")
            child_metadata = {**child.get("metadata", {}), "undone_split": feedback_id}
            restored.append(_update_element(child_id, {"review_status": "rejected", "metadata": child_metadata}))
        restored.insert(0, _restore_element_state(element_id, before))
    else:
        restored.append(_restore_element_state(element_id, before))
        sample_id = after.get("sample_id")
        if sample_id:
            execute("UPDATE training_samples SET source = 'undone' WHERE id = ?", (sample_id,))
        for sample in after.get("superseded_samples", []):
            current_sample = one("SELECT source FROM training_samples WHERE id=?", (sample.get("id"),))
            if current_sample is None or current_sample["source"] != "undone":
                raise ValueError("a superseded training sample changed after this action")
            execute(
                "UPDATE training_samples SET source=? WHERE id=?",
                (sample["source"], sample["id"]),
            )

    latest_element = get_element(element_id)
    undo_id = _feedback(
        current,
        "undo",
        _element_state(current),
        {**_element_state(latest_element), "undo_of": feedback_id},
        engineer,
        f"Undo {entry['action']}",
    )
    return {"element": latest_element, "restored": restored, "feedback_id": undo_id, "undone_feedback_id": feedback_id}
