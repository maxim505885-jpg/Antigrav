"""Immutable grid-to-row index: speeds local queries without copying XYZ/RGB.

Queries have bounded memory. Building the first version uses O(N) sorting
memory (~24 bytes per stored point plus sort workspace); no claim of fully
streaming construction is made. A manifest is written last as the completion
marker. Interrupted builds are ignored, never mistaken for complete indices.
"""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
import time
from typing import Iterator

import numpy as np

from .provider import NpyPointProvider, PointBatch, PointQuery


def fingerprint(provider: NpyPointProvider) -> dict:
    def stat(path):
        s = path.stat()
        return {"path": str(path.resolve()), "size": s.st_size, "mtime_ns": s.st_mtime_ns}
    return {"positions": stat(provider.positions_path), "origin": provider.origin.tolist(),
            "colors": stat(provider.colors_path) if provider.colors_path else None,
            "count": provider.count}


def build_index(provider: NpyPointProvider, directory: str | Path, cell_size: float = 5.0) -> dict:
    if not math.isfinite(cell_size) or cell_size <= 0:
        raise ValueError("cell_size must be finite and positive")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    source = fingerprint(provider)
    start_time = time.perf_counter()
    positions = np.load(provider.positions_path, mmap_mode="r", allow_pickle=False)
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for start in range(0, provider.count, provider.chunk_size):
        chunk = np.asarray(positions[start:start+provider.chunk_size], dtype=np.float64)
        finite = chunk[np.isfinite(chunk).all(axis=1)]
        if len(finite):
            lo, hi = np.minimum(lo, finite.min(axis=0)), np.maximum(hi, finite.max(axis=0))
    if not np.isfinite(lo).all():
        raise ValueError("source has no finite positions")
    # Local-space origin avoids cancellation for large survey coordinates.
    grid_min = np.floor(lo / cell_size) * cell_size
    shape = np.floor((hi-grid_min) / cell_size).astype(np.int64) + 1
    cells = math.prod(int(v) for v in shape)
    if cells > 2_000_000:
        raise ValueError("grid exceeds 2 million cells; increase cell_size")
    keys = np.full(provider.count, -1, dtype=np.int64)
    counts = np.zeros(cells, dtype=np.int64)
    for start in range(0, provider.count, provider.chunk_size):
        xyz = np.asarray(positions[start:start+provider.chunk_size], dtype=np.float64)
        valid = np.isfinite(xyz).all(axis=1)
        coords = np.floor((xyz[valid]-grid_min) / cell_size).astype(np.int64)
        cell_ids = (coords[:, 0] * shape[1] + coords[:, 1]) * shape[2] + coords[:, 2]
        keys[start:start+len(xyz)][valid] = cell_ids
        counts += np.bincount(cell_ids, minlength=cells)
    finite_count = int(counts.sum())
    order = np.argsort(keys, kind="stable")
    offsets = np.concatenate(([0], np.cumsum(counts)))
    np.save(directory / "rows.npy", order[provider.count-finite_count:])
    np.save(directory / "offsets.npy", offsets)
    if source != fingerprint(provider):
        raise ValueError("source changed during index build; index left incomplete")
    metadata = {"schema": "scan.point-index/1", "source": source, "cell_size": cell_size,
                "grid_min_local": grid_min.tolist(), "shape": shape.tolist(),
                "finite_count": finite_count, "excluded_nonfinite": provider.count-finite_count,
                "built_seconds": round(time.perf_counter()-start_time, 3),
                "resolution": "all finite rows of stored array; no decimation"}
    temp = directory / "manifest.tmp"
    temp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    temp.replace(directory / "manifest.json")
    return metadata


class IndexedPointProvider:
    def __init__(self, source: NpyPointProvider, directory: str | Path):
        self.source = source
        self.directory = Path(directory)
        manifest = self.directory / "manifest.json"
        if not manifest.exists():
            raise ValueError("incomplete spatial index (manifest missing)")
        self.metadata = json.loads(manifest.read_text(encoding="utf-8"))
        if self.metadata.get("schema") != "scan.point-index/1":
            raise ValueError("unsupported spatial index")
        if self.metadata["source"] != fingerprint(source):
            raise ValueError("spatial index does not match source")
        self.shape = np.array(self.metadata["shape"], dtype=np.int64)
        self.grid_min = np.array(self.metadata["grid_min_local"], dtype=np.float64)
        self.cell_size = self.metadata["cell_size"]
        offsets = np.load(self.directory / "offsets.npy", mmap_mode="r", allow_pickle=False)
        rows = np.load(self.directory / "rows.npy", mmap_mode="r", allow_pickle=False)
        if (offsets.dtype != np.int64 or rows.dtype != np.int64 or rows.ndim != 1
                or offsets.shape != (math.prod(self.shape)+1,) or offsets[0] != 0
                or offsets[-1] != len(rows) or len(rows) != self.metadata["finite_count"]
                or (np.diff(offsets) < 0).any()):
            raise ValueError("corrupt spatial index")

    def iter_points(self, query: PointQuery) -> Iterator[PointBatch]:
        if self.metadata["source"] != fingerprint(self.source):
            raise ValueError("source changed after index creation")
        lower, upper = np.asarray(query.bounds[:3]), np.asarray(query.bounds[3:])
        # World->local subtraction can round a boundary into the adjacent cell.
        # Expand the candidate-cell search by a few float64 ULPs, then apply the
        # original exact world bounds below; returned measurements are unchanged.
        magnitude = np.maximum(np.maximum(np.abs(lower), np.abs(upper)), np.abs(self.source.origin))
        padding = np.spacing(magnitude) * 4
        lower_cell = np.floor((lower-self.source.origin-self.grid_min-padding) / self.cell_size)
        upper_cell = np.floor((upper-self.source.origin-self.grid_min+padding) / self.cell_size)
        if (upper_cell < 0).any() or (lower_cell >= self.shape).any():
            return
        # Clamp in float before casting, including queries with very large extents.
        lower_cell = np.maximum(lower_cell, 0).astype(np.int64)
        upper_cell = np.minimum(upper_cell, self.shape-1).astype(np.int64)
        positions = np.load(self.source.positions_path, mmap_mode="r", allow_pickle=False)
        colors = (np.load(self.source.colors_path, mmap_mode="r", allow_pickle=False)
                  if self.source.colors_path else None)
        rows = np.load(self.directory / "rows.npy", mmap_mode="r", allow_pickle=False)
        offsets = np.load(self.directory / "offsets.npy", mmap_mode="r", allow_pickle=False)
        try:
            for x, y, z in itertools.product(*(range(int(a),int(b)+1) for a,b in zip(lower_cell,upper_cell))):
                cell = (x*self.shape[1]+y)*self.shape[2]+z
                begin, end = int(offsets[cell]), int(offsets[cell+1])
                for start in range(begin, end, self.source.chunk_size):
                    indices = np.asarray(rows[start:min(start+self.source.chunk_size,end)])
                    if len(indices) and (indices.min() < 0 or indices.max() >= self.source.count):
                        raise ValueError("corrupt source row in index")
                    xyz = np.asarray(positions[indices], dtype=np.float64) + self.source.origin
                    selected = (xyz >= lower).all(axis=1) & (xyz <= upper).all(axis=1)
                    if selected.any():
                        yield PointBatch(xyz[selected], np.asarray(colors[indices][selected])
                                         if colors is not None else None,
                                         np.array(indices[selected], copy=True))
        finally:
            del positions, colors, rows, offsets
