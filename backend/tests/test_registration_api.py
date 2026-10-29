import pytest
from pathlib import Path
import numpy as np

from scan2bim.db import execute, new_id, utcnow
from scan2bim.api import registration as registration_api
from scan2bim.storage import cloud_paths


def test_global_registration_partition_is_disjoint_and_handles_small_clouds():
    source = np.column_stack((np.arange(200), np.zeros((200, 2))))
    target = source + np.array([10.0, 0.0, 0.0])
    fit_source, fit_target, eval_source, eval_target = (
        registration_api._partition_global_registration_samples(
            source, target, 100, sample_seed=17
        )
    )

    assert len(fit_source) == len(fit_target) == 100
    assert len(eval_source) == len(eval_target) == 100
    assert set(fit_source[:, 0]).isdisjoint(set(eval_source[:, 0]))
    assert set(fit_target[:, 0]).isdisjoint(set(eval_target[:, 0]))
    np.testing.assert_array_equal(
        np.sort(np.concatenate((fit_source[:, 0], eval_source[:, 0]))),
        np.arange(200),
    )

    small_source, small_target = source[:199], target[:199]
    fit_source, fit_target, eval_source, eval_target = (
        registration_api._partition_global_registration_samples(
            small_source, small_target, 100, sample_seed=17
        )
    )
    assert len(fit_source) == len(fit_target) == 199
    assert eval_source is None and eval_target is None


