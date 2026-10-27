import pytest
import numpy as np

from scan2bim.db import dumps, execute, new_id, utcnow
from scan2bim.api import registration as registration_api
from scan2bim.storage import cloud_paths
from scan2bim.registration.stitching import (
    compute_pairwise_svd_alignment,
    convert_local_transform_to_world,
)


def test_compute_pairwise_svd_alignment_exact_transform():
    # 4 non-coplanar points
    src = np.array([
        [0.0, 0.0, 0.0],
        [5.0, 0.0, 0.0],
        [0.0, 4.0, 0.0],
        [0.0, 0.0, 3.0],
    ])
    # Rotate 90 degrees around Z, translate by (10, 20, 5)
    # [x, y, z] -> [-y + 10, x + 20, z + 5]
    dst = np.array([
        [10.0, 20.0, 5.0],
        [10.0, 25.0, 5.0],
        [6.0, 20.0, 5.0],
        [10.0, 20.0, 8.0],
    ])

    res = compute_pairwise_svd_alignment(src, dst)
    assert res["pairs_count"] == 4
    assert res["rmse_mm"] < 0.01
    assert res["max_error_mm"] < 0.01
    for r in res["residuals_mm"]:
        assert r < 0.01

    mat = np.array(res["matrix_4x4"])
    expected_r = np.array([
        [0.0, -1.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    assert np.allclose(mat[:3, :3], expected_r, atol=1e-5)
    assert np.allclose(mat[:3, 3], [10.0, 20.0, 5.0], atol=1e-5)


def test_compute_pairwise_svd_alignment_validation_errors():
    # Less than 3 points
    with pytest.raises(ValueError, match="At least 3 point pairs"):
        compute_pairwise_svd_alignment(np.zeros((2, 3)), np.zeros((2, 3)))

    # Collinear points
    src_collinear = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
    ])
    with pytest.raises(ValueError, match="collinear or degenerate"):
        compute_pairwise_svd_alignment(src_collinear, src_collinear + 1.0)


def test_local_pairwise_transform_converts_to_source_world_to_target_world():
    local = np.eye(4, dtype=np.float64)
    local[:3, :3] = np.array([
        [0.0, -1.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    local[:3, 3] = [10.0, 20.0, 5.0]
    source_origin = np.array([100.0, -50.0, 10.0])
    target_origin = np.array([-30.0, 80.0, 2.0])

    world = np.asarray(convert_local_transform_to_world(local, source_origin, target_origin))
    source_local = np.array([[1.0, 2.0, 3.0], [-5.0, 4.0, 0.5]])
    source_world = source_local + source_origin
    expected_target_world = (local[:3, :3] @ source_local.T).T + local[:3, 3] + target_origin
    actual_target_world = (world[:3, :3] @ source_world.T).T + world[:3, 3]

    assert np.allclose(actual_target_world, expected_target_world, atol=1e-10)
    assert np.allclose(world[:3, :3], local[:3, :3], atol=1e-12)


def test_local_pairwise_transform_rejects_invalid_frames():
    with pytest.raises(ValueError, match="4×4"):
        convert_local_transform_to_world(np.eye(3), [0, 0, 0], [0, 0, 0])
    with pytest.raises(ValueError, match="origins"):
        convert_local_transform_to_world(np.eye(4), [0, 0], [0, 0, 0])


def test_pair_align_endpoint(client):
    proj = client.post("/api/v1/projects", json={"name": "Pair Align Test"}).json()
    p_id = proj["id"]

    now = utcnow()
    c1_id = new_id()
    c2_id = new_id()

    execute(
        """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, origin_x, origin_y, origin_z, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (c1_id, p_id, "Cloud 1", "c1.ply", "ply", 100, "ready", 100.0, -50.0, 10.0, now, now)
    )
    execute(
        """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, origin_x, origin_y, origin_z, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (c2_id, p_id, "Cloud 2", "c2.ply", "ply", 100, "ready", 900.0, 20.0, -5.0, now, now)
    )

    pairs = [
        {"source_point": [0.0, 0.0, 0.0], "target_point": [2.0, 3.0, 4.0], "label": "Point A"},
        {"source_point": [10.0, 0.0, 0.0], "target_point": [12.0, 3.0, 4.0], "label": "Point B"},
        {"source_point": [0.0, 10.0, 0.0], "target_point": [2.0, 13.0, 4.0], "label": "Point C"},
        {"source_point": [0.0, 0.0, 10.0], "target_point": [2.0, 3.0, 14.0], "label": "Point D"},
    ]

    res = client.post("/api/v1/registration/pair-align", json={
        "source_cloud_id": c1_id,
        "target_cloud_id": c2_id,
        "pairs": pairs,
        "apply_icp_refinement": False,
    })

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["accuracy_status"] == "not_measured"
    assert data["independent_control_count"] == 0
    assert data["fit_residuals_are_independent"] is False
    assert data["pairs_count"] == 4
    assert data["rmse_mm"] < 0.01
    assert len(data["pair_details"]) == 4
    assert data["pair_details"][0]["label"] == "Point A"
    assert data["pair_details"][0]["residual_mm"] < 0.01
    assert np.allclose(data["matrix_4x4"][0:3], [
        [1.0, 0.0, 0.0, 2.0],
        [0.0, 1.0, 0.0, 3.0],
        [0.0, 0.0, 1.0, 4.0],
    ], atol=1e-10)
    assert np.allclose(data["world_matrix_4x4"][0:3], [
        [1.0, 0.0, 0.0, 802.0],
        [0.0, 1.0, 0.0, 73.0],
        [0.0, 0.0, 1.0, -11.0],
    ], atol=1e-10)
    assert data["coordinate_frame"]["matrix_4x4"] == "stored_local_source_to_stored_local_target"
    assert data["coordinate_frame"]["world_matrix_4x4"] == "source_world_to_target_world"

    execute(
        "UPDATE clouds SET metadata_json = ? WHERE id = ?",
        (dumps({"recap_project": {"transform_applied": False, "transform_4x4": np.eye(4).tolist()}}), c1_id),
    )
    unresolved_frame = client.post("/api/v1/registration/pair-align", json={
        "source_cloud_id": c1_id,
        "target_cloud_id": c2_id,
        "pairs": pairs,
        "apply_icp_refinement": False,
    }).json()
    assert unresolved_frame["world_matrix_4x4"] is None
    assert unresolved_frame["coordinate_frame"]["world_matrix_4x4"] is None


def test_pair_align_icp_refinement_receives_manual_pose_without_precentering(client, monkeypatch):
    project = client.post("/api/v1/projects", json={"name": "Tie point ICP initialization"}).json()
    source_id, target_id = new_id(), new_id()
    now = utcnow()
    for cloud_id, name in ((source_id, "Source"), (target_id, "Target")):
        execute(
            """INSERT INTO clouds
            (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (cloud_id, project["id"], name, f"{name.lower()}.ply", "ply", 100, "ready", now, now),
        )

    pairs = [
        {"source_point": [0.0, 0.0, 0.0], "target_point": [8.0, -3.0, 2.0]},
        {"source_point": [2.0, 0.0, 0.0], "target_point": [8.0, -1.0, 2.0]},
        {"source_point": [0.0, 3.0, 0.0], "target_point": [5.0, -3.0, 2.0]},
        {"source_point": [0.0, 0.0, 4.0], "target_point": [8.0, -3.0, 6.0]},
    ]
    source_samples = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 0.5], [-2.0, 1.0, 3.0]])
    target_samples = np.array([[20.0, 10.0, 5.0], [21.0, 12.0, 5.5], [18.0, 11.0, 8.0]])
    monkeypatch.setattr(
        registration_api,
        "_load_cloud_points",
        lambda cloud_id, _: (source_samples if cloud_id == source_id else target_samples, np.arange(3)),
    )
    captured = {}

    def fake_icp(source, target, **kwargs):
        captured["source"] = np.array(source)
        captured["target"] = np.array(target)
        captured.update(kwargs)
        return {
            "matrix_4x4": np.eye(4).tolist(),
            "rmse_mm": 2.5,
            "inlier_count": 42,
            "inlier_fraction": 0.42,
            "iterations": 4,
            "converged": True,
        }

    monkeypatch.setattr(registration_api, "rigid_icp", fake_icp)
    response = client.post("/api/v1/registration/pair-align", json={
        "source_cloud_id": source_id,
        "target_cloud_id": target_id,
        "pairs": pairs,
        "apply_icp_refinement": True,
    })

    assert response.status_code == 200
    result = response.json()
    np.testing.assert_allclose(captured["source"], source_samples)
    np.testing.assert_allclose(captured["target"], target_samples)
    np.testing.assert_allclose(captured["initial_t4x4"], result["matrix_4x4"])
    assert result["refined_with_icp"] is True
    assert result["icp_rmse_mm"] == 2.5
    assert result["icp_inlier_count"] == 42
    assert result["icp_inlier_fraction"] == 0.42
    assert result["icp_iterations"] == 4
    assert result["icp_converged"] is True


@pytest.mark.parametrize(
    "field,bad_point",
    [
        ("source_point", [0.0, 1.0]),
        ("source_point", [0.0, 1.0, 2.0, 3.0]),
        ("target_point", [0.0, 1.0]),
        ("target_point", [0.0, 1.0, 2.0, 3.0]),
    ],
)
def test_pair_align_rejects_malformed_point_dimensions_as_validation_error(client, field, bad_point):
    project = client.post("/api/v1/projects", json={"name": "Malformed tie point test"}).json()
    source_id = new_id()
    target_id = new_id()
    now = utcnow()
    for cloud_id, name in ((source_id, "Source"), (target_id, "Target")):
        execute(
            """INSERT INTO clouds
            (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (cloud_id, project["id"], name, f"{name.lower()}.ply", "ply", 100, "ready", now, now),
        )

    pairs = [
        {"source_point": [0.0, 0.0, 0.0], "target_point": [0.0, 0.0, 0.0]},
        {"source_point": [1.0, 0.0, 0.0], "target_point": [1.0, 0.0, 0.0]},
        {"source_point": [0.0, 1.0, 0.0], "target_point": [0.0, 1.0, 0.0]},
    ]
    pairs[2][field] = bad_point
    response = client.post("/api/v1/registration/pair-align", json={
        "source_cloud_id": source_id,
        "target_cloud_id": target_id,
        "pairs": pairs,
    })

    assert response.status_code == 422
    assert any(
        field in error["loc"]
        for error in response.json()["detail"]
    )
