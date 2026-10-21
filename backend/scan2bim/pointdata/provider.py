"""Read-only NPY provider; linear scan today, replaceable spatial index later.

All query and output coordinates are world-space metres. Input coordinates are
local offsets. source_indices are row IDs, NOT scanner station IDs: the latter
cannot be recovered from a unified cloud. No implicit decimation is performed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np


@dataclass(frozen=True)
class PointQuery:
    bounds: tuple[float, float, float, float, float, float]

    def __post_init__(self) -> None:
        values = np.asarray(self.bounds, dtype=np.float64)
        if values.shape != (6,) or not np.isfinite(values).all():
            raise ValueError("bounds must contain six finite world coordinates")
        if np.any(values[:3] > values[3:]):
            raise ValueError("bounds minimum exceeds maximum")
        object.__setattr__(self, "bounds", tuple(float(v) for v in values))


@dataclass(frozen=True)
class PointBatch:
    xyz: np.ndarray
    rgb: np.ndarray | None
    source_indices: np.ndarray


class NpyPointProvider:
    """Iterate a bounding box without materialising the complete stored cloud."""

    def __init__(self, positions_path: str | Path, *, origin,
                 colors_path: str | Path | None = None, chunk_size: int = 500_000):
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
            raise ValueError("chunk_size must be a positive integer")
        self.positions_path = Path(positions_path)
        self.colors_path = Path(colors_path) if colors_path is not None else None
        self.origin = np.asarray(origin, dtype=np.float64).copy()
        if self.origin.shape != (3,) or not np.isfinite(self.origin).all():
            raise ValueError("origin must contain three finite coordinates")
        self.origin.setflags(write=False)
        self.chunk_size = chunk_size
        positions = np.load(self.positions_path, mmap_mode="r", allow_pickle=False)
        if positions.ndim != 2 or positions.shape[1] != 3 or not np.issubdtype(positions.dtype, np.floating):
            raise ValueError("positions must be a floating point N x 3 array")
        self.count = len(positions)
        del positions
        if self.colors_path is not None:
            colors = np.load(self.colors_path, mmap_mode="r", allow_pickle=False)
            if colors.shape != (self.count, 3) or colors.dtype != np.uint8:
                raise ValueError("colors must be a uint8 N x 3 array matching positions")
            del colors

    def iter_points(self, query: PointQuery) -> Iterator[PointBatch]:
        positions = np.load(self.positions_path, mmap_mode="r", allow_pickle=False)
        colors = (np.load(self.colors_path, mmap_mode="r", allow_pickle=False)
                  if self.colors_path is not None else None)
        if positions.shape != (self.count, 3) or (colors is not None and colors.shape != (self.count, 3)):
            raise ValueError("stored cloud changed since provider creation")
        lower = np.asarray(query.bounds[:3], dtype=np.float64)
        upper = np.asarray(query.bounds[3:], dtype=np.float64)
        try:
            for start in range(0, self.count, self.chunk_size):
                # Promote BEFORE addition: float32 global coordinates would lose
                # millimetre detail for survey coordinates in the millions.
                xyz = np.asarray(positions[start:start + self.chunk_size], dtype=np.float64) + self.origin
                mask = np.isfinite(xyz).all(axis=1) & (xyz >= lower).all(axis=1) & (xyz <= upper).all(axis=1)
                selected = np.flatnonzero(mask)
                if selected.size:
                    yield PointBatch(xyz[mask],
                                     np.array(colors[start:start + self.chunk_size][mask], copy=True)
                                     if colors is not None else None,
                                     selected.astype(np.int64) + start)
        finally:
            del positions, colors
