import numpy as np
import json
import pytest
from scan2bim.registration.stitching import (
    rigid_icp,
    kabsch_fit,
    create_recap_registration_project,
    merge_and_save_unified_cloud,
    validate_full_resolution_station,
    validate_unified_cloud_cache,
    write_centered_unified_positions,
)


def test_kabsch_fit_exact():
    # Known translation and 90 deg rotation around Z
    pts = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [2.0, 3.0, 1.0],
    ])
    r_true = np.array([
        [0.0, -1.0, 0.0],
        [1.0,  0.0, 0.0],
        [0.0,  0.0, 1.0],
    ])
    t_true = np.array([5.0, -2.0, 3.0])

    target = (r_true @ pts.T).T + t_true

    r_est, t_est = kabsch_fit(pts, target)
    np.testing.assert_allclose(r_est, r_true, atol=1e-6)
    np.testing.assert_allclose(t_est, t_true, atol=1e-6)


def test_rigid_icp_convergence(tmp_path):
    np.random.seed(42)
    base_cloud = np.random.uniform(-10, 10, size=(1000, 3))

    # Small displacement
    theta = np.deg2rad(2.0)
    r_true = np.array([
        [np.cos(theta), -np.sin(theta), 0.0],
        [np.sin(theta),  np.cos(theta), 0.0],
        [0.0,            0.0,           1.0],
    ])
    t_true = np.array([0.05, -0.03, 0.02])

    source_cloud = (r_true @ base_cloud.T).T + t_true

    result = rigid_icp(source_cloud, base_cloud, max_iterations=30, tolerance_m=1e-5)
    assert result["converged"] is True
    assert result["iterations"] > 1  # a real convergence check cannot stop on the first update
    assert result["rmse_mm"] < 5.0  # sub-5mm precision

    # Test ReCap manifest creation
    stations = [
        {"id": "station_01", "path": "scan1.e57", "point_count": 1000, "matrix_4x4": np.eye(4).tolist()},
        {"id": "station_02", "path": "scan2.e57", "point_count": 1000, "matrix_4x4": result["matrix_4x4"], "rmse_mm": result["rmse_mm"]},
    ]
    manifest_path = tmp_path / "recap_project.json"
    create_recap_registration_project(stations, "Цех 1.rcs", manifest_path)
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == "SCAN station-registration manifest"
    assert manifest["recap_project_generated"] is False
    assert manifest["registration_verified"] is False


def test_rigid_icp_reports_missing_residual_when_no_correspondences():
    source = np.tile(np.array([[-10.0, 0.0, 0.0], [10.0, 0.0, 0.0]]), (10, 1))
    target = np.tile(np.array([[0.0, -10.0, 0.0], [0.0, 10.0, 0.0]]), (10, 1))

    result = rigid_icp(source, target, max_iterations=10)

    assert result["converged"] is False
    assert result["rmse_mm"] is None


def test_rigid_icp_uses_reproducible_unique_sample_indices():
    rng = np.random.default_rng(112)
    target = rng.uniform(-4.0, 4.0, size=(1200, 3))
    source = target + np.array([0.025, -0.01, 0.015])

    first = rigid_icp(source, target, sample_size=256, random_seed=91)
    second = rigid_icp(source, target, sample_size=256, random_seed=91)

    assert first["source_sample_indices"] == second["source_sample_indices"]
    assert first["target_sample_indices"] == second["target_sample_indices"]
    assert len(first["source_sample_indices"]) == 256
    assert len(set(first["source_sample_indices"])) == 256
    assert len(first["target_sample_indices"]) == 512
    assert len(set(first["target_sample_indices"])) == 512
    assert first["matrix_4x4"] == second["matrix_4x4"]
    assert first["rmse_mm"] == second["rmse_mm"]


def test_full_resolution_station_gate_accepts_complete_matching_source():
    validate_full_resolution_station(
        "station_01", 1000, 1000, complete=True, decimated=False,
    )


