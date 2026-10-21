"""Prepare independent labels and evaluate grouping from a local JSON snapshot."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from scan2bim.structure.column_type_evaluation import create_annotation_template, evaluate_annotation_sweep
from scan2bim.structure.column_annotations import column_snapshot_sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["template", "evaluate"])
    parser.add_argument("--source", type=Path, required=True, help="Local BIM JSON with stable per-instance IDs")
    parser.add_argument("--out", type=Path, required=True, help="New JSON file; existing files are never overwritten")
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--dataset-id", default="pilot-A-columns")
    parser.add_argument("--linear-mm", type=float, nargs="+", default=[2, 5, 10])
    parser.add_argument("--relative", type=float, nargs="+", default=[0.005, 0.01])
    args = parser.parse_args()
    if (args.source.suffix.lower() != ".json" or args.out.suffix.lower() != ".json"
        or (args.annotations is not None and args.annotations.suffix.lower() != ".json")):
        parser.error("only JSON snapshots/reports are supported; source scans are never opened")
    if args.out.exists():
        parser.error("output already exists; choose a new filename to preserve review history")
    raw = args.source.read_bytes()
    snapshot = json.loads(raw.decode("utf-8-sig"))
    elements = snapshot.get("elements") if isinstance(snapshot, dict) else snapshot
    if not isinstance(elements, list) or not elements:
        parser.error("source must contain elements with stable IDs; export BIM JSON first")
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"] for item in elements):
        parser.error("each source element requires a stable non-empty ID")
    source_artifact_sha256 = sha256(raw).hexdigest()
    digest = source_artifact_sha256
    try:
        if args.mode == "template":
            report = create_annotation_template(elements, digest, args.dataset_id)
        else:
            if args.annotations is None:
                parser.error("evaluate requires --annotations")
            annotation_bytes = args.annotations.read_bytes()
            document = json.loads(annotation_bytes.decode("utf-8-sig"))
            manifest = document.get("source_cloud_manifest")
            if manifest is not None:
                source_metadata = snapshot.get("source") if isinstance(snapshot, dict) else None
                source_manifest = source_metadata.get("snapshot_manifest") if isinstance(source_metadata, dict) else None
                if source_manifest != manifest:
                    raise ValueError("source cloud manifest differs from the annotation snapshot")
                digest = column_snapshot_sha256(elements, source_manifest)
            report = evaluate_annotation_sweep(elements, document, digest,
                linear_tolerances_m=[mm / 1000 for mm in args.linear_mm], relative_tolerances=args.relative)
            report["annotation_sha256"] = sha256(annotation_bytes).hexdigest()
            report["source_artifact_sha256"] = source_artifact_sha256
    except ValueError as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    if args.mode == "template":
        summary = {"pending_columns": len(report["annotations"]), "source_snapshot_sha256": digest}
    else:
        summary = {"runs": [{key: run[key] for key in ("linear_tolerance_m", "relative_tolerance",
            "proposal_count", "evaluation_status", "reference_counts", "pairwise")} for run in report["runs"]]}
    print(json.dumps({"out": str(args.out), **summary}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
