"""Station panorama API: real points in, honest answers out, no invented measurement."""
from __future__ import annotations

import io
import json
import math
import uuid

import numpy as np
import pytest
from PIL import Image

from scan2bim import db as database
from scan2bim.processing.panorama import project_point_to_uv
from scan2bim.storage import cloud_paths

STATION_POINTS = np.array(
    [
        [5.0, 0.0, 0.0],
        [-5.0, 0.0, 0.0],
        [0.0, 5.0, 0.0],
        [0.0, -5.0, 0.0],
        [0.0, 0.0, 3.0],
        [0.0, 0.0, -3.0],
    ],
    dtype=np.float32,
)


def _create_cloud(*, status: str = "ready", with_stations: bool = True) -> tuple[str, str, dict]:
    project_id = f"project-pano-{uuid.uuid4().hex[:10]}"
    cloud_id = f"cloud-pano-{uuid.uuid4().hex[:10]}"
    now = database.utcnow()
    origin = [100.0, 200.0, 10.0]
    metadata: dict = {"origin": origin, "station_count": 2}
    if with_stations:
        metadata["station_row_ranges"] = [
            {
                "station_id": "st-01",
                "source_row_start": 0,
                "source_row_end_exclusive": 6,
                "source_row_count": 6,
                "source_row_index_base": 0,
            },
            {
                "station_id": "st-02",
                "source_row_start": 6,
                "source_row_end_exclusive": 12,
                "source_row_count": 6,
                "source_row_index_base": 0,
            },
        ]

    points = np.vstack([STATION_POINTS, STATION_POINTS + np.array([20.0, 0.0, 0.0], dtype=np.float32)])
    with database.db() as con:
        con.execute(
            "INSERT INTO projects (id,name,created_at,updated_at) VALUES (?,?,?,?)",
            (project_id, "Panorama project", now, now),
        )
        con.execute(
            "INSERT INTO clouds (id,project_id,name,source_path,source_format,point_count,"
            "ingested_count,status,metadata_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                cloud_id,
                project_id,
                "Two stations",
                "synthetic.rcs",
                "rcs",
                len(points),
                len(points),
                status,
                json.dumps(metadata),
                now,
                now,
            ),
        )

    paths = cloud_paths(project_id, cloud_id)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    np.save(paths["positions"], points)
    paths["meta"].write_text(json.dumps(metadata), encoding="utf-8")
    return project_id, cloud_id, metadata


@pytest.fixture
def stations_cloud(client):
    return _create_cloud()