@pytest.mark.parametrize(
    ("source_count", "stored_count", "complete", "decimated", "error"),
    [
        (1000, 1000, False, False, "stream is incomplete"),
        (1000, 1000, True, True, "source is decimated"),
        (1000, 800, True, False, "source has 1000 points, but only 800 are stored"),
        (None, 1000, True, False, "source point count is missing"),
    ],
)
def test_full_resolution_station_gate_rejects_incomplete_or_decimated_sources(
    source_count, stored_count, complete, decimated, error,
):
    with pytest.raises(ValueError, match=error):
        validate_full_resolution_station(
            "station_02", source_count, stored_count,
            complete=complete, decimated=decimated,
        )


def test_unified_cloud_cache_requires_matching_count_hash_inputs_and_transform():
    station_inputs = {
        "station_01": {"stored_positions_sha256": "source-1", "stored_point_count": 10,
                       "unified_row_start": 0, "unified_row_end_exclusive": 10},
        "station_02": {"source_sha256": "source-2", "stored_point_count": 20,
                       "unified_row_start": 10, "unified_row_end_exclusive": 30},
    }
    matrix = np.eye(4)
    row_ranges = [
        {"station_id": "station_01", "source_row_start": 0, "source_row_end_exclusive": 10,
         "source_row_count": 10, "source_row_index_base": 0},
        {"station_id": "station_02", "source_row_start": 10, "source_row_end_exclusive": 30,
         "source_row_count": 20, "source_row_index_base": 0},
    ]
    meta = {
        "source_point_count": 30,
        "stored_point_count": 30,
        "checksum_sha256": "cache-sha",
        "unified_merge": True,
        "station_input_fingerprints": station_inputs,
        "station_row_ranges": row_ranges,
        "registration_matrix_station_02": matrix.tolist(),
    }

    validate_unified_cloud_cache(
        meta,
        expected_point_count=30,
        actual_point_count=30,
        expected_station_inputs=station_inputs,
        expected_registration_matrix=matrix,
        actual_file_sha256="cache-sha",
    )


@pytest.mark.parametrize(
    ("meta_patch", "actual_count", "file_hash", "station_inputs", "matrix", "error"),
    [
        ({}, 29, "cache-sha", None, None, "point count"),
        ({}, 30, "different-hash", None, None, "checksum"),
        ({"station_input_fingerprints": {}}, 30, "cache-sha", None, None, "station inputs"),
        ({"registration_matrix_station_02": np.zeros((4, 4)).tolist()}, 30, "cache-sha", None, None, "registration matrix"),
        ({"station_row_ranges": [{"station_id": "station_01"}]}, 30, "cache-sha", None, None, "source-row ranges"),
        ({"unified_merge": False}, 30, "cache-sha", None, None, "not marked as a unified merge"),
    ],
)
def test_unified_cloud_cache_rejects_stale_or_incomplete_metadata(
    meta_patch, actual_count, file_hash, station_inputs, matrix, error,
):
    expected_inputs = {
        "station_01": {"stored_positions_sha256": "source-1", "stored_point_count": 10,
                       "unified_row_start": 0, "unified_row_end_exclusive": 10},
        "station_02": {"source_sha256": "source-2", "stored_point_count": 20,
                       "unified_row_start": 10, "unified_row_end_exclusive": 30},
    }
    expected_matrix = np.eye(4)
    expected_ranges = [
        {"station_id": "station_01", "source_row_start": 0, "source_row_end_exclusive": 10,
         "source_row_count": 10, "source_row_index_base": 0},
        {"station_id": "station_02", "source_row_start": 10, "source_row_end_exclusive": 30,
         "source_row_count": 20, "source_row_index_base": 0},
    ]
    meta = {
        "source_point_count": 30,
        "stored_point_count": 30,
        "checksum_sha256": "cache-sha",
        "unified_merge": True,
        "station_input_fingerprints": expected_inputs,
        "station_row_ranges": expected_ranges,
        "registration_matrix_station_02": expected_matrix.tolist(),
        **meta_patch,
    }
    with pytest.raises(ValueError, match=error):
        validate_unified_cloud_cache(
            meta,
            expected_point_count=30,
            actual_point_count=actual_count,
            expected_station_inputs=station_inputs or expected_inputs,
            expected_registration_matrix=matrix if matrix is not None else expected_matrix,
            actual_file_sha256=file_hash,
        )


