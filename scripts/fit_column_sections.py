"""Review-fit individual derived pilot slices without editing candidates or labels."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from scan2bim.structure.section_fitting import fit_circular_section, fit_rectangular_section


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=ROOT / "data/validation/pilot-A/column-section-review-v3")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--known-sides-m", type=float, nargs=2, metavar=("A", "B"), help="explicit measured side lengths, metres")
    parser.add_argument("--tolerance-m", type=float, default=.004)
    parser.add_argument("--min-points", type=int, default=100)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output file already exists; choose a new output path")
    if args.min_points < 2:
        parser.error("--min-points must be at least 2")
    report_path = args.review / "report.json"
    if not report_path.is_file():
        parser.error("review report.json is missing")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    results = []
    for column in report["columns"]:
        npz_path = args.review / column["slice_data"]
        if not npz_path.is_file():
            raise FileNotFoundError(npz_path)
        npz_hash = sha256(npz_path)
        with np.load(npz_path, allow_pickle=False) as slices:
            for index, slice_meta in enumerate(column["slices"]):
                key = f"xyz_{index}"
                points3d = slices[key]
                result = {"column_candidate_id": column["element_id"], "slice_index": index,
                    "world_z_m": slice_meta["world_z_m"], "source_sampling": slice_meta["sampling"],
                    "source_point_count": int(len(points3d)), "input_sha256": npz_hash}
                if len(points3d) < args.min_points:
                    result.update({"status": "insufficient_points", "hypotheses": [], "observed_faces": [],
                                   "shape_hypotheses": [], "shape_status": "unknown",
                                   "input_point_count": int(len(points3d)), "review_required": True})
                else:
                    # Input NPZ contains a context crop. Keep the fitted result clearly
                    # marked as a slice proposal, with its original point-row indices.
                    fitted = fit_rectangular_section(points3d[:, :2],
                        known_sides_m=tuple(args.known_sides_m) if args.known_sides_m else None,
                        distance_tolerance_m=args.tolerance_m)
                    circle = fit_circular_section(points3d[:, :2], distance_tolerance_m=args.tolerance_m)
                    shapes = [circle] if circle is not None else []
                    derived_source_rows = slices.get(f"stored_source_row_ids_{index}")
                    for shape in shapes:
                        shape["derived_source_row_ids"] = (
                            sorted(int(derived_source_rows[row]) for row in shape["input_point_indices"])
                            if derived_source_rows is not None else []
                        )
                    fitted["shape_hypotheses"] = shapes
                    fitted["shape_status"] = (
                        "ambiguous" if shapes and fitted["hypotheses"]
                        else "candidate" if shapes or len(fitted["hypotheses"]) == 1
                        else "unknown"
                    )
                    result.update(fitted)
                result["source_slice_status"] = slice_meta["status"]
                results.append(result)
    summary: dict[str, int] = {}
    shape_summary: dict[str, int] = {}
    for item in results:
        summary[item["status"]] = summary.get(item["status"], 0) + 1
        shape_status = item.get("shape_status", "unknown")
        shape_summary[shape_status] = shape_summary.get(shape_status, 0) + 1
    output = {"schema": "scan.column-section-fit-review/1", "source_review_report": str(report_path),
        "source_report_sha256": sha256(report_path), "algorithm_tolerance_m": args.tolerance_m,
        "known_sides_m": args.known_sides_m, "min_points": args.min_points,
        "engineering_status": "not_assessed", "catalog_assignment": "none",
        "source_geometry_modified": False,
        "notes": "Per-slice hypotheses only. NPZ data includes nearby context; proposals require human review and are not physical truth.",
        "summary": summary, "shape_summary": shape_summary, "slices": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(args.out), "summary": summary, "shape_summary": shape_summary,
                      "engineering_status": output["engineering_status"], "source_geometry_modified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
