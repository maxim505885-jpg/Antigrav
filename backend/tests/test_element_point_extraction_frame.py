from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scan2bim.learning import store


@pytest.fixture
def point_cloud(tmp_path: Path, monkeypatch):
    positions = np.array(
        [[0.0, 0.0, 0.0], [0.55, 0.0, 1.0], [0.75, 0.0, 1.0], [2.0, 2.0, 2.0]],
        dtype=np.float32,
    )
    path = tmp_path / "positions.npy"
    np.save(path, positions)
    origin = np.array([10.0, 20.0, 30.0])
    monkeypatch.setattr(store, "_cloud", lambda cloud_id: {
        "id": cloud_id,
        "project_id": "pilot",
        "origin_x": origin[0],
        "origin_y": origin[1],
        "origin_z": origin[2],
    })
    monkeypatch.setattr(store, "cloud_paths", lambda project_id, cloud_id: {"positions": path})
    return positions, origin


def test_legacy_recognition_candidates_use_cloud_local_bbox_coordinates():
    assert store.element_bbox_coordinate_frame({"source": "geometric", "metadata": {}}) == "cloud_local"
    assert store.element_bbox_coordinate_frame({"source": "structural_grid", "metadata": {}}) == "cloud_local"


def test_explicit_world_frame_is_preserved_for_new_recognition_candidates():
    element = {
        "source": "geometric",
        "metadata": {"bbox_coordinate_frame": "source_cloud_world"},
    }
    assert store.element_bbox_coordinate_frame(element) == "source_cloud_world"


def test_pipeline_candidates_persist_world_bbox_coordinate_frame():
    from scan2bim.pipeline_single_pass import _candidate_record
    from scan2bim.recognition.geometric import DetectedElement

    candidate = DetectedElement(
        class_name="column",
        geometry={"kind": "member"},
        bbox={"min": [100, 200, 0], "max": [100, 200, 5]},
        confidence=0.7,
    )

    record = _candidate_record(candidate)

    assert record["metadata"]["bbox_coordinate_frame"] == "source_cloud_world"


def test_local_bbox_extracts_points_and_returns_world_coordinates(point_cloud):
    _, origin = point_cloud
    points = store.extract_element_points(
        "cloud", {"min": [0, 0, 0], "max": [0, 0, 0]}, coordinate_frame="cloud_local"
    )
    np.testing.assert_allclose(points, [origin])


def test_world_bbox_extracts_the_same_local_source_points(point_cloud):
    _, origin = point_cloud
    points = store.extract_element_points(
        "cloud", {"min": origin.tolist(), "max": origin.tolist()}, coordinate_frame="source_cloud_world"
    )
    np.testing.assert_allclose(points, [origin])


def test_axis_context_expands_only_degenerate_dimensions_for_inspection(point_cloud):
    _, origin = point_cloud
    points = store.extract_element_points(
        "cloud",
        {"min": [0, 0, 0], "max": [0, 0, 2]},
        coordinate_frame="cloud_local",
        degenerate_context_half_extent_m=0.6,
    )
    np.testing.assert_allclose(points, [origin, origin + [0.55, 0, 1]])


def test_member_axis_context_does_not_expand_measured_narrow_dimensions(point_cloud):
    _, origin = point_cloud
    points = store.extract_element_points(
        "cloud",
        {"min": [0, -0.1, 0], "max": [0, 0.1, 2]},
        coordinate_frame="cloud_local",
        degenerate_context_half_extent_m=0.6,
    )
    np.testing.assert_allclose(points, [origin, origin + [0.55, 0, 1]])


def test_invalid_coordinate_frame_is_rejected(point_cloud):
    with pytest.raises(ValueError, match="coordinate frame"):
        store.extract_element_points(
            "cloud", {"min": [0, 0, 0], "max": [0, 0, 0]}, coordinate_frame="unknown"
        )