def test_merge_and_save_unified_cloud(tmp_path):
    pts1 = np.array([[10.0, 20.0, 1.0], [12.0, 22.0, 2.0]], dtype=np.float32)
    pts2 = np.array([[30.0, 40.0, 3.0], [32.0, 42.0, 4.0]], dtype=np.float32)

    stations = [
        {"name": "Scan_1", "points": pts1, "matrix_4x4": np.eye(4).tolist()},
        {"name": "Scan_2", "points": pts2, "matrix_4x4": np.eye(4).tolist()},
    ]

    out_dir = tmp_path / "unified_test"
    res = merge_and_save_unified_cloud(stations, out_dir, project_title="Test Merged Cloud", export_ply=True)

    assert res["status"] == "success"
    assert res["total_points"] == 4
    assert (out_dir / "positions.npy").exists()
    assert (out_dir / "meta.json").exists()
    assert (out_dir / "registration_manifest.json").exists()
    assert (out_dir / "unified_cloud.ply").exists()

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["stored_point_count"] == 4
    assert meta["unified_merge"] is True
    assert [(row["source_row_start"], row["source_row_end_exclusive"]) for row in meta["station_row_ranges"]] == [(0, 2), (2, 4)]
    manifest = json.loads((out_dir / "registration_manifest.json").read_text(encoding="utf-8"))
    assert manifest["stations"][1]["source_row_start"] == 2
    assert manifest["stations"][1]["source_row_end_exclusive"] == 4

    # Check bounds consistency for pipeline _load_geometry
    positions = np.load(out_dir / "positions.npy")
    origin = np.array(meta["origin"])
    bbox_min = np.array(meta["bbox_min"])
    bbox_max = np.array(meta["bbox_max"])
    np.testing.assert_allclose(bbox_min - origin, positions.min(axis=0), atol=1e-3)
    np.testing.assert_allclose(bbox_max - origin, positions.max(axis=0), atol=1e-3)


def test_centered_merge_preserves_millimeter_offsets_at_large_world_coordinates(tmp_path):
    world_offset = np.array([1.0e8, -2.0e8, 3.0e8], dtype=np.float64)
    points1 = np.array([
        [0.000, 0.000, 0.000],
        [0.006, 0.012, 0.018],
    ], dtype=np.float64)
    points2 = np.array([
        [0.024, 0.006, 0.012],
        [0.030, 0.018, 0.000],
    ], dtype=np.float64)
    out_path = tmp_path / "centered.npy"

    result = write_centered_unified_positions(
        [
            {"points": points1, "origin": world_offset},
            {"points": points2, "origin": world_offset},
        ],
        out_path,
        chunk_size=1,
    )

    expected_world = np.vstack((points1, points2)) + world_offset
    expected_origin = expected_world.min(axis=0) / 2 + expected_world.max(axis=0) / 2
    expected_local = expected_world - expected_origin
    actual_local = np.load(out_path)
    np.testing.assert_allclose(result["origin"], expected_origin, atol=1e-8)
    np.testing.assert_allclose(actual_local, expected_local, atol=2e-8)
    assert np.unique(actual_local, axis=0).shape[0] == len(expected_local)
    assert [(row["source_row_start"], row["source_row_end_exclusive"]) for row in result["station_row_ranges"]] == [(0, 2), (2, 4)]

    merged = merge_and_save_unified_cloud(
        [
            {"id": "station_01", "points": points1, "origin": world_offset},
            {"id": "station_02", "points": points2, "origin": world_offset},
        ],
        tmp_path / "merge_api",
    )
    saved_local = np.load(merged["positions_file"])
    np.testing.assert_allclose(merged["origin"], expected_origin, atol=1e-8)
    np.testing.assert_allclose(saved_local, expected_local, atol=2e-8)


def test_station_row_mapping_rejects_duplicate_station_ids(tmp_path):
    points = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
    stations = [
        {"id": "duplicate", "points": points},
        {"id": "duplicate", "points": points},
    ]

    with pytest.raises(ValueError, match="unique for source-row mapping"):
        write_centered_unified_positions(stations, tmp_path / "ambiguous.npy")

    with pytest.raises(ValueError, match="unique for source-row mapping"):
        merge_and_save_unified_cloud(stations, tmp_path / "ambiguous_merge")

    with pytest.raises(ValueError, match="unique in a registration manifest"):
        create_recap_registration_project(stations, "Ambiguous", tmp_path / "ambiguous.json")
