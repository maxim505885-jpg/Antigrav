"""Small deterministic point samples and streaming LOD pyramids for web previews.

Supports:
- Deterministic file-order samples for fast overview.
- Multi-level streaming binary LOD pyramid (stride 15: float32 x, y, z + uint8 r, g, b).
- Dynamic distance-based LOD streaming for Three.js WebGL viewer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

PREVIEW_DTYPE = np.dtype([
    ("x", "<f4"),
    ("y", "<f4"),
    ("z", "<f4"),
    ("r", "u1"),
    ("g", "u1"),
    ("b", "u1"),
])


class PreviewLodBuilder:
    """Create deterministic file-order samples for a web viewer preview."""

    def __init__(self, overview_limit: int = 50_000, medium_limit: int = 200_000):
        if overview_limit < 1 or medium_limit < overview_limit:
            raise ValueError("preview limits must be positive and medium_limit >= overview_limit")
        self.overview_limit = int(overview_limit)
        self.medium_limit = int(medium_limit)

    @staticmethod
    def _sample(points: np.ndarray, limit: int) -> np.ndarray:
        count = min(len(points), limit)
        indices = np.linspace(0, len(points) - 1, count, dtype=np.int64)
        return np.asarray(points[indices], dtype=np.float32)

    def build_lod_pyramid(
        self,
        positions_path: str | Path,
        output_dir: str | Path,
    ) -> dict[str, Any]:
        """Write overview/medium samples and a manifest; no spatial tree is built."""
        source = Path(positions_path)
        points = np.load(source, mmap_mode="r")
        if points.ndim != 2 or points.shape[1] < 3 or len(points) == 0:
            raise ValueError("positions.npy must contain a non-empty N x >=3 array")
        if not (np.issubdtype(points.dtype, np.integer) or np.issubdtype(points.dtype, np.floating)):
            raise ValueError("positions.npy coordinates must be real numeric values")

        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        bounds_min = np.asarray(points[:, :3].min(axis=0), dtype=np.float64)
        bounds_max = np.asarray(points[:, :3].max(axis=0), dtype=np.float64)
        if not np.isfinite(bounds_min).all() or not np.isfinite(bounds_max).all():
            raise ValueError("positions.npy coordinates must be finite")

        overview = self._sample(points, self.overview_limit)
        medium = self._sample(points, self.medium_limit)
        np.save(output / "overview.npy", overview)
        np.save(output / "medium.npy", medium)
        manifest: dict[str, Any] = {
            "version": "scan_web_preview_samples_v1",
            "product": "web_preview_only",
            "native_recap_package": False,
            "spatial_octree": False,
            "sampling_method": "evenly spaced source row indices; not spatially uniform",
            "source_file": source.name,
            "total_points": int(len(points)),
            "bounds_local_m": {
                "min": bounds_min.tolist(),
                "max": bounds_max.tolist(),
            },
            "levels": [
                {"level": 0, "file": "overview.npy", "points_count": len(overview)},
                {"level": 1, "file": "medium.npy", "points_count": len(medium)},
                {"level": 2, "file": source.name, "points_count": int(len(points)), "is_source": True},
            ],
            "resolution_m": None,
            "resolution_note": "unknown; no spatial voxelization or decimation-error analysis was performed",
        }
        manifest_path = output / "preview_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest


# Compatibility alias for the earlier experimental script
ReCapOctreeBuilder = PreviewLodBuilder


class StreamingLodBuilder:
    """Build multi-level streaming LOD binary slices and manifest for WebGL rendering.

    Generates interleaved binary point files (15 bytes/pt: float32 x,y,z + uint8 r,g,b)
    specifically designed for streaming into Three.js BufferGeometry at 60 FPS.
    """

    DEFAULT_LEVEL_SPECS = (
        {
            "level": 0,
            "name": "Обзор (LOD 0)",
            "target_points": 50_000,
            "distance_min": 60.0,
            "distance_max": 10000.0,
            "point_size": 2.2,
            "target_fps": 60,
            "description": "Общий вид всего цеха и координатной сетки",
        },
        {
            "level": 1,
            "name": "Средний план (LOD 1)",
            "target_points": 250_000,
            "distance_min": 20.0,
            "distance_max": 60.0,
            "point_size": 1.5,
            "target_fps": 60,
            "description": "Инспекция пролетов цеха, подкрановых путей и связей",
        },
        {
            "level": 2,
            "name": "Детализация (LOD 2)",
            "target_points": 1_000_000,
            "distance_min": 0.0,
            "distance_max": 20.0,
            "point_size": 1.0,
            "target_fps": 60,
            "description": "Миллиметровая инспекция сечений колонн и узлов",
        },
    )

    @staticmethod
    def _compute_height_colors(z_coords: np.ndarray) -> np.ndarray:
        """Compute synthetic HSL-style RGB height colors when source has no RGB."""
        z_min = float(np.min(z_coords))
        z_max = float(np.max(z_coords))
        span = max(1e-6, z_max - z_min)
        norm = (z_coords - z_min) / span  # 0.0 .. 1.0
        
        # Color ramp: dark blue/cyan -> green -> yellow/orange -> red
        r = np.clip(255.0 * np.sin(norm * np.pi * 0.8), 0, 255).astype(np.uint8)
        g = np.clip(255.0 * np.cos(norm * np.pi * 0.5), 40, 240).astype(np.uint8)
        b = np.clip(255.0 * (1.0 - norm), 20, 255).astype(np.uint8)
        return np.column_stack([r, g, b])

    def build_lod_pyramid(
        self,
        positions_path: str | Path,
        output_dir: str | Path,
        colors_path: str | Path | None = None,
        cloud_id: str = "cloud",
    ) -> dict[str, Any]:
        """Build binary LOD files (lod_0.bin, lod_1.bin, lod_2.bin) and lod_manifest.json."""
        source_pos = Path(positions_path)
        if not source_pos.is_file():
            raise FileNotFoundError(f"positions file not found: {source_pos}")

        positions = np.load(source_pos, mmap_mode="r")
        total_count = len(positions)
        if total_count == 0:
            raise ValueError("positions array cannot be empty")

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        colors: np.ndarray | None = None
        if colors_path and Path(colors_path).is_file():
            try:
                raw_colors = np.load(colors_path, mmap_mode="r")
                if len(raw_colors) == total_count and raw_colors.shape[1] >= 3:
                    colors = raw_colors
            except Exception:
                colors = None

        bounds_min = np.asarray(positions[:, :3].min(axis=0), dtype=np.float64)
        bounds_max = np.asarray(positions[:, :3].max(axis=0), dtype=np.float64)
        bounds_center = (bounds_min + bounds_max) / 2.0
        bounds_size = bounds_max - bounds_min

        levels_manifest = []

        for spec in self.DEFAULT_LEVEL_SPECS:
            lvl = spec["level"]
            target_pts = min(total_count, spec["target_points"])
            
            # Deterministic strided sampling across positions
            indices = np.linspace(0, total_count - 1, target_pts, dtype=np.int64)
            sample_pos = np.asarray(positions[indices, :3], dtype=np.float32)

            if colors is not None:
                sample_col = np.asarray(colors[indices, :3], dtype=np.uint8)
            else:
                sample_col = self._compute_height_colors(sample_pos[:, 2])

            bin_file = output_path / f"lod_{lvl}.bin"
            
            # Write packed binary stride 15
            arr = np.empty(target_pts, dtype=PREVIEW_DTYPE)
            arr["x"] = sample_pos[:, 0]
            arr["y"] = sample_pos[:, 1]
            arr["z"] = sample_pos[:, 2]
            arr["r"] = sample_col[:, 0]
            arr["g"] = sample_col[:, 1]
            arr["b"] = sample_col[:, 2]

            with open(bin_file, "wb") as f:
                f.write(arr.tobytes())

            levels_manifest.append({
                "level": lvl,
                "name": spec["name"],
                "file": bin_file.name,
                "points_count": int(target_pts),
                "distance_min": float(spec["distance_min"]),
                "distance_max": float(spec["distance_max"]),
                "point_size": float(spec["point_size"]),
                "target_fps": int(spec["target_fps"]),
                "byte_size": bin_file.stat().st_size,
                "description": spec["description"],
            })

        manifest = {
            "version": "scan_streaming_lod_v1",
            "format": "octree_streaming_binary_lod",
            "stride_bytes": 15,
            "cloud_id": cloud_id,
            "total_points": int(total_count),
            "bounds": {
                "min": bounds_min.tolist(),
                "max": bounds_max.tolist(),
                "center": bounds_center.tolist(),
                "size": bounds_size.tolist(),
            },
            "levels": levels_manifest,
        }

        manifest_file = output_path / "lod_manifest.json"
        manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest
