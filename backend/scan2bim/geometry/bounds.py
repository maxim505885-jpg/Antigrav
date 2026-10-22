"""Axis-aligned bounds derived from supported structural geometry."""
from __future__ import annotations

import math
from typing import Any


def derive_bbox(geometry: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    kind = geometry.get("kind")
    if kind == "oriented_box":
        cx, cy, cz = (float(v) for v in geometry.get("center", (0.0, 0.0, 0.0)))
        length = float(geometry["sizes"]["length"])
        thickness = float(geometry["sizes"]["thickness"])
        height = float(geometry["sizes"]["height"])
        angle = float(geometry.get("rotation_z", 0.0))
        ca, sa = math.cos(angle), math.sin(angle)
        corners = [
            (cx + lx * ca - ly * sa, cy + lx * sa + ly * ca)
            for lx, ly in ((-length / 2, -thickness / 2), (length / 2, -thickness / 2),
                           (length / 2, thickness / 2), (-length / 2, thickness / 2))
        ]
        return {
            "min": [round(min(x for x, _ in corners), 3), round(min(y for _, y in corners), 3), round(cz - height / 2, 3)],
            "max": [round(max(x for x, _ in corners), 3), round(max(y for _, y in corners), 3), round(cz + height / 2, 3)],
        }
    if kind == "member" and geometry.get("p0") and geometry.get("p1"):
        section_value = geometry.get("section_m")
        if section_value is None:
            half = 0.0
        else:
            section = float(section_value)
            if not math.isfinite(section) or section <= 0:
                raise ValueError("member section_m must be finite and positive when provided")
            half = section / 2
        p0 = [float(v) for v in geometry["p0"]]
        p1 = [float(v) for v in geometry["p1"]]
        return {
            "min": [round(min(p0[i], p1[i]) - half, 3) for i in range(3)],
            "max": [round(max(p0[i], p1[i]) + half, 3) for i in range(3)],
        }
    if kind == "slab" and geometry.get("polygon"):
        points = geometry["polygon"]
        z = float(geometry.get("z", 0.0))
        half = float(geometry.get("assumed_thickness", 0.2)) / 2
        return {
            "min": [round(min(float(p[0]) for p in points), 3), round(min(float(p[1]) for p in points), 3), round(z - half, 3)],
            "max": [round(max(float(p[0]) for p in points), 3), round(max(float(p[1]) for p in points), 3), round(z + half, 3)],
        }
    return fallback or {"min": [0, 0, 0], "max": [0, 0, 0]}
