"""Neutral BIM model (JSON) shared by IFC export, Revit plugin and API clients."""
from __future__ import annotations

from typing import Any


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
    return {
        "schema": "scan2bim.bim/1.0",
        "units": "m",
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
        },
        "levels": storeys,
        "elements": [
            {
                "id": el["id"],
                "class_name": el["class_name"],
                "geometry": el["geometry"],
                "bbox": el["bbox"],
                "confidence": el["confidence"],
                "confidence_kind": el.get("confidence_kind", "heuristic"),
                "measured": bool(el["measured"]),
                "inferred": bool(el.get("inferred")),
                "source": el.get("source", "geometric"),
                "review_status": el.get("review_status", "unreviewed"),
                "dimensions": el.get("dimensions", {}),
            }
            for el in elements
        ],
        "notes": [
            "Measured geometry is separated from inferred geometry via measured/inferred flags.",
            "Confidence is a heuristic score, not a calibrated probability.",
            "No material or load-bearing property is inferred from shape.",
        ],
    }