def test_source_point_ids_are_consistent_when_rows_land_inside_current_bbox(point_cloud):
    positions, origin = point_cloud
    path = store.cloud_paths("pilot", "cloud")["positions"]
    snapshot = store.point_cloud_snapshot("cloud", path, len(positions), origin)
    evidence = store.inspect_source_point_alignment(
        "cloud",
        {
            "source": "geometric",
            "metadata": {
                "source_point_ids": [0, 1],
                "source_point_id_space": "positions.npy row index",
                "source_point_ids_sampled": False,
                "source_cloud_snapshot": snapshot,
            },
            "bbox": {"min": [0, 0, 0], "max": [0.55, 0, 1]},
        },
        coordinate_frame="cloud_local",
    )
    assert evidence == {
        "status": "consistent",
        "row_ids_count": 2,
        "row_ids_checked_count": 2,
        "row_ids_valid_count": 2,
        "row_ids_within_bbox_count": 2,
        "row_ids_within_geometry_count": 2,
        "geometry_check": "bbox",
        "row_ids_sampled": False,
        "snapshot_matches": True,
    }


def test_member_source_rows_are_checked_against_axis_not_zero_thickness_bbox(point_cloud):
    positions, origin = point_cloud
    path = store.cloud_paths("pilot", "cloud")["positions"]
    snapshot = store.point_cloud_snapshot("cloud", path, len(positions), origin)
    evidence = store.inspect_source_point_alignment(
        "cloud",
        {
            "geometry": {
                "kind": "member",
                "p0": origin.tolist(),
                "p1": (origin + [0.55, 0.0, 1.0]).tolist(),
            },
            "metadata": {
                "source_point_ids": [0, 2],
                "source_point_id_space": "positions.npy row index",
                "source_cloud_snapshot": snapshot,
            },
            "bbox": {"min": origin.tolist(), "max": (origin + [0.55, 0.0, 1.0]).tolist()},
        },
        coordinate_frame="source_cloud_world",
    )

    assert evidence["status"] == "consistent"
    assert evidence["geometry_check"] == "member_axis"
    assert evidence["row_ids_within_bbox_count"] == 1
    assert evidence["row_ids_within_geometry_count"] == 2


def test_member_source_rows_allow_section_slice_offset_within_provenance_corridor(point_cloud):
    positions, origin = point_cloud
    path = store.cloud_paths("pilot", "cloud")["positions"]
    positions = positions.copy()
    positions[2] = [0.275, 0.53, 0.5]
    np.save(path, positions)
    snapshot = store.point_cloud_snapshot("cloud", path, len(positions), origin)

    evidence = store.inspect_source_point_alignment(
        "cloud",
        {
            "geometry": {
                "kind": "member",
                "p0": origin.tolist(),
                "p1": (origin + [0.55, 0.0, 1.0]).tolist(),
            },
            "metadata": {
                "source_point_ids": [2],
                "source_point_id_space": "positions.npy row index",
                "source_cloud_snapshot": snapshot,
            },
            "bbox": {"min": origin.tolist(), "max": (origin + [0.55, 0.0, 1.0]).tolist()},
        },
        coordinate_frame="source_cloud_world",
    )

    assert evidence["status"] == "consistent"
    assert evidence["geometry_check"] == "member_axis"
    assert evidence["row_ids_within_bbox_count"] == 0
    assert evidence["row_ids_within_geometry_count"] == 1


def test_member_source_row_far_from_axis_is_a_mismatch(point_cloud):
    positions, origin = point_cloud
    path = store.cloud_paths("pilot", "cloud")["positions"]
    snapshot = store.point_cloud_snapshot("cloud", path, len(positions), origin)
    evidence = store.inspect_source_point_alignment(
        "cloud",
        {
            "geometry": {
                "kind": "member",
                "p0": origin.tolist(),
                "p1": (origin + [0.55, 0.0, 1.0]).tolist(),
            },
            "metadata": {
                "source_point_ids": [3],
                "source_point_id_space": "positions.npy row index",
                "source_cloud_snapshot": snapshot,
            },
            "bbox": {"min": origin.tolist(), "max": (origin + [0.55, 0.0, 1.0]).tolist()},
        },
        coordinate_frame="source_cloud_world",
    )

    assert evidence["status"] == "mismatch"
    assert evidence["geometry_check"] == "member_axis"
    assert evidence["row_ids_within_geometry_count"] == 0


def test_aligned_legacy_rows_without_a_cloud_snapshot_are_not_verified(point_cloud):
    evidence = store.inspect_source_point_alignment(
        "cloud",
        {
            "source": "geometric",
            "metadata": {
                "source_point_ids": [0, 1],
                "source_point_id_space": "positions.npy row index",
                "source_point_ids_sampled": False,
            },
            "bbox": {"min": [0, 0, 0], "max": [0.55, 0, 1]},
        },
        coordinate_frame="cloud_local",
    )

    assert evidence["status"] == "unverifiable"
    assert evidence["reason"] == "missing_source_cloud_snapshot"
    assert evidence["row_ids_within_bbox_count"] == 2


