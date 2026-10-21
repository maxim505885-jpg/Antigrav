"""Inspect derived pilot slices without changing candidates or review labels."""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import file_digest
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle
import numpy as np

from scan2bim.geometry.section import CloudGeometry
from scan2bim.pointdata import NpyPointProvider, PointQuery
from scan2bim.recognition.geometric import DetectedElement, _occurrence_grid
from scan2bim.recognition.steel import _set_grid_state, classify_column_sections


def checksum(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/validation/pilot-A/revit/scan2bim-pilot-A.json")
    parser.add_argument("--crop", type=Path, default=ROOT / "data/validation/pilot-A")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.source.suffix.lower() != ".json" or args.out.exists():
        parser.error("use a JSON snapshot and a new output directory")
    snapshot = json.loads(args.source.read_text(encoding="utf-8"))
    meta = json.loads((args.crop / "recognition.json").read_text(encoding="utf-8"))
    origin = np.array(snapshot["source"]["origin"], dtype=float)
    if not np.array_equal(origin, np.array(meta["origin"])):
        parser.error("snapshot and derived crop origins differ")
    path = args.crop / "positions.npy"
    before = {"snapshot": checksum(args.source), "positions": checksum(path)}
    provider = NpyPointProvider(path, origin=origin)
    source_rows = np.load(args.crop / "source_indices.npy", mmap_mode="r", allow_pickle=False)
    if source_rows.shape != (provider.count,):
        parser.error("derived source row map does not match positions")
    args.out.mkdir(parents=True)
    originals = [item for item in snapshot["elements"] if item["class_name"] == "column"]
    geom = CloudGeometry(path, origin, np.array(meta["bbox_min"]), np.array(meta["bbox_max"]), provider.count)
    grid = _occurrence_grid(geom)
    _set_grid_state(grid)
    updated = [DetectedElement(**{key: deepcopy(item[key]) for key in
        ("class_name", "geometry", "bbox", "confidence", "measured", "inferred", "source", "dimensions") if key in item})
        for item in originals]
    classification_summary = classify_column_sections(grid, updated, origin)
    reports = []
    for number, (element, revised) in enumerate(zip(originals, updated), 1):
        geometry = element["geometry"]
        center = np.array(geometry["center"], dtype=float)
        angle = float(geometry.get("rotation_z", 0))
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        sizes = geometry["sizes"]
        corners = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]]) * np.array([sizes["length"], sizes["thickness"]]) / 2
        corners = corners @ rotation.T + center[:2]
        lower = np.minimum(np.array(element["bbox"]["min"]), np.r_[corners.min(axis=0), element["bbox"]["min"][2]])
        upper = np.maximum(np.array(element["bbox"]["max"]), np.r_[corners.max(axis=0), element["bbox"]["max"][2]])
        lower[:2] -= .3
        upper[:2] += .3
        roi_parts, roi_rows = [], []
        for batch in provider.iter_points(PointQuery(tuple(lower) + tuple(upper))):
            roi_parts.append(batch.xyz)
            roi_rows.append(batch.source_indices)
        roi_xyz = np.concatenate(roi_parts) if roi_parts else np.empty((0, 3))
        roi_ids = np.concatenate(roi_rows) if roi_rows else np.empty(0, dtype=np.int64)
        local_xy = (roi_xyz[:, :2] - center[:2]) @ rotation
        inside = (np.abs(local_xy) <= np.array([sizes["length"], sizes["thickness"]]) / 2).all(axis=1)
        edges = np.arange(lower[2], upper[2] + .2, .2)
        counts, _ = np.histogram(roi_xyz[inside, 2], bins=edges)
        centers = (edges[:-1] + edges[1:]) / 2
        available, peaks = counts.copy(), []
        while len(peaks) < 5 and len(available) and available.max() >= 20:
            index = int(available.argmax())
            peaks.append(float(centers[index]))
            available[np.abs(centers - centers[index]) < .4] = 0
        levels = [*np.linspace(lower[2], upper[2], 7)[1:-1], *sorted(peaks), *([None] * (5 - len(peaks)))]
        fig, axes = plt.subplots(2, 5, figsize=(17, 8))
        fig.subplots_adjust(left=.05, right=.99, bottom=.08, top=.86, wspace=.45, hspace=.55)
        axes = axes.ravel()
        slices, stored = [], {}
        try:
            for i, (ax, z) in enumerate(zip(axes, levels)):
                selected = np.abs(roi_xyz[:, 2] - z) <= .1 if z is not None else np.zeros(len(roi_xyz), dtype=bool)
                xyz, row_ids = roi_xyz[selected], roi_ids[selected]
                stored[f"xyz_{i}"] = xyz
                stored[f"crop_row_ids_{i}"] = row_ids
                stored[f"stored_source_row_ids_{i}"] = np.asarray(source_rows[row_ids])
                step = max(1, int(np.ceil(len(xyz) / 20000)))
                visible = xyz[::step]
                ax.scatter(visible[:, 0] - center[0], visible[:, 1] - center[1], s=.6, alpha=.6, rasterized=True)
                ax.add_patch(Polygon(corners - center[:2], fill=False, edgecolor="tab:red", linestyle="--", linewidth=1))
                bbox = element["bbox"]
                ax.add_patch(Rectangle(np.array(bbox["min"][:2]) - center[:2],
                    bbox["max"][0] - bbox["min"][0], bbox["max"][1] - bbox["min"][1],
                    fill=False, edgecolor="tab:orange", linestyle=":", linewidth=1))
                observed = np.quantile(xyz[:, :2], [.02, .98], axis=0) if len(xyz) >= 20 else None
                spans = (observed[1] - observed[0]).tolist() if observed is not None else None
                slices.append({"world_z_m": float(z) if z is not None else None,
                    "sampling": "uniform_height" if i < 5 else "densest_observed_bands",
                    "thickness_m": .2, "source_point_count": len(xyz),
                    "displayed_point_count": len(visible), "observed_xy_quantile_span_m": spans,
                    "status": "raw_observations_not_fitted_section" if spans is not None else "insufficient_points"})
                title = f"{'Uniform' if i < 5 else 'Observed'} Z={z:.2f} m; n={len(xyz)}" if z is not None else "No additional band\nwith 20+ core points"
                ax.set_title(title, fontsize=9)
                ax.set(xlabel="world X offset, m", ylabel="world Y offset, m",
                    xlim=(lower[0] - center[0], upper[0] - center[0]), ylim=(lower[1] - center[1], upper[1] - center[1]))
                ax.set_aspect("equal", adjustable="box")
                ax.grid(alpha=.2)
            fig.suptitle(f"{element['id']} | raw derived points | red: candidate rectangle; orange: source bbox\n"
                f"candidate {sizes['length']:.3f} x {sizes['thickness']:.3f} m; no fit, no reference labels", fontsize=11)
            # Filenames use a controlled ordinal; source IDs are data, not paths.
            stem = f"column-{number:02d}"
            fig.savefig(args.out / f"{stem}.png", dpi=130)
            np.savez_compressed(args.out / f"{stem}.npz", **stored)
        finally:
            plt.close(fig)
        reports.append({"element_id": element["id"], "preview": f"{stem}.png", "slice_data": f"{stem}.npz",
            "query_bounds_world_m": [*lower.tolist(), *upper.tolist()], "slices": slices,
            "raw_height_profile": [{"world_z_m": float(z), "points_inside_candidate": int(count)} for z, count in zip(centers, counts)],
            "old_dimensions": element["dimensions"], "recomputed_dimensions": revised.dimensions,
            "profile_recomputed": "section_method" in revised.metadata,
            "geometry_changed": revised.geometry != element["geometry"]})
        print(json.dumps({"column": number, "total": len(originals), "id": element["id"],
            "points_per_slice": [s["source_point_count"] for s in slices]}), flush=True)
    after = {"snapshot": checksum(args.source), "positions": checksum(path)}
    assert before == after, "derived inputs changed while generating evidence"
    report = {"schema": "scan.column-section-review/1", "source_checksums": before,
        "source_files_unchanged": True, "point_row_ids_are_not_station_ids": True,
        "notes": "No production DB or FARO source opened. Slice spans are observations, not fitted or confirmed dimensions.",
        "classification_summary": classification_summary, "columns": reports}
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
