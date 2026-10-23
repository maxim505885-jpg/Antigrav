"""Cloud export: real files, measured round-trip deviation, source untouched."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from conftest import wait_cloud, wait_job
from scan2bim.processing.cloud_export import (
    CloudExportError,
    EXPORT_FORMATS,
    export_cloud,
    write_e57,
    write_las,
)


def _room(n: int = 400, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    xyz = rng.uniform(0, 6, size=(n, 3)).astype(np.float32)
    rgb = rng.integers(0, 255, size=(n, 3), dtype=np.uint8)
    return xyz, rgb


def _store(tmp_path: Path) -> tuple[Path, Path]:
    xyz, rgb = _room()
    positions = tmp_path / "positions.npy"
    colors = tmp_path / "colors.npy"
    np.save(positions, xyz)
    np.save(colors, rgb)
    return positions, colors


def test_export_ply_roundtrip(tmp_path: Path):
    positions, colors = _store(tmp_path)
    meta = export_cloud(positions, tmp_path / "out.ply", "ply", colors_path=colors)
    assert meta["point_count"] == 400
    assert meta["verified"] is True
    # float32 storage: deviation bounded by coordinate magnitude
    assert meta["max_deviation_m"] <= meta["tolerance_m"]
    raw = (tmp_path / "out.ply").read_bytes()
    assert raw.startswith(b"ply\nformat binary_little_endian 1.0\n")


def test_export_xyz_roundtrip(tmp_path: Path):
    positions, _ = _store(tmp_path)
    meta = export_cloud(positions, tmp_path / "out.xyz", "xyz")
    assert meta["verified"] is True
    assert meta["max_deviation_m"] <= 1e-3


def test_export_las_roundtrip(tmp_path: Path):
    pytest.importorskip("laspy")
    positions, colors = _store(tmp_path)
    meta = export_cloud(positions, tmp_path / "out.las", "las", colors_path=colors)
    assert meta["verified"] is True
    assert meta["read_back_has_color"] is True
    assert meta["max_deviation_m"] <= 1e-5


def test_export_laz_roundtrip(tmp_path: Path):
    pytest.importorskip("laspy")
    pytest.importorskip("lazrs")
    positions, _ = _store(tmp_path)
    meta = export_cloud(positions, tmp_path / "out.laz", "laz")
    assert meta["verified"] is True
    assert meta["max_deviation_m"] <= 1e-5


def test_export_e57_roundtrip(tmp_path: Path):
    pytest.importorskip("pye57")
    positions, colors = _store(tmp_path)
    meta = export_cloud(positions, tmp_path / "out.e57", "e57", colors_path=colors)
    assert meta["verified"] is True
    assert meta["read_back_has_color"] is True
    assert meta["max_deviation_m"] <= 1e-9


def test_export_rejects_unknown_format(tmp_path: Path):
    positions, _ = _store(tmp_path)
    with pytest.raises(CloudExportError):
        export_cloud(positions, tmp_path / "out.xyz", "dwg")


def test_export_keeps_source_bytes(tmp_path: Path):
    positions, colors = _store(tmp_path)
    before = hashlib.sha256(positions.read_bytes()).hexdigest()
    export_cloud(positions, tmp_path / "out.ply", "ply", colors_path=colors)
    assert hashlib.sha256(positions.read_bytes()).hexdigest() == before


def test_export_rejects_nonfinite_coordinates_beyond_initial_sample(tmp_path: Path):
    xyz, _ = _room(1200)
    xyz[1100, 1] = np.nan
    positions = tmp_path / "positions.npy"
    np.save(positions, xyz)

    with pytest.raises(CloudExportError, match="non-finite coordinates"):
        export_cloud(positions, tmp_path / "out.ply", "ply")

    assert not (tmp_path / "out.ply").exists()


def test_write_las_scale_is_metric(tmp_path: Path):
    pytest.importorskip("laspy")
    import laspy

    xyz = np.array([[100.0, 200.0, 10.0], [100.5, 200.25, 10.75]], dtype=np.float64)
    path = write_las(xyz, tmp_path / "metric.las")
    back = laspy.read(str(path))
    assert np.allclose(np.array([back.x, back.y, back.z]).T, xyz, atol=1e-6)


def test_write_e57_requires_no_transform_drift(tmp_path: Path):
    pytest.importorskip("pye57")
    xyz = np.array([[0.0, 0.0, 0.0], [1.23456789, -2.0, 3.5]], dtype=np.float64)
    path = write_e57(xyz, tmp_path / "exact.e57")
    from scan2bim.formats.readers import read_cloud

    cloud = read_cloud(path, max_points=0)
    assert np.allclose(np.sort(cloud.xyz, axis=0), np.sort(xyz, axis=0), atol=1e-9)


def test_export_api_roundtrip(client):
    demo = client.post("/api/v1/demo")
    assert demo.status_code == 200, demo.text
    cloud = wait_cloud(client, demo.json()["cloud"]["id"])
    assert cloud["status"] == "ready"
    source_count = cloud["ingested_count"]

    job = client.post(
        f"/api/v1/clouds/{cloud['id']}/export",
        json={"format": "ply", "verify": True},
    )
    assert job.status_code == 200, job.text
    done = wait_job(client, job.json()["id"])
    assert done["status"] == "succeeded", done.get("error")
    meta = done["result"]
    assert meta["point_count"] == source_count
    assert meta["verified"] is True
    assert meta["export_id"]

    listed = client.get(f"/api/v1/clouds/{cloud['id']}/exports").json()
    assert len(listed) == 1
    assert listed[0]["format"] == "ply"
    assert listed[0]["export_id"] == meta["export_id"]

    download = client.get(
        f"/api/v1/clouds/{cloud['id']}/exports/{listed[0]['export_id']}/download"
    )
    assert download.status_code == 200, download.text
    assert download.content.startswith(b"ply\n")

    # The source cloud must be untouched by the export.
    cloud_after = client.get(f"/api/v1/clouds/{cloud['id']}").json()
    assert cloud_after["ingested_count"] == source_count


def test_export_api_rejects_bad_derived_id(client):
    demo = client.post("/api/v1/demo")
    cloud = wait_cloud(client, demo.json()["cloud"]["id"])
    job = client.post(
        f"/api/v1/clouds/{cloud['id']}/export",
        json={"format": "ply", "derived_id": "../../etc"},
    )
    assert job.status_code == 404, job.text
    assert "derived cloud not found" in job.json()["detail"]


def test_export_api_download_rejects_path_traversal(client):
    demo = client.post("/api/v1/demo")
    cloud = wait_cloud(client, demo.json()["cloud"]["id"])
    response = client.get(f"/api/v1/clouds/{cloud['id']}/exports/..%2F..%2Fetc/download")
    assert response.status_code == 404


def test_export_formats_are_documented():
    assert set(EXPORT_FORMATS) == {"e57", "las", "laz", "ply", "xyz"}