def test_source_point_ids_are_flagged_when_rows_do_not_match_current_bbox(point_cloud):
    evidence = store.inspect_source_point_alignment(
        "cloud",
        {
            "source": "geometric",
            "metadata": {
                "source_point_ids": [3],
                "source_point_id_space": "positions.npy row index",
                "source_point_ids_sampled": False,
            },
            "bbox": {"min": [0, 0, 0], "max": [0, 0, 0]},
        },
        coordinate_frame="cloud_local",
    )
    assert evidence["status"] == "mismatch"
    assert evidence["row_ids_count"] == 1
    assert evidence["row_ids_valid_count"] == 1
    assert evidence["row_ids_within_bbox_count"] == 0


def test_source_row_evidence_rejects_ids_from_another_cloud_snapshot(point_cloud):
    positions, origin = point_cloud
    path = store.cloud_paths("pilot", "cloud")["positions"]
    snapshot = store.point_cloud_snapshot("cloud", path, len(positions), origin)
    element = {
        "source": "geometric",
        "metadata": {
            "source_point_ids": [0, 1],
            "source_point_id_space": "positions.npy row index",
            "source_cloud_snapshot": snapshot,
        },
        "bbox": {"min": [0, 0, 0], "max": [0.55, 0, 1]},
    }

    np.save(path, positions + np.array([0.01, 0.0, 0.0], dtype=np.float32))

    evidence = store.inspect_source_point_alignment("cloud", element, "cloud_local")

    assert evidence["status"] == "mismatch"
    assert evidence["snapshot_matches"] is False


def test_non_integer_source_rows_are_not_silently_dropped_from_alignment_check(point_cloud):
    evidence = store.inspect_source_point_alignment(
        "cloud",
        {
            "source": "geometric",
            "metadata": {
                "source_point_ids": [0, 0.5],
                "source_point_id_space": "positions.npy row index",
            },
            "bbox": {"min": [0, 0, 0], "max": [0, 0, 0]},
        },
        coordinate_frame="cloud_local",
    )
    assert evidence["status"] == "mismatch"
    assert evidence["row_ids_checked_count"] == 2
    assert evidence["row_ids_valid_count"] == 1


def test_source_point_alignment_is_unverifiable_without_declared_index_space():
    evidence = store.inspect_source_point_alignment(
        "cloud",
        {"metadata": {"source_point_ids": [2]}, "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]}},
        coordinate_frame="cloud_local",
    )
    assert evidence["status"] == "unverifiable"


def test_element_points_api_uses_legacy_local_frame_and_member_context(point_cloud, client, monkeypatch):
    import importlib

    api_module = importlib.import_module("scan2bim.api.app")
    monkeypatch.setattr(api_module, "get_element", lambda _element_id: {
        "id": "legacy-axis",
        "cloud_id": "cloud",
        "source": "structural_grid",
        "metadata": {},
        "geometry": {"kind": "member"},
        "bbox": {"min": [0, 0, 0], "max": [0, 0, 2]},
    })

    response = client.get("/api/v1/elements/legacy-axis/points")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    np.testing.assert_allclose(body["points"], [[10, 20, 30], [10.55, 20, 31]])
    assert body["bbox_coordinate_frame"] == "cloud_local"
    assert body["source_point_evidence"]["status"] == "unverifiable"


def test_element_points_api_reports_source_row_mismatch(point_cloud, client, monkeypatch):
    import importlib

    api_module = importlib.import_module("scan2bim.api.app")
    monkeypatch.setattr(api_module, "get_element", lambda _element_id: {
        "id": "stale-beam",
        "cloud_id": "cloud",
        "source": "geometric",
        "metadata": {
            "source_point_ids": [3],
            "source_point_id_space": "positions.npy row index",
        },
        "geometry": {"kind": "oriented_box"},
        "bbox": {"min": [0, 0, 0], "max": [0, 0, 0]},
    })

    response = client.get("/api/v1/elements/stale-beam/points")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    assert body["source_point_evidence"]["status"] == "mismatch"
    assert body["source_point_evidence"]["row_ids_within_bbox_count"] == 0
