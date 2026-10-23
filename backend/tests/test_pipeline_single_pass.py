import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scan2bim import pipeline_single_pass as pipeline
from scan2bim.pointdata.octree import PreviewLodBuilder


def test_pipeline_keeps_recognition_results_as_unreviewed_and_never_claims_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    positions = np.array([
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 2.0], [1.0, 1.0, 2.0],
    ], dtype=np.float32)
    source = tmp_path / "positions.npy"
    np.save(source, positions)
    (tmp_path / "meta.json").write_text(json.dumps({
        "origin": [100.0, 200.0, 10.0],
        "bbox_min": [100.0, 200.0, 10.0],
        "bbox_max": [101.0, 201.0, 12.0],
        "checksum_sha256": "source-checksum",
        "station_count": 2,
        "station_row_ranges": [
            {"station_id": "station-1", "source_row_start": 0, "source_row_end_exclusive": 2,
             "source_row_count": 2, "source_row_index_base": 0},
            {"station_id": "station-2", "source_row_start": 2, "source_row_end_exclusive": 4,
             "source_row_count": 2, "source_row_index_base": 0},
        ],
    }), encoding="utf-8")
    detected = SimpleNamespace(
        class_name="column",
        geometry={"center": [100.5, 200.5, 11.0], "sizes": {"height": 2.0}},
        bbox={"min": [100.4, 200.4, 10.0], "max": [100.6, 200.6, 12.0]},
        confidence=0.4,
        measured=True,
        inferred=False,
        source="geometric",
        dimensions={"role": "column_candidate"},
        metadata={"source_point_ids": [1, 2, 3]},
    )
    captured: dict = {}
    monkeypatch.setattr(
        pipeline, "detect_structures",
        lambda geometry, _progress=None: (
            captured.setdefault("origin", geometry.origin.tolist())
            and SimpleNamespace(elements=[detected], stats={"points_processed": 4}, warnings=[])
        ),
    )

    def write_draft(elements, output_dir, project_title, source_frame, source_provenance):
        captured["elements"] = elements
        captured["project_title"] = project_title
        captured["source_frame"] = source_frame
        captured["source_provenance"] = source_provenance
        return {"manifest_path": str(Path(output_dir) / "manifest.json"), "sheets": [{"issue": "draft"}]}

    monkeypatch.setattr(pipeline, "generate_full_spds_album", write_draft)
    output = tmp_path / "release"
    report = pipeline.WorkshopPipeline(output).execute_pipeline(source, project_title="Цех")

    assert captured["origin"] == [100.0, 200.0, 10.0]
    assert captured["source_frame"] == "source_cloud_world"
    assert captured["source_provenance"]["station_row_ranges"][1] == {
        "station_id": "station-2", "source_row_start": 2,
        "source_row_end_exclusive": 4, "source_row_count": 2,
        "source_row_index_base": 0,
    }
    assert "positions_path" not in captured["source_provenance"]
    assert captured["elements"][0]["class_name"] == "column"
    assert captured["elements"][0]["review_status"] == "unreviewed"
    assert report["status"] == "completed_with_review_candidates"
    assert report["release_ready"] is False
    assert report["candidate_counts_by_class"] == {"column": 1}
    assert report["ifc_export"] == "not_generated"
    assert "not_generated" in report["native_recap_project"]
    assert report["source"]["source_sha256"] == "source-checksum"
    assert json.loads((output / "candidates.json").read_text(encoding="utf-8"))[0]["review_status"] == "unreviewed"


def test_preview_lod_manifest_does_not_claim_octree_or_native_recap(tmp_path: Path):
    source = tmp_path / "positions.npy"
    points = np.arange(90, dtype=np.float32).reshape(30, 3)
    np.save(source, points)

    manifest = PreviewLodBuilder(overview_limit=5, medium_limit=10).build_lod_pyramid(
        source, tmp_path / "preview",
    )

    assert manifest["spatial_octree"] is False
    assert manifest["native_recap_package"] is False
    assert manifest["sampling_method"] == "evenly spaced source row indices; not spatially uniform"
    assert manifest["levels"][0]["points_count"] == 5
    assert np.load(tmp_path / "preview" / "overview.npy").tolist() == points[[0, 7, 14, 21, 29]].tolist()


def test_pipeline_rejects_metadata_bounds_that_do_not_match_positions(tmp_path: Path):
    source = tmp_path / "positions.npy"
    np.save(source, np.zeros((3, 3), dtype=np.float32))
    (tmp_path / "meta.json").write_text(json.dumps({
        "origin": [0.0, 0.0, 0.0],
        "bbox_min": [-1.0, 0.0, 0.0],
        "bbox_max": [0.0, 0.0, 0.0],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="bounds do not match"):
        pipeline._load_geometry(source)


def test_pipeline_rejects_gapped_or_partial_station_row_ranges(tmp_path: Path):
    source = tmp_path / "positions.npy"
    np.save(source, np.zeros((4, 3), dtype=np.float32))
    (tmp_path / "meta.json").write_text(json.dumps({
        "origin": [0.0, 0.0, 0.0],
        "bbox_min": [0.0, 0.0, 0.0],
        "bbox_max": [0.0, 0.0, 0.0],
        "station_count": 2,
        "station_row_ranges": [
            {"station_id": "station-1", "source_row_start": 0, "source_row_end_exclusive": 2,
             "source_row_count": 2, "source_row_index_base": 0},
            {"station_id": "station-2", "source_row_start": 3, "source_row_end_exclusive": 4,
             "source_row_count": 1, "source_row_index_base": 0},
        ],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="contiguous, zero-based"):
        pipeline._load_geometry(source)
