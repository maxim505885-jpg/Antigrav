import numpy as np
import pytest

from scan2bim.db import execute, new_id, utcnow
from scan2bim.registration.control_validation import evaluate_control_points


def test_control_evaluation_reports_independent_rmse_and_threshold():
    source = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    target = [[x + 0.2, y - 0.3, z + 0.4] for x, y, z in source]
    matrix = np.eye(4)
    matrix[:3, 3] = [0.2, -0.3, 0.4]

    result = evaluate_control_points(matrix.tolist(), source, target)

    assert result["accuracy_status"] == "independent_controls_measured"
    assert result["independence_attested_by_user"] is True
    assert result["independent_control_count"] == 3
    assert result["rmse_mm"] == pytest.approx(0.0, abs=1e-9)
    assert result["criterion_passed"] is True


def test_control_evaluation_fails_threshold_when_controls_disagree():
    source = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    target = [[0, 0, 0], [1.1, 0, 0], [0, 1, 0]]

    result = evaluate_control_points(np.eye(4).tolist(), source, target, acceptance_rmse_mm=10)

    assert result["rmse_mm"] == pytest.approx(57.7350269)
    assert result["max_error_mm"] == pytest.approx(100.0)
    assert result["criterion_passed"] is False


@pytest.mark.parametrize(
    ("matrix", "source", "target", "message"),
    [
        ([[1, 0], [0, 1]], [[0, 0, 0]] * 3, [[0, 0, 0]] * 3, "4×4"),
        (np.eye(4).tolist(), [[0, 0, 0]] * 3, [[0, 0, 0]] * 3, "уникальными"),
        (np.eye(4).tolist(), [[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 0, 0]] * 3, "уникальными"),
        (np.eye(4).tolist(), [[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 0, 0], [1, 0, 0], [2, 0, 0]], "почти коллинеарны"),
        (np.eye(4).tolist(), [[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 0, 0], [0, 1, 0], [0, 0, 1]], "почти коллинеарны"),
        (np.eye(4).tolist(), [[0, 0, 0], [0, 1, 0], [0, 0, 1]], [[0, 0, 0], [1, 0, 0], [2, 0, 0]], "почти коллинеарны"),
        (np.eye(4).tolist(), [[0, 0, 0]] * 2, [[0, 0, 0]] * 2, "не менее трёх"),
        ([[2, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
         [[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "жёсткое вращение"),
    ],
)
def test_control_evaluation_rejects_invalid_controls(matrix, source, target, message):
    with pytest.raises(ValueError, match=message):
        evaluate_control_points(matrix, source, target)


def test_live_endpoint_requires_independence_attestation_and_returns_residuals(client):
    project = client.post("/api/v1/projects", json={"name": "Control validation"}).json()
    source_id, target_id = new_id(), new_id()
    now = utcnow()
    for cloud_id, name in ((source_id, "Source"), (target_id, "Target")):
        execute(
            """INSERT INTO clouds
               (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (cloud_id, project["id"], name, f"{name}.rcs", "rcs", 0, "ready", now, now),
        )
    controls = [
        {"source_point": [0, 0, 0], "target_point": [1, 2, 3], "label": "A"},
        {"source_point": [1, 0, 0], "target_point": [2, 2, 3], "label": "B"},
        {"source_point": [0, 1, 0], "target_point": [1, 3, 3], "label": "C"},
    ]
    request = {
        "source_cloud_id": source_id,
        "target_cloud_id": target_id,
        "matrix_4x4": [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]],
        "controls": controls,
        "independent_of_fit": False,
    }

    rejected = client.post("/api/v1/registration/evaluate-controls", json=request)
    assert rejected.status_code == 400
    assert "независимы" in rejected.json()["detail"]

    request["independent_of_fit"] = True
    response = client.post("/api/v1/registration/evaluate-controls", json=request)
    assert response.status_code == 200
    result = response.json()
    assert result["independent_control_count"] == 3
    assert result["rmse_mm"] == pytest.approx(0.0, abs=1e-9)
    assert result["criterion_passed"] is True
    assert result["control_details"][0]["label"] == "A"
    assert result["accuracy_status"] == "independent_controls_measured"
