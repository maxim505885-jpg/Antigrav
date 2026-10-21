"""E57 streaming reader yields bounded chunks in source-cloud world coordinates."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scan2bim import ingest
from scan2bim.db import execute, new_id, one, utcnow
from scan2bim.formats import readers
from scan2bim.formats.readers import iter_e57_chunks, read_cloud
from scan2bim.storage import cloud_paths


def _write_two_scan_e57(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    from pye57 import E57

    local_a = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]])
    local_b = np.array([[-2.0, 1.0, 0.5], [0.0, 3.0, 2.5], [4.0, 5.0, 4.5]])
    colors_a = np.array([[10, 20, 30], [40, 50, 60], [70, 80, 90], [100, 110, 120]], dtype=np.uint8)
    colors_b = np.array([[130, 140, 150], [160, 170, 180], [190, 200, 210]], dtype=np.uint8)
    translation_a = np.array([100.0, 200.0, 300.0])
    translation_b = np.array([-50.0, 25.0, 10.0])

    e57 = E57(str(path), mode="w")
    try:
        for xyz, rgb, translation in ((local_a, colors_a, translation_a), (local_b, colors_b, translation_b)):
            e57.write_scan_raw(
                {
                    "cartesianX": xyz[:, 0],
                    "cartesianY": xyz[:, 1],
                    "cartesianZ": xyz[:, 2],
                    "colorRed": rgb[:, 0],
                    "colorGreen": rgb[:, 1],
                    "colorBlue": rgb[:, 2],
                    "intensity": np.arange(len(xyz), dtype=np.float32) + 0.25,
                },
                translation=translation,
            )
    finally:
        e57.close()

    world = np.vstack([local_a + translation_a, local_b + translation_b])
    colors = np.vstack([colors_a, colors_b])
    intensity = np.concatenate([
        np.arange(len(local_a), dtype=np.float32) + 0.25,
        np.arange(len(local_b), dtype=np.float32) + 0.25,
    ])
    return world, colors, intensity


def test_e57_chunks_are_bounded_and_match_world_coordinates_and_fields(tmp_path: Path):
    path = tmp_path / "two-scans.e57"
    expected_xyz, expected_rgb, expected_intensity = _write_two_scan_e57(path)

    chunks = list(iter_e57_chunks(path, chunk_points=2))

    assert len(chunks) == 4
    assert all(0 < len(xyz) <= 2 for xyz, _, _ in chunks)
    actual_xyz = np.concatenate([xyz for xyz, _, _ in chunks])
    actual_rgb = np.concatenate([rgb for _, rgb, _ in chunks if rgb is not None])
    actual_intensity = np.concatenate([intensity for _, _, intensity in chunks if intensity is not None])
    assert np.allclose(actual_xyz, expected_xyz, atol=1e-6)
    assert np.array_equal(actual_rgb, expected_rgb)
    assert np.allclose(actual_intensity, expected_intensity, atol=1e-6)


def test_e57_chunked_and_existing_reader_return_same_coordinates(tmp_path: Path):
    path = tmp_path / "two-scans.e57"
    _write_two_scan_e57(path)

    streamed = np.concatenate([xyz for xyz, _, _ in iter_e57_chunks(path, chunk_points=3)])
    compatible = read_cloud(path, max_points=0).xyz

    assert np.allclose(streamed, compatible, atol=1e-6)


def test_unlimited_e57_ingest_writes_full_cloud_through_disk_backed_arrays(
    client, tmp_path: Path, monkeypatch
):
    from pye57 import E57

    path = tmp_path / "full-resolution.e57"
    xyz = np.array([[10.0 + i, 20.0 - i, 3.0 + i * 0.5] for i in range(7)])
    rgb = np.array([[i, i + 20, i + 40] for i in range(7)], dtype=np.uint8)
    intensity = np.arange(7, dtype=np.float32) + 0.5
    e57 = E57(str(path), mode="w")
    try:
        e57.write_scan_raw(
            {
                "cartesianX": xyz[:, 0],
                "cartesianY": xyz[:, 1],
                "cartesianZ": xyz[:, 2],
                "colorRed": rgb[:, 0],
                "colorGreen": rgb[:, 1],
                "colorBlue": rgb[:, 2],
                "intensity": intensity,
            }
        )
    finally:
        e57.close()

    project = client.post("/api/v1/projects", json={"name": "streamed E57"}).json()
    cloud_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds
        (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (cloud_id, project["id"], path.name, str(path), "e57", path.stat().st_size, "processing", now, now),
    )
    monkeypatch.setattr(ingest, "MAX_INGEST_POINTS", 0)
    monkeypatch.setattr(ingest, "MAX_PREVIEW_POINTS", 3)
    monkeypatch.setattr(ingest, "MIN_INGEST_DISK_RESERVE_BYTES", 0)
    monkeypatch.setattr(ingest, "read_cloud", lambda *_a, **_k: pytest.fail("whole-cloud E57 reader used"))

    result = ingest.ingest_cloud(project["id"], cloud_id, path)

    paths = cloud_paths(project["id"], cloud_id)
    origin = (xyz.min(axis=0) + xyz.max(axis=0)) / 2
    np.testing.assert_allclose(np.load(paths["positions"]), (xyz - origin).astype(np.float32))
    np.testing.assert_array_equal(np.load(paths["colors"]), rgb)
    np.testing.assert_allclose(np.load(paths["intensity"]), intensity)
    assert result["ingested_count"] == len(xyz)
    assert result["decimated"] is False
    row = one("SELECT status, point_count, ingested_count, sha256 FROM clouds WHERE id = ?", (cloud_id,))
    assert row["status"] == "ready"
    assert row["point_count"] == len(xyz) == row["ingested_count"]
    assert row["sha256"]
    assert not (paths["dir"] / ".ingest-stage").exists()


def _write_las(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import laspy

    xyz = np.array([[1000.0 + i * 0.25, 2000.0 - i * 0.5, 30.0 + i] for i in range(7)])
    rgb = np.array([[i * 10, i * 10 + 1, i * 10 + 2] for i in range(7)], dtype=np.uint8)
    intensity = np.arange(7, dtype=np.uint16) * 100 + 10
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = np.array([0.001, 0.001, 0.001])
    las = laspy.LasData(header)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    las.red, las.green, las.blue = (rgb[:, i].astype(np.uint16) * 257 for i in range(3))
    las.intensity = intensity
    las.write(path)
    return xyz, rgb, intensity


@pytest.mark.parametrize("suffix", ["las", "laz"])
def test_las_chunks_are_bounded_and_preserve_scaled_xyz_rgb_and_intensity(tmp_path: Path, suffix: str):
    path = tmp_path / f"chunked.{suffix}"
    xyz, rgb, intensity = _write_las(path)

    chunks = list(readers.iter_las_chunks(path, chunk_points=2))

    assert len(chunks) == 4
    assert all(0 < len(points) <= 2 for points, _, _ in chunks)
    np.testing.assert_allclose(np.concatenate([points for points, _, _ in chunks]), xyz, atol=0.001)
    np.testing.assert_array_equal(np.concatenate([colors for _, colors, _ in chunks]), rgb)
    np.testing.assert_array_equal(np.concatenate([values for _, _, values in chunks]), intensity)


def test_unlimited_las_ingest_writes_full_cloud_without_whole_cloud_reader(
    client, tmp_path: Path, monkeypatch
):
    path = tmp_path / "full-resolution.las"
    xyz, rgb, intensity = _write_las(path)
    project = client.post("/api/v1/projects", json={"name": "streamed LAS"}).json()
    cloud_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds
        (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (cloud_id, project["id"], path.name, str(path), "las", path.stat().st_size, "processing", now, now),
    )
    monkeypatch.setattr(ingest, "MAX_INGEST_POINTS", 0)
    monkeypatch.setattr(ingest, "MAX_PREVIEW_POINTS", 3)
    monkeypatch.setattr(ingest, "MIN_INGEST_DISK_RESERVE_BYTES", 0)
    monkeypatch.setattr(ingest, "read_cloud", lambda *_a, **_k: pytest.fail("whole-cloud LAS reader used"))

    result = ingest.ingest_cloud(project["id"], cloud_id, path)

    paths = cloud_paths(project["id"], cloud_id)
    origin = (xyz.min(axis=0) + xyz.max(axis=0)) / 2
    np.testing.assert_allclose(np.load(paths["positions"]), (xyz - origin).astype(np.float32))
    np.testing.assert_array_equal(np.load(paths["colors"]), rgb)
    np.testing.assert_allclose(np.load(paths["intensity"]), intensity.astype(np.float32))
    assert result["ingested_count"] == len(xyz)
    assert result["decimated"] is False
    row = one("SELECT status, point_count, ingested_count, sha256 FROM clouds WHERE id = ?", (cloud_id,))
    assert row["status"] == "ready"
    assert row["point_count"] == len(xyz) == row["ingested_count"]
    assert row["sha256"]
    assert not (paths["dir"] / ".ingest-stage").exists()
