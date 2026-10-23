"""Cleanup filters: real geometry in, honest counts out, source untouched."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from conftest import wait_cloud, wait_job
from scan2bim.processing.cleanup import (
    CleanupError,
    apply_cleanup,
    radius_outlier_mask,
    statistical_outlier_mask,
    voxel_downsample_indices,
    write_ply,
)


def _dense_grid(step: float = 0.05, n: int = 12) -> np.ndarray:
    axis = np.arange(n) * step
    gx, gy, gz = np.meshgrid(axis, axis, axis)
    return np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()]).astype(np.float32)


def test_statistical_filter_removes_isolated_point():
    points = np.vstack([_dense_grid(), np.array([[50.0, 50.0, 50.0]], dtype=np.float32)])
    keep, stats = statistical_outlier_mask(points, k=8, std_ratio=2.0)
    assert keep[-1] is np.bool_(False) or not bool(keep[-1])
    assert bool(keep[:-1].mean() > 0.95)
    assert stats["removed"] == 1
    assert stats["threshold_m"] > 0


def test_radius_filter_removes_isolated_point():
    points = np.vstack([_dense_grid(), np.array([[40.0, 40.0, 40.0]], dtype=np.float32)])
    keep, stats = radius_outlier_mask(points, radius=0.12, min_neighbors=3)
    assert not bool(keep[-1])
    assert bool(keep[:-1].mean() > 0.95)
    assert stats["removed"] == 1


def test_radius_filter_rejects_non_positive_radius():
    with pytest.raises(CleanupError):
        radius_outlier_mask(_dense_grid(), radius=0.0)


def test_voxel_keeps_one_point_per_voxel():
    points = np.array(
        [
            [0.01, 0.01, 0.01],
            [0.02, 0.02, 0.02],
            [0.50, 0.50, 0.50],
        ],
        dtype=np.float32,
    )
    indices, stats = voxel_downsample_indices(points, voxel_m=0.10)
    assert len(indices) == 2
    assert stats["voxels"] == 2
    assert indices[0] == 0  # first representative of the shared voxel


def test_apply_cleanup_keeps_source_bytes_and_writes_meta(tmp_path: Path):
    rng = np.random.default_rng(5)
    points = rng.uniform(0, 2, size=(600, 3)).astype(np.float32)
    colors = rng.integers(0, 255, size=(600, 3), dtype=np.uint8)
    source = tmp_path / "positions.npy"
    colors_path = tmp_path / "colors.npy"
    np.save(source, points)
    np.save(colors_path, colors)
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    derived = tmp_path / "derived" / "abc123"
    meta = apply_cleanup(
        source,
        derived,
        "voxel",
        {"voxel_m": 0.20},
        colors_path=colors_path,
    )

    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert meta["input_count"] == 600
    assert meta["output_count"] < 600
    assert meta["source"]["source_unchanged"] is True
    stored = np.load(derived / "positions.npy")
    assert len(stored) == meta["output_count"]
    stored_colors = np.load(derived / "colors.npy")
    assert stored_colors.shape == (meta["output_count"], 3)
    assert (derived / "meta.json").is_file()
    assert meta["has_normals"] is True
    normals = np.load(derived / "normals.npy")
    curvature = np.load(derived / "curvature.npy")
    assert normals.shape == (meta["output_count"], 3)
    assert curvature.shape == (meta["output_count"],)
    assert np.all(np.isfinite(normals))
    assert np.all(np.isfinite(curvature))


def test_apply_cleanup_drops_non_finite_points(tmp_path: Path):
    points = np.array(
        [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [np.nan, 0.0, 0.0]], dtype=np.float32
    )
    source = tmp_path / "positions.npy"
    np.save(source, points)
    meta = apply_cleanup(source, tmp_path / "out", "voxel", {"voxel_m": 0.5})
    assert meta["finite_count"] == 2
    assert meta["output_count"] <= 2


def test_apply_cleanup_rejects_unknown_method(tmp_path: Path):
    source = tmp_path / "positions.npy"
    np.save(source, np.zeros((4, 3), dtype=np.float32))
    with pytest.raises(CleanupError):
        apply_cleanup(source, tmp_path / "out", "magic", {})


def test_write_ply_binary_header_and_size(tmp_path: Path):
    points = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]], dtype=np.float32)
    colors = np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8)
    path = write_ply(points, colors, tmp_path / "cloud.ply")
    raw = path.read_bytes()
    assert raw.startswith(b"ply\nformat binary_little_endian 1.0\n")
    header_end = raw.index(b"end_header\n") + len(b"end_header\n")
    header = raw[:header_end].decode("ascii")
    assert "element vertex 2" in header
    assert "property uchar red" in header
    assert len(raw) - header_end == 2 * (3 * 4 + 3)


def test_cleanup_api_creates_and_downloads_derived_cloud(client):
    demo = client.post("/api/v1/demo")
    assert demo.status_code == 200, demo.text
    cloud = wait_cloud(client, demo.json()["cloud"]["id"])
    assert cloud["status"] == "ready"
    source_count = cloud["ingested_count"]

    job = client.post(
        f"/api/v1/clouds/{cloud['id']}/cleanup",
        json={"method": "voxel", "voxel_m": 0.30},
    )
    assert job.status_code == 200, job.text
    done = wait_job(client, job.json()["id"])
    assert done["status"] == "succeeded", done.get("error")
    result = done["result"]
    assert result["input_count"] == source_count
    assert result["output_count"] < result["input_count"]
    assert result["derived_id"]

    listed = client.get(f"/api/v1/clouds/{cloud['id']}/derived").json()
    assert len(listed) == 1
    assert listed[0]["method"] == "voxel"

    download = client.get(
        f"/api/v1/clouds/{cloud['id']}/derived/{result['derived_id']}/download?format=ply"
    )
    assert download.status_code == 200, download.text
    assert download.content.startswith(b"ply\n")
    assert f"element vertex {result['output_count']}".encode() in download.content[:400]

    cloud_after = client.get(f"/api/v1/clouds/{cloud['id']}").json()
    assert cloud_after["ingested_count"] == source_count


def test_cleanup_api_rejects_unknown_derived_id(client):
    demo = client.post("/api/v1/demo")
    cloud = wait_cloud(client, demo.json()["cloud"]["id"])
    response = client.get(f"/api/v1/clouds/{cloud['id']}/derived/../../etc/passwd/download")
    assert response.status_code == 404