def _png_bytes(width: int, height: int, colour=(40, 90, 140)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def test_station_list_reports_measured_anchors(client, stations_cloud):
    _, cloud_id, _ = stations_cloud
    response = client.get(f"/api/v1/clouds/{cloud_id}/stations")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["count"] == 2
    first, second = body["stations"]
    assert first["station_id"] == "st-01"
    assert first["station_source"] == "station_row_ranges"
    assert first["anchor_kind"] == "point_centroid"
    assert first["point_count"] == 6
    # Station centroids are symmetric around the cloud origin.
    assert first["anchor"] == pytest.approx([100.0, 200.0, 10.0], abs=1e-3)
    assert second["anchor"] == pytest.approx([120.0, 200.0, 10.0], abs=1e-3)
    assert first["has_photo"] is False
    assert first["panorama_url"].endswith("/st-01/panorama")


def test_station_list_requires_ingested_cloud(client):
    _, cloud_id, _ = _create_cloud(status="processing")
    response = client.get(f"/api/v1/clouds/{cloud_id}/stations")
    assert response.status_code == 409
    assert response.json()["detail"]["cloud_status"] == "processing"


def test_unknown_station_is_404(client, stations_cloud):
    _, cloud_id, _ = stations_cloud
    response = client.get(f"/api/v1/clouds/{cloud_id}/stations/st-99/panorama")
    assert response.status_code == 404


def test_panorama_renders_from_points_and_says_so(client, stations_cloud):
    _, cloud_id, _ = stations_cloud
    response = client.get(f"/api/v1/clouds/{cloud_id}/stations/st-01/panorama")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-panorama-source"] == "point_cloud"
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size == (2048, 1024)
        assert image.mode == "RGB"


def test_photo_upload_replaces_cloud_view_and_can_be_removed(client, stations_cloud):
    _, cloud_id, _ = stations_cloud
    upload = client.post(
        f"/api/v1/clouds/{cloud_id}/stations/st-01/photo",
        files={"file": ("scan.png", _png_bytes(1200, 600), "image/png")},
        data={"yaw_offset_deg": "15"},
    )
    assert upload.status_code == 200, upload.text
    meta = upload.json()["photo"]
    assert meta["is_photograph"] is True
    assert meta["projection"] == "equirectangular"
    assert meta["width"] == 1200 and meta["height"] == 600
    assert len(meta["sha256"]) == 64
    assert meta["yaw_offset_deg"] == 15

    listing = client.get(f"/api/v1/clouds/{cloud_id}/stations").json()["stations"][0]
    assert listing["has_photo"] is True
    assert listing["photo"]["sha256"] == meta["sha256"]

    served = client.get(f"/api/v1/clouds/{cloud_id}/stations/st-01/panorama")
    assert served.status_code == 200
    assert served.headers["x-panorama-source"] == "photo"
    with Image.open(io.BytesIO(served.content)) as image:
        assert image.size == (1200, 600)

    cloud_view = client.get(f"/api/v1/clouds/{cloud_id}/stations/st-01/panorama?source=cloud")
    assert cloud_view.headers["x-panorama-source"] == "point_cloud"

    removed = client.delete(f"/api/v1/clouds/{cloud_id}/stations/st-01/photo")
    assert removed.status_code == 200
    assert client.get(f"/api/v1/clouds/{cloud_id}/stations").json()["stations"][0]["has_photo"] is False
    assert client.get(f"/api/v1/clouds/{cloud_id}/stations/st-01/panorama?source=photo").status_code == 404


def test_photo_upload_rejects_non_equirectangular(client, stations_cloud):
    _, cloud_id, _ = stations_cloud
    response = client.post(
        f"/api/v1/clouds/{cloud_id}/stations/st-01/photo",
        files={"file": ("square.png", _png_bytes(1200, 1200), "image/png")},
    )
    assert response.status_code == 422
    assert "2:1" in response.json()["detail"]


def test_photo_upload_rejects_non_image(client, stations_cloud):
    _, cloud_id, _ = stations_cloud
    response = client.post(
        f"/api/v1/clouds/{cloud_id}/stations/st-01/photo",
        files={"file": ("notes.txt", b"not an image at all", "text/plain")},
    )
    assert response.status_code == 422


def test_measure_returns_real_distance_between_scanned_points(client, stations_cloud):
    _, cloud_id, _ = stations_cloud
    anchor = np.array([0.0, 0.0, 0.0])
    u_a, v_a, _ = project_point_to_uv(np.array([5.0, 0.0, 0.0]), anchor)
    u_b, v_b, _ = project_point_to_uv(np.array([-5.0, 0.0, 0.0]), anchor)

    response = client.post(
        f"/api/v1/clouds/{cloud_id}/stations/st-01/measure",
        json={"a": {"u": u_a, "v": v_a}, "b": {"u": u_b, "v": v_b}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resolved"] is True
    assert body["distance_m"] == pytest.approx(10.0, rel=0.02)
    assert body["precision_mm"] > 0
    assert body["depth_source"] == "point_cloud"
    assert body["reliable"] is True
    # World coordinates: the cloud origin is added on the way out, and the
    # cloud-frame point stays available for verification.
    assert body["a"]["point"][0] == pytest.approx(105.0, abs=0.2)
    assert body["b"]["point"][0] == pytest.approx(95.0, abs=0.2)
    assert body["a"]["point_local"][0] == pytest.approx(5.0, abs=0.2)
    assert body["b"]["point_local"][0] == pytest.approx(-5.0, abs=0.2)
    assert body["a"]["stable"] is True


def test_measure_refuses_pixels_without_points(client, stations_cloud):
    _, cloud_id, _ = stations_cloud
    # Nothing was scanned on the diagonal between the +X/-X and +Y/-Y points.
    response = client.post(
        f"/api/v1/clouds/{cloud_id}/stations/st-01/measure",
        json={"a": {"u": 0.125, "v": 0.5}, "b": {"u": 0.5, "v": 0.5}},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "нет точек" in detail["summary"]
    assert "distance_mm" not in detail


def test_pick_reports_world_point_and_precision(client, stations_cloud):
    _, cloud_id, _ = stations_cloud
    anchor = np.array([0.0, 0.0, 0.0])
    u, v, _ = project_point_to_uv(np.array([0.0, 5.0, 0.0]), anchor)

    response = client.post(
        f"/api/v1/clouds/{cloud_id}/stations/st-01/pick",
        json={"u": u, "v": v},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resolved"] is True
    assert body["distance_m"] == pytest.approx(5.0, rel=0.01)
    assert body["point"][1] == pytest.approx(205.0, abs=0.1)
    assert body["point_local"][1] == pytest.approx(5.0, abs=0.1)
    assert body["angular_resolution_deg"] == pytest.approx([360.0 / 2048, 180.0 / 1024])


def test_pick_rejects_out_of_range_uv(client, stations_cloud):
    _, cloud_id, _ = stations_cloud
    response = client.post(
        f"/api/v1/clouds/{cloud_id}/stations/st-01/pick",
        json={"u": 1.2, "v": 0.5},
    )
    assert response.status_code == 422


def test_single_station_cloud_is_marked_as_such(client):
    _, cloud_id, _ = _create_cloud(with_stations=False)
    body = client.get(f"/api/v1/clouds/{cloud_id}/stations").json()
    assert body["count"] == 1
    assert body["stations"][0]["station_id"] == "cloud"
    assert body["stations"][0]["station_source"] == "cloud"
    assert body["stations"][0]["point_count"] == 12


def test_panorama_cache_is_reused_until_positions_change(client, stations_cloud):
    _, cloud_id, metadata = stations_cloud
    first = client.get(f"/api/v1/clouds/{cloud_id}/stations/st-02/panorama")
    assert first.status_code == 200
    cloud = client.get(f"/api/v1/clouds/{cloud_id}").json()
    paths = cloud_paths(cloud["project_id"], cloud_id)
    meta_path = paths["dir"] / "panoramas" / "st-02" / "cloud_panorama.json"
    canary = json.loads(meta_path.read_text(encoding="utf-8"))
    rendered_at = canary["rendered_at"]
    # The sheet states which renderer produced it and how much it covers.
    assert canary["renderer"] in {"sampled", "streaming"}
    assert canary["renderer_version"]
    assert 0.0 < canary["coverage"] <= 1.0
    assert canary["render_seconds"] >= 0.0
    assert canary["coverage_note"]

    second = client.get(f"/api/v1/clouds/{cloud_id}/stations/st-02/panorama")
    assert second.status_code == 200
    assert json.loads(meta_path.read_text(encoding="utf-8"))["rendered_at"] == rendered_at


def test_cloud_panorama_can_be_queued_and_rendered_by_headless_worker(client, stations_cloud, monkeypatch):
    _, cloud_id, _ = stations_cloud
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")

    url = f"/api/v1/clouds/{cloud_id}/stations/st-01/panorama/render?width=1024&height=512"
    queued = client.post(url)
    assert queued.status_code == 200, queued.text
    body = queued.json()
    assert body["status"] == "queued"
    job_id = body["job"]["id"]
    assert body["job"]["status"] == "queued"

    duplicate = client.post(url)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["job"]["id"] == job_id

    from scan2bim.worker import run_once

    assert run_once("test-panorama-worker") is True
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "succeeded", job
    assert job["progress"] == 1.0
    assert job["result"]["panorama"]["source"] == "point_cloud"

    cached = client.post(url)
    assert cached.status_code == 200, cached.text
    assert cached.json()["status"] == "ready"
    assert cached.json()["panorama"]["cache_key"] == job["result"]["panorama"]["cache_key"]