def test_registration_flow_success(client):
    project = client.post("/api/v1/projects", json={"name": "Registration test"}).json()
    project_id = project["id"]
    
    # Cloud 1
    c1_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, origin_x, origin_y, origin_z, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (c1_id, project_id, "Cloud 1", "c1.ply", "ply", 1000, "ready", 10.0, 20.0, 30.0, now, now)
    )
    p1 = cloud_paths(project_id, c1_id)
    p1["positions"].parent.mkdir(parents=True, exist_ok=True)
    pts1 = np.random.normal(0, 5, size=(100, 3)).astype(np.float64)
    np.save(p1["positions"], pts1)

    # Cloud 2 (shifted Cloud 1)
    c2_id = new_id()
    execute(
        """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, origin_x, origin_y, origin_z, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (c2_id, project_id, "Cloud 2", "c2.ply", "ply", 1000, "ready", 100.0, 200.0, 300.0, now, now)
    )
    p2 = cloud_paths(project_id, c2_id)
    p2["positions"].parent.mkdir(parents=True, exist_ok=True)
    pts2 = pts1 + np.array([1.0, 0.5, -0.2])
    np.save(p2["positions"], pts2)

    # Match via ICP
    res = client.post("/api/v1/registration/match", json={
        "source_cloud_id": c1_id,
        "target_cloud_id": c2_id,
        "sample_points": 100,
        "max_iterations": 20
    })
    assert res.status_code == 200
    data = res.json()
    assert "matrix_4x4" in data
    assert data["world_matrix_4x4"] is not None
    assert data["coordinate_frame"]["world_matrix_4x4"] == "source_world_to_target_world"
    assert "rmse_mm" in data
    assert data["rmse_mm"] >= 0
    assert data["source_sample_count"] == 100
    assert data["target_sample_count"] == 100
    assert 0 <= data["inlier_count"] <= data["source_sample_count"]
    assert data["inlier_fraction"] == pytest.approx(data["inlier_count"] / 100)
    assert len(data["source_sample_row_ids"]) == len(set(data["source_sample_row_ids"])) == 100
    assert len(data["target_sample_row_ids"]) == len(set(data["target_sample_row_ids"])) == 100
    assert set(data["source_sample_row_ids"]) == set(range(100))
    assert set(data["target_sample_row_ids"]) == set(range(100))

    sampled = client.post("/api/v1/registration/match", json={
        "source_cloud_id": c1_id,
        "target_cloud_id": c2_id,
        "sample_points": 20,
        "max_iterations": 20,
        "random_seed": 91,
    })
    assert sampled.status_code == 200
    sampled_data = sampled.json()
    expected_rows = np.linspace(0, 99, 20, dtype=np.int64).tolist()
    assert sampled_data["source_sample_row_ids"] == expected_rows
    assert sampled_data["target_sample_row_ids"] == expected_rows

    # Export PLY and ReCap
    stations = [
        {"points": pts1.tolist(), "matrix_4x4": np.eye(4).tolist()},
        {"points": pts2.tolist(), "matrix_4x4": data["matrix_4x4"]}
    ]
    res_ply = client.post("/api/v1/registration/export-ply", json={
        "project_name": "test_unified",
        "stations": stations
    })
    assert res_ply.status_code == 200
    assert Path(res_ply.json()["output_path"]).exists()

    res_rc = client.post("/api/v1/registration/export-recap", json={
        "project_name": "test_unified",
        "stations": stations
    })
    assert res_rc.status_code == 200
    assert Path(res_rc.json()["output_path"]).exists()


def test_global_match_endpoint_returns_read_only_candidate(client, monkeypatch):
    project = client.post("/api/v1/projects", json={"name": "Global registration test"}).json()
    project_id = project["id"]
    cloud_ids = [new_id(), new_id()]
    now = utcnow()
    for index, cloud_id in enumerate(cloud_ids):
        execute(
            """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status,
               origin_x, origin_y, origin_z, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cloud_id, project_id, f"Station {index}", f"station-{index}.ply", "ply", 1000,
             "ready", float(index * 10), 0.0, 0.0, now, now),
        )
        positions = cloud_paths(project_id, cloud_id)["positions"]
        positions.parent.mkdir(parents=True, exist_ok=True)
        np.save(positions, np.arange(600, dtype=np.float64).reshape(200, 3))
    before = [cloud_paths(project_id, cloud_id)["positions"].read_bytes() for cloud_id in cloud_ids]
    matrix = np.eye(4).tolist()

    def fake_global_fgr_icp(source, target, **kwargs):
        all_points = np.arange(600, dtype=np.float64).reshape(200, 3)
        source_order = np.random.default_rng(19).permutation(200)
        target_order = np.random.default_rng(20).permutation(200)
        fit_source_rows = source_order[:100]
        eval_source_rows = source_order[100:200]
        fit_target_rows = target_order[:100]
        eval_target_rows = target_order[100:200]
        np.testing.assert_array_equal(np.sort(source[:, 0]), np.sort(all_points[fit_source_rows, 0]))
        np.testing.assert_array_equal(np.sort(target[:, 0]), np.sort(all_points[fit_target_rows, 0]))
        np.testing.assert_array_equal(
            np.sort(kwargs["evaluation_source_points"][:, 0]),
            np.sort(all_points[eval_source_rows, 0]),
        )
        np.testing.assert_array_equal(
            np.sort(kwargs["evaluation_target_points"][:, 0]),
            np.sort(all_points[eval_target_rows, 0]),
        )
        assert set(source[:, 0]).isdisjoint(set(kwargs["evaluation_source_points"][:, 0]))
        assert set(target[:, 0]).isdisjoint(set(kwargs["evaluation_target_points"][:, 0]))
        assert kwargs["sample_seed"] == 17
        assert kwargs["voxel_size_m"] == 0.5
        assert kwargs["max_correspondence_distance_m"] == 0.25
        return {
            "status": "candidate", "accuracy_status": "not_measured",
            "independent_control_count": 0, "fit_residuals_are_independent": False,
            "method": "open3d_fgr_point_to_plane_icp", "matrix_4x4": matrix,
            "rotation_3x3": np.eye(3).tolist(), "translation": [0.0, 0.0, 0.0],
            "rmse_mm": 125.0, "inlier_count": 80, "source_sample_count": 100,
            "target_sample_count": 100, "inlier_fraction": 0.8, "iterations": None, "iteration_limit": 80,
            "sample_method": "seeded_random_without_replacement", "sample_seed": 17,
            "converged": None, "optimizer_convergence": "not_exposed_by_open3d_result",
            "global_fgr_fitness": 0.7, "global_fgr_rmse_mm": 300.0,
            "holdout": {
                "status": "evaluated", "rmse_mm": 130.0,
                "inlier_count": 75, "source_sample_count": 100,
                "target_sample_count": 100, "inlier_fraction": 0.75,
                "is_disjoint_from_fit": True,
            },
            "voxel_size_m": 0.5, "max_correspondence_distance_m": 0.25,
        }

    monkeypatch.setattr(registration_api, "global_fgr_icp", fake_global_fgr_icp)
    response = client.post("/api/v1/registration/global-match", json={
        "source_cloud_id": cloud_ids[0], "target_cloud_id": cloud_ids[1],
        "sample_points": 100, "sample_seed": 17, "max_correspondence_distance_m": 0.25,
    })

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "candidate"
    assert result["accuracy_status"] == "not_measured"
    assert result["method"] == "open3d_fgr_point_to_plane_icp"
    assert result["holdout"]["status"] == "evaluated"
    assert result["holdout"]["is_disjoint_from_fit"] is True
    assert "Невязки подгонки" in result["fit_note"]
    assert result["world_matrix_4x4"] is not None
    assert result["coordinate_frame"]["matrix_4x4"] == "stored_local_source_to_stored_local_target"
    assert client.get(f"/api/v1/projects/{project_id}/station-registrations").json()["items"] == []
    assert [cloud_paths(project_id, cloud_id)["positions"].read_bytes() for cloud_id in cloud_ids] == before


def test_registration_rejects_clouds_below_icp_minimum(client):
    project = client.post("/api/v1/projects", json={"name": "Small registration test"}).json()
    cloud_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (cloud_id, project["id"], "Small cloud", "small.ply", "ply", 100, "ready", now, now),
    )
    point_path = cloud_paths(project["id"], cloud_id)["positions"]
    point_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(point_path, np.zeros((9, 3), dtype=np.float64))

    response = client.post("/api/v1/registration/match", json={
        "source_cloud_id": cloud_id,
        "target_cloud_id": cloud_id,
        "sample_points": 10,
    })

    assert response.status_code == 400
    assert "не менее 10 точек" in response.json()["detail"]
