"""Feature vector for engineering elements.

Kept deliberately small and interpretable so a kNN prior can be trained from a
few reviewed examples and audited by an engineer.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

FEATURE_NAMES = [
    "length_m",
    "thickness_m",
    "height_m",
    "footprint_area_m2",
    "aspect_length_thickness",
    "height_to_length",
    "slenderness",
    "log_volume_m3",
    "abs_cos_rotation",
    "abs_sin_rotation",
    "confidence",
]


def _get(element: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    geom = element.get("geometry") or {}
    dims = element.get("dimensions") or {}
    bbox = element.get("bbox") or {}
    return geom, dims, bbox


def _bbox_extents(bbox: dict[str, Any]) -> tuple[float, float, float]:
    try:
        mn = bbox.get("min") or [0, 0, 0]
        mx = bbox.get("max") or [0, 0, 0]
        return (
            max(0.0, float(mx[0]) - float(mn[0])),
            max(0.0, float(mx[1]) - float(mn[1])),
            max(0.0, float(mx[2]) - float(mn[2])),
        )
    except Exception:
        return 0.0, 0.0, 0.0


def features_from_element(element: dict[str, Any]) -> dict[str, float]:
    geom, dims, bbox = _get(element)
    length = float(dims.get("length_m") or 0.0)
    thickness = float(dims.get("thickness_m") or 0.0)
    height = float(dims.get("height_m") or 0.0)
    area = float(dims.get("footprint_area_m2") or dims.get("area_m2") or 0.0)
    rotation = float(geom.get("rotation_z") or 0.0)
    if geom.get("kind") == "slab":
        bx, by, bz = _bbox_extents(bbox)
        length = length or max(bx, by)
        thickness = thickness or max(0.05, min(bx, by))
        height = height or bz
        area = area or float(geom.get("area") or max(0.0, bx * by))
    if geom.get("kind") == "oriented_box":
        sizes = geom.get("sizes") or {}
        length = length or float(sizes.get("length") or 0.0)
        thickness = thickness or float(sizes.get("thickness") or 0.0)
        height = height or float(sizes.get("height") or 0.0)
        area = area or length * thickness
    aspect = length / thickness if thickness > 1e-6 else 0.0
    height_to_length = height / length if length > 1e-6 else 0.0
    slenderness = height / max(thickness, 1e-3)
    volume = max(0.0, length * thickness * height)
    values = {
        "length_m": length,
        "thickness_m": thickness,
        "height_m": height,
        "footprint_area_m2": area,
        "aspect_length_thickness": aspect,
        "height_to_length": height_to_length,
        "slenderness": slenderness,
        "log_volume_m3": math.log1p(volume),
        "abs_cos_rotation": abs(math.cos(rotation)),
        "abs_sin_rotation": abs(math.sin(rotation)),
        "confidence": float(element.get("confidence") or 0.0),
    }
    clean: dict[str, float] = {}
    for name in FEATURE_NAMES:
        value = float(values.get(name, 0.0))
        clean[name] = round(value if math.isfinite(value) else 0.0, 6)
    return clean


def vector_from_features(features: dict[str, float], names: list[str] | None = None) -> np.ndarray:
    keys = names or FEATURE_NAMES
    return np.asarray([float(features.get(k, 0.0)) for k in keys], dtype=np.float64)
