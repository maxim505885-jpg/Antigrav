"""Orchestrate point-cloud candidate recognition and review-only draft exports.

This module never invents grid coordinates, member sizes, supports, or element
counts. Recognition results remain unreviewed candidates; the generated SPDS
album is explicitly a draft and is not a construction release.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from .cad.spds_full_set import generate_full_spds_album
from .geometry.section import CloudGeometry
from .pointdata.octree import PreviewLodBuilder
from .recognition.geometric import detect_structures


def _load_geometry(positions_path: Path) -> tuple[CloudGeometry, dict[str, Any]]:
    """Build recognition geometry from stored points and their optional metadata."""
    points = np.load(positions_path, mmap_mode="r")
    if points.ndim != 2 or points.shape[1] < 3 or len(points) == 0:
        raise ValueError("positions.npy must contain a non-empty N x >=3 point array")
    if not (np.issubdtype(points.dtype, np.integer) or np.issubdtype(points.dtype, np.floating)):
        raise ValueError("positions.npy must contain real numeric coordinates")
    local_min = np.asarray(points[:, :3].min(axis=0), dtype=np.float64)
    local_max = np.asarray(points[:, :3].max(axis=0), dtype=np.float64)

    meta_path = positions_path.parent / "meta.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    if not isinstance(metadata, dict):
        raise ValueError("cloud metadata must be a JSON object")
    raw_origin = metadata.get("origin")
    has_world_origin = (
        isinstance(raw_origin, list) and len(raw_origin) == 3
        and all(not isinstance(value, bool) and isinstance(value, (int, float))
                and np.isfinite(value) for value in raw_origin)
    )
    origin = np.asarray(raw_origin if has_world_origin else [0.0, 0.0, 0.0], dtype=np.float64)
    bbox_min = np.asarray(metadata.get("bbox_min", local_min + origin), dtype=np.float64)
    bbox_max = np.asarray(metadata.get("bbox_max", local_max + origin), dtype=np.float64)
    if (origin.shape != (3,) or bbox_min.shape != (3,) or bbox_max.shape != (3,)
            or not np.isfinite(origin).all() or not np.isfinite(bbox_min).all()
            or not np.isfinite(bbox_max).all()):
        raise ValueError("cloud metadata origin and bounds must be finite 3D coordinates")
    if not np.allclose(bbox_min - origin, local_min, rtol=1e-4, atol=1e-3) or not np.allclose(
        bbox_max - origin, local_max, rtol=1e-4, atol=1e-3
    ):
        raise ValueError("cloud metadata bounds do not match the stored positions")

    raw_ranges = metadata.get("station_row_ranges")
    station_row_ranges = None
    if raw_ranges is not None:
        if not isinstance(raw_ranges, list) or not raw_ranges:
            raise ValueError("station row ranges must be a non-empty list")
        station_row_ranges = []
        expected_start = 0
        station_ids: set[str] = set()
        for row in raw_ranges:
            if not isinstance(row, dict):
                raise ValueError("station row range entries must be objects")
            station_id = row.get("station_id")
            start = row.get("source_row_start")
            end = row.get("source_row_end_exclusive")
            count = row.get("source_row_count")
            index_base = row.get("source_row_index_base")
            if not isinstance(station_id, str) or not station_id.strip() or station_id in station_ids:
                raise ValueError("station row range station IDs must be non-empty and unique")
            if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end, count)):
                raise ValueError("station row range bounds and count must be integers")
            if (
                isinstance(index_base, bool) or not isinstance(index_base, int) or index_base != 0
                or start != expected_start or end <= start or end - start != count
            ):
                raise ValueError("station row ranges must be contiguous, zero-based, and match their counts")
            station_ids.add(station_id)
            expected_start = end
            station_row_ranges.append({
                "station_id": station_id,
                "source_row_start": start,
                "source_row_end_exclusive": end,
                "source_row_count": count,
                "source_row_index_base": index_base,
            })
        if expected_start != len(points):
            raise ValueError("station row ranges must cover every stored position exactly once")
        station_count = metadata.get("station_count")
        if station_count is not None and station_count != len(station_row_ranges):
            raise ValueError("station row range count does not match cloud station_count")

    geometry = CloudGeometry(
        positions_path=positions_path,
        origin=origin,
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        count=len(points),
    )
    provenance = {
        "positions_path": str(positions_path.resolve()),
        "coordinate_frame": "source_cloud_world" if has_world_origin else "positions_local_origin_unknown",
        "origin_m": origin.tolist(),
        "source_sha256": metadata.get("checksum_sha256"),
        "point_count": int(len(points)),
        "station_row_ranges": station_row_ranges,
    }
    return geometry, provenance


def _candidate_record(element: Any) -> dict[str, Any]:
    """Serialize a measured recognizer output as an unreviewed candidate."""
    source_rows = element.metadata.get("source_point_ids", [])
    identity = json.dumps(
        {
            "class_name": element.class_name,
            "geometry": element.geometry,
            "source_point_ids": source_rows,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
    ).encode("utf-8")
    proposal_id = element.metadata.get("member_proposal_id")
    element_id = proposal_id or "candidate-" + hashlib.sha256(identity).hexdigest()[:24]
    return {
        "id": str(element_id),
        "class_name": element.class_name,
        "geometry": element.geometry,
        "bbox": element.bbox,
        "confidence": float(element.confidence),
        "confidence_kind": "heuristic",
        "measured": bool(element.measured),
        "inferred": bool(element.inferred),
        "source": element.source,
        "dimensions": element.dimensions,
        "metadata": element.metadata,
        "review_status": "unreviewed",
    }


class WorkshopPipeline:
    """Run measured recognition and produce a review-only drawing package."""

    def __init__(self, output_root: str | Path = "data/output/workshop_draft"):
        self.output_root = Path(output_root)

    def execute_pipeline(
        self,
        positions_path: str | Path,
        project_title: str = "Производственный корпус",
        progress=None,
    ) -> dict[str, Any]:
        source = Path(positions_path)
        if not source.is_file():
            raise FileNotFoundError(f"positions file not found: {source}")
        self.output_root.mkdir(parents=True, exist_ok=True)

        geometry, provenance = _load_geometry(source)
        preview_manifest = PreviewLodBuilder().build_lod_pyramid(
            source, self.output_root / "preview_lod",
        )
        candidates_file = self.output_root / "candidates.json"
        if candidates_file.is_file() and candidates_file.stat().st_size > 100:
            candidates = json.loads(candidates_file.read_text(encoding="utf-8"))
            stats = {"points_processed": geometry.count}
            warnings = []
        else:
            result = detect_structures(geometry, progress)
            candidates = [_candidate_record(element) for element in result.elements]
            candidates_file.write_text(
                json.dumps(candidates, ensure_ascii=False, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            stats = result.stats
            warnings = result.warnings

        album = generate_full_spds_album(
            candidates,
            output_dir=self.output_root / "spds_draft",
            project_title=project_title,
            source_frame=provenance["coordinate_frame"],
            source_provenance={
                key: value for key, value in provenance.items()
                if key != "positions_path"
            },
        )
        report = {
            "status": "completed_with_review_candidates",
            "issue": "draft",
            "release_ready": False,
            "source": provenance,
            "points_processed_by_recognizer": int(stats.get("points_processed", geometry.count)),
            "candidate_count": len(candidates),
            "candidate_counts_by_class": dict(sorted(Counter(
                item["class_name"] for item in candidates
            ).items())),
            "recognition_stats": stats,
            "warnings": warnings,
            "preview_manifest": str((self.output_root / "preview_lod" / "preview_manifest.json").resolve()),
            "spds_album_manifest": album.get("manifest_path", str(album.get("album_pdf_path", ""))),
            "spds_sheets_generated": len(album["sheets"]),
            "ifc_export": "not_generated",
            "native_recap_project": "not_generated; a sampled web preview is not an RCP/RCS package",
            "output_directory": str(self.output_root.resolve()),
        }
        (self.output_root / "pipeline_summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        return report


# Kept temporarily for the existing command name; it no longer implies one
# physical pass over the cloud or a native ReCap package.
SinglePassWorkshopEngine = WorkshopPipeline
