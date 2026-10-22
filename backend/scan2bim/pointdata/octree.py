"""Small deterministic point samples for fast web previews.

This is not a spatial octree and does not create Autodesk ReCap RCP/RCS data.
It samples rows from an existing NPY point array and leaves the full array
untouched for local inspection and recognition.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


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


# Compatibility alias for the earlier experimental script; it never produced
# a native ReCap package despite the old name.
ReCapOctreeBuilder = PreviewLodBuilder
