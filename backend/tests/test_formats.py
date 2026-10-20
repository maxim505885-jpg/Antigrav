"""Readers must round-trip known synthetic coordinates."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scan2bim.demo import generate_room_points
from scan2bim.formats import RcsConversionRequired, detect_format, read_cloud


def _xyz(path: Path, spacing: float = 0.2, cols: int = 6) -> tuple[np.ndarray, np.ndarray]:
    xyz, rgb, _ = generate_room_points(spacing=spacing)
    if cols == 3:
        arr = xyz
    else:
        arr = np.column_stack([xyz, rgb])
    np.savetxt(path, arr, fmt="%.5f")
    return xyz, rgb


def test_ply_reader(tmp_path: Path):
    from plyfile import PlyData, PlyElement

    xyz, rgb, _ = generate_room_points(spacing=0.4)
    vertex = np.empty(
        len(xyz),
        dtype=[("x", "f4"), ("y", "f4"), ("z", "f4"), ("red", "u1"), ("green", "u1"), ("blue", "u1")],
    )
    vertex["x"], vertex["y"], vertex["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    vertex["red"], vertex["green"], vertex["blue"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    path = tmp_path / "cloud.ply"
    PlyData([PlyElement.describe(vertex, "vertex")], text=False).write(str(path))
    assert detect_format(path) == "ply"
    cloud = read_cloud(path)
    assert len(cloud.xyz) == len(xyz)
    assert cloud.rgb is not None
    assert np.allclose(cloud.xyz.min(axis=0), xyz.min(axis=0), atol=1e-4)


def test_las_reader_roundtrip(tmp_path: Path):
    import laspy

    xyz, rgb, _ = generate_room_points(spacing=0.5)
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.offsets = xyz.min(axis=0)
    header.scales = np.array([0.001, 0.001, 0.001])
    las = laspy.LasData(header)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    las.red = (rgb[:, 0].astype(np.uint16) * 257)
    las.green = (rgb[:, 1].astype(np.uint16) * 257)
    las.blue = (rgb[:, 2].astype(np.uint16) * 257)
    path = tmp_path / "cloud.las"
    las.write(path)
    assert detect_format(path) == "las"
    cloud = read_cloud(path)
    assert len(cloud.xyz) == len(xyz)
    assert cloud.rgb is not None
    assert np.allclose(cloud.xyz.min(axis=0), xyz.min(axis=0), atol=0.01)


def test_laz_reader(tmp_path: Path):
    import laspy

    xyz, _, _ = generate_room_points(spacing=1.0)
    header = laspy.LasHeader(point_format=0, version="1.2")
    las = laspy.LasData(header)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    path = tmp_path / "cloud.laz"
    las.write(path)
    assert detect_format(path) == "laz"
    cloud = read_cloud(path)
    assert len(cloud.xyz) == len(xyz)


def test_xyz_and_pts_readers(tmp_path: Path):
    path = tmp_path / "cloud.xyz"
    xyz, rgb = _xyz(path, spacing=0.8, cols=6)
    cloud = read_cloud(path)
    assert len(cloud.xyz) == len(xyz)
    assert cloud.rgb is not None
    assert np.allclose(cloud.xyz.mean(axis=0), xyz.mean(axis=0), atol=0.01)

    pts = tmp_path / "cloud.pts"
    arr = np.column_stack([xyz, np.zeros(len(xyz)), rgb])
    with pts.open("w", encoding="utf-8") as fh:
        fh.write(f"{len(arr)}\n")
        np.savetxt(fh, arr, fmt="%.4f")
    parsed = read_cloud(pts)
    assert len(parsed.xyz) == len(xyz)
    assert parsed.metadata.get("has_color")


def test_decimation_is_reported(tmp_path: Path):
    path = tmp_path / "cloud.xyz"
    xyz, _ = _xyz(path, spacing=0.5, cols=3)
    cloud = read_cloud(path, max_points=100)
    assert len(cloud.xyz) <= 100
    assert cloud.metadata["decimated"] is True
    assert cloud.metadata["source_point_count"] == len(xyz)


def test_rcs_is_refused_with_guidance(tmp_path: Path):
    path = tmp_path / "scan.rcs"
    path.write_bytes(b"ADOCT" + b"\x00" * 64)
    assert detect_format(path) == "rcs"
    with pytest.raises(RcsConversionRequired) as exc:
        read_cloud(path)
    guidance = exc.value.guidance
    assert "proprietary" in guidance["summary"].lower()
    assert any("E57" in step for step in guidance["steps"])


def test_e57_reader_roundtrip(tmp_path: Path):
    """E57 is a listed format; prove the reader on a file we actually wrote."""
    pye57 = pytest.importorskip("pye57")

    xyz, rgb, _ = generate_room_points(spacing=0.5)
    keep = len(xyz) // 3
    xyz, rgb = xyz[:keep], rgb[:keep]

    path = tmp_path / "room.e57"
    e57 = pye57.E57(str(path), mode="w")
    try:
        e57.write_scan_raw(
            {
                "cartesianX": xyz[:, 0].astype(np.float64),
                "cartesianY": xyz[:, 1].astype(np.float64),
                "cartesianZ": xyz[:, 2].astype(np.float64),
                "colorRed": rgb[:, 0].astype(np.uint8),
                "colorGreen": rgb[:, 1].astype(np.uint8),
                "colorBlue": rgb[:, 2].astype(np.uint8),
            }
        )
    finally:
        e57.close()

    assert detect_format(path) == "e57"
    cloud = read_cloud(path, max_points=0)
    assert cloud.xyz.shape[1] == 3
    assert len(cloud.xyz) == keep
    # Coordinates must survive the round trip, not just the point count.
    assert np.allclose(np.sort(cloud.xyz, axis=0), np.sort(xyz, axis=0), atol=1e-6)
    assert cloud.rgb is not None and cloud.rgb.shape == rgb.shape
