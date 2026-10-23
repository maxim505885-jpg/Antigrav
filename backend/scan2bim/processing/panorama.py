"""Scan Station and Panoramic View metadata and image generator.

Supports:
- Station discovery and metadata extraction (center X0, Y0, Z0, orientation, point count).
- Synthetic and real spherical equirectangular panoramic image generation for station inspection.
- Bubble-view raycasting projection (pixel UV to 3D ray direction).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping
import numpy as np


def project_uv_to_ray(u: float, v: float) -> np.ndarray:
    """Map equirectangular panoramic UV coordinates [0..1] to a normalized 3D ray direction vector [x, y, z].

    u in [0, 1] -> azimuth phi in [-pi, pi]
    v in [0, 1] -> elevation theta in [-pi/2, pi/2]
    """
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        raise ValueError(f"UV coordinates must be in [0, 1], got u={u}, v={v}")

    phi = (u - 0.5) * 2.0 * math.pi
    theta = (0.5 - v) * math.pi

    x = math.cos(theta) * math.sin(phi)
    y = math.cos(theta) * math.cos(phi)
    z = math.sin(theta)

    ray = np.array([x, y, z], dtype=np.float64)
    norm = np.linalg.norm(ray)
    return ray / norm if norm > 0 else np.array([0.0, 1.0, 0.0])


def project_point_to_uv(point: np.ndarray, station_center: np.ndarray) -> tuple[float, float, float]:
    """Map 3D world point to equirectangular UV coordinates relative to station center.

    Returns (u, v, distance).
    """
    diff = np.asarray(point, dtype=np.float64) - np.asarray(station_center, dtype=np.float64)
    distance = float(np.linalg.norm(diff))
    if distance < 1e-6:
        return 0.5, 0.5, 0.0

    x, y, z = diff
    phi = math.atan2(x, y)  # in [-pi, pi]
    theta = math.asin(np.clip(z / distance, -1.0, 1.0))  # in [-pi/2, pi/2]

    u = (phi / (2.0 * math.pi)) + 0.5
    v = 0.5 - (theta / math.pi)
    return float(np.clip(u, 0.0, 1.0)), float(np.clip(v, 0.0, 1.0)), distance


def generate_station_depth_panorama(
    points: np.ndarray,
    station_center: np.ndarray,
    width: int = 1024,
    height: int = 512,
    max_range_m: float = 50.0,
) -> np.ndarray:
    """Generate equirectangular depth map (height x width, float32) from 3D points relative to station center.

    Pixels without points contain np.nan.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError("points must be an N×3 array")

    diff = pts - np.asarray(station_center, dtype=np.float64)
    dist = np.linalg.norm(diff, axis=1)
    valid = (dist > 0.05) & (dist <= max_range_m)
    diff = diff[valid]
    dist = dist[valid]

    depth_map = np.full((height, width), np.nan, dtype=np.float32)
    if len(dist) == 0:
        return depth_map

    phi = np.arctan2(diff[:, 0], diff[:, 1])
    theta = np.arcsin(np.clip(diff[:, 2] / dist, -1.0, 1.0))

    u = (phi / (2.0 * np.pi)) + 0.5
    v = 0.5 - (theta / np.pi)

    px = np.clip((u * (width - 1)).astype(np.int32), 0, width - 1)
    py = np.clip((v * (height - 1)).astype(np.int32), 0, height - 1)

    for i in range(len(dist)):
        curr = depth_map[py[i], px[i]]
        if np.isnan(curr) or dist[i] < curr:
            depth_map[py[i], px[i]] = np.float32(dist[i])

    return depth_map
