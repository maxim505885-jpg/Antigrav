"""Synthetic room with known dimensions for demos and tests.

Ground truth: 6.0 x 4.0 m footprint, 3.0 m clear height, 0.20 m walls,
0.40 x 0.40 m column at (1.5, 1.5)-(1.9, 1.9).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

TRUTH = {
    "width_x": 6.0,
    "depth_y": 4.0,
    "height_z": 3.0,
    "wall_thickness": 0.20,
    "column_size": 0.40,
    "column_origin": [1.5, 1.5],
    "room_inner": [5.6, 3.6],
    "floor_area": 24.0,
}


def _grid(a0: float, a1: float, b0: float, b1: float, spacing: float) -> tuple[np.ndarray, np.ndarray]:
    na = max(2, int(round((a1 - a0) / spacing)) + 1)
    nb = max(2, int(round((b1 - b0) / spacing)) + 1)
    a = np.linspace(a0, a1, na)
    b = np.linspace(b0, b1, nb)
    A, B = np.meshgrid(a, b, indexing="ij")
    return A.ravel(), B.ravel()


def generate_room_points(spacing: float = 0.04, seed: int = 42) -> tuple[np.ndarray, np.ndarray, dict]:
    spacing = float(spacing)
    W, D, H = TRUTH["width_x"], TRUTH["depth_y"], TRUTH["height_z"]
    T = TRUTH["wall_thickness"]
    parts: list[np.ndarray] = []

    # Floor and ceiling.
    x, y = _grid(0, W, 0, D, spacing)
    parts.append(np.column_stack([x, y, np.zeros_like(x)]))
    parts.append(np.column_stack([x, y, np.full_like(x, H)]))

    # Wall surfaces (both faces of each wall).
    for x0 in (0.0, T, W - T, W):
        y2, z = _grid(0, D, 0, H, spacing)
        parts.append(np.column_stack([np.full_like(y2, x0), y2, z]))
    for y0 in (0.0, T, D - T, D):
        x2, z = _grid(0, W, 0, H, spacing)
        parts.append(np.column_stack([x2, np.full_like(x2, y0), z]))

    # Column faces.
    cx, cy = TRUTH["column_origin"]
    size = TRUTH["column_size"]
    for x0 in (cx, cx + size):
        y2, z = _grid(cy, cy + size, 0, H, spacing)
        parts.append(np.column_stack([np.full_like(y2, x0), y2, z]))
    for y0 in (cy, cy + size):
        x2, z = _grid(cx, cx + size, 0, H, spacing)
        parts.append(np.column_stack([x2, np.full_like(x2, y0), z]))

    xyz = np.concatenate(parts, axis=0)
    # Small scanned noise, deterministic.
    rng = np.random.default_rng(seed)
    xyz = xyz + rng.normal(0, 0.002, size=xyz.shape)
    base = np.array([180, 185, 190], dtype=np.uint8)
    rgb = np.tile(base, (len(xyz), 1))
    return xyz, rgb, dict(TRUTH)


def write_room_ply(path: str | Path, spacing: float = 0.04) -> dict:
    from plyfile import PlyData, PlyElement

    xyz, rgb, truth = generate_room_points(spacing=spacing)
    vertex = np.empty(
        len(xyz),
        dtype=[
            ("x", "f4"),
            ("y", "f4"),
            ("z", "f4"),
            ("red", "u1"),
            ("green", "u1"),
            ("blue", "u1"),
        ],
    )
    vertex["x"] = xyz[:, 0]
    vertex["y"] = xyz[:, 1]
    vertex["z"] = xyz[:, 2]
    vertex["red"] = rgb[:, 0]
    vertex["green"] = rgb[:, 1]
    vertex["blue"] = rgb[:, 2]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    PlyData([PlyElement.describe(vertex, "vertex")], text=False).write(str(path))
    truth["point_count"] = int(len(xyz))
    truth["file"] = str(path)
    return truth
