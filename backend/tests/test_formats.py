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


def test_text_chunk_reader_preserves_csv_colors_and_pts_attributes(tmp_path: Path):
    from scan2bim.formats.readers import iter_text_chunks

    csv_path = tmp_path / "colored.csv"
    csv_path.write_text("0,0,0,10,20,30\n1,2,3,40,50,60\n", encoding="utf-8")
    csv_chunks = list(iter_text_chunks(csv_path, "csv", chunk_points=1))
    np.testing.assert_array_equal(np.concatenate([part[0] for part in csv_chunks]), [[0, 0, 0], [1, 2, 3]])
    np.testing.assert_array_equal(np.concatenate([part[1] for part in csv_chunks]), [[10, 20, 30], [40, 50, 60]])
    assert all(part[2] is None for part in csv_chunks)

    pts_path = tmp_path / "colored.pts"
    pts_path.write_text("2\n0 0 0 0.25 100 110 120\n1 2 3 0.75 130 140 150\n", encoding="utf-8")
    pts = list(iter_text_chunks(pts_path, "pts", chunk_points=1))
    np.testing.assert_array_equal(np.concatenate([part[2] for part in pts]), [0.25, 0.75])
    np.testing.assert_array_equal(np.concatenate([part[1] for part in pts]), [[100, 110, 120], [130, 140, 150]])


@pytest.mark.parametrize("data_kind", ["ascii", "binary"])
def test_pcd_chunk_reader_reads_bounded_xyz_rgb_intensity(tmp_path: Path, data_kind: str):
    from scan2bim.formats.readers import iter_pcd_chunks

    path = tmp_path / f"cloud-{data_kind}.pcd"
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\n"
        "VERSION 0.7\nFIELDS x y z intensity r g b\nSIZE 4 4 4 4 1 1 1\n"
        "TYPE F F F F U U U\nCOUNT 1 1 1 1 1 1 1\nWIDTH 2\nHEIGHT 1\nPOINTS 2\n"
        f"DATA {data_kind}\n"
    ).encode("ascii")
    if data_kind == "ascii":
        payload = b"0 0 0 0.25 10 20 30\n1 2 3 0.75 40 50 60\n"
    else:
        payload = np.array(
            [(0, 0, 0, 0.25, 10, 20, 30), (1, 2, 3, 0.75, 40, 50, 60)],
            dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4"),
                   ("r", "u1"), ("g", "u1"), ("b", "u1")],
        ).tobytes()
    path.write_bytes(header + payload)

    chunks = list(iter_pcd_chunks(path, chunk_points=1))
    assert [len(chunk[0]) for chunk in chunks] == [1, 1]
    np.testing.assert_array_equal(np.concatenate([chunk[0] for chunk in chunks]), [[0, 0, 0], [1, 2, 3]])
    np.testing.assert_array_equal(np.concatenate([chunk[1] for chunk in chunks]), [[10, 20, 30], [40, 50, 60]])
    np.testing.assert_allclose(np.concatenate([chunk[2] for chunk in chunks]), [0.25, 0.75])


@pytest.mark.parametrize("data_kind", ["ascii", "binary"])
def test_pcd_chunk_reader_decodes_packed_rgb_float(tmp_path: Path, data_kind: str):
    from scan2bim.formats.readers import iter_pcd_chunks

    packed = np.array([0x000A141E, 0x0028323C], dtype="<u4").view("<f4")
    path = tmp_path / f"packed-{data_kind}.pcd"
    header = (
        "# .PCD v0.7\nVERSION 0.7\nFIELDS x y z rgb\nSIZE 4 4 4 4\n"
        "TYPE F F F F\nCOUNT 1 1 1 1\nWIDTH 2\nHEIGHT 1\nPOINTS 2\n"
        f"DATA {data_kind}\n"
    ).encode("ascii")
    if data_kind == "ascii":
        payload = f"0 0 0 {float(packed[0])!r}\n1 2 3 {float(packed[1])!r}\n".encode("ascii")
    else:
        payload = np.array(
            [(0, 0, 0, packed[0]), (1, 2, 3, packed[1])],
            dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("rgb", "<f4")],
        ).tobytes()
    path.write_bytes(header + payload)
    chunks = list(iter_pcd_chunks(path, chunk_points=1))
    np.testing.assert_array_equal(np.concatenate([chunk[1] for chunk in chunks]), [[10, 20, 30], [40, 50, 60]])


@pytest.mark.parametrize("ply_format", ["ascii 1.0", "binary_little_endian 1.0", "binary_big_endian 1.0"])
def test_ply_chunk_reader_preserves_xyz_rgb_intensity(tmp_path: Path, ply_format: str):
    from scan2bim.formats.readers import iter_ply_chunks

    path = tmp_path / "chunked.ply"
    header = (
        f"ply\nformat {ply_format}\nelement vertex 2\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nproperty float intensity\n"
        "end_header\n"
    ).encode("ascii")
    if ply_format.startswith("ascii"):
        payload = b"0 0 0 1 0 1 0.25\n1 2 3 40 50 60 0.75\n"
    else:
        endian = ">" if ply_format.startswith("binary_big_endian") else "<"
        payload = np.array(
            [(0, 0, 0, 1, 0, 1, 0.25), (1, 2, 3, 40, 50, 60, 0.75)],
            dtype=[("x", f"{endian}f4"), ("y", f"{endian}f4"), ("z", f"{endian}f4"), ("red", "u1"),
                   ("green", "u1"), ("blue", "u1"), ("intensity", f"{endian}f4")],
        ).tobytes()
    path.write_bytes(header + payload)
    chunks = list(iter_ply_chunks(path, chunk_points=1))
    assert [len(chunk[0]) for chunk in chunks] == [1, 1]
    np.testing.assert_array_equal(np.concatenate([chunk[0] for chunk in chunks]), [[0, 0, 0], [1, 2, 3]])
    np.testing.assert_array_equal(np.concatenate([chunk[1] for chunk in chunks]), [[1, 0, 1], [40, 50, 60]])
    np.testing.assert_allclose(np.concatenate([chunk[2] for chunk in chunks]), [0.25, 0.75])


def test_stream_readers_reject_truncated_or_mismatched_point_counts(tmp_path: Path):
    from scan2bim.formats.readers import FormatError, iter_pcd_chunks, iter_ply_chunks

    pcd = tmp_path / "mismatched.pcd"
    pcd.write_text(
        "# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\n"
        "WIDTH 2\nHEIGHT 1\nPOINTS 2\nDATA ascii\n0 0 0\n",
        encoding="ascii",
    )
    with pytest.raises(FormatError, match="point count mismatch"):
        list(iter_pcd_chunks(pcd, chunk_points=1))

    ply = tmp_path / "truncated.ply"
    ply.write_bytes(
        b"ply\nformat binary_little_endian 1.0\nelement vertex 2\n"
        b"property float x\nproperty float y\nproperty float z\nend_header\n" + b"\0" * 20
    )
    with pytest.raises(FormatError, match="truncated PLY binary"):
        list(iter_ply_chunks(ply, chunk_points=1))

    pcd_binary = tmp_path / "truncated.pcd"
    pcd_binary.write_bytes(
        b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\n"
        b"WIDTH 2\nHEIGHT 1\nPOINTS 2\nDATA binary\n" + b"\0" * 20
    )
    with pytest.raises(FormatError, match="truncated PCD binary"):
        list(iter_pcd_chunks(pcd_binary, chunk_points=1))

    ply_ascii = tmp_path / "mismatched.ply"
    ply_ascii.write_text(
        "ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\nproperty float y\n"
        "property float z\nend_header\n0 0 0\n",
        encoding="ascii",
    )
    with pytest.raises(FormatError, match="PLY vertex count mismatch"):
        list(iter_ply_chunks(ply_ascii, chunk_points=1))


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


def test_rcs_native_failure_is_preserved_when_converter_is_unavailable(monkeypatch, tmp_path: Path):
    path = tmp_path / "scan.rcs"
    path.write_bytes(b"ADOCT" + b"\x00" * 64)

    monkeypatch.setattr(
        "scan2bim.formats.rcs_native.native_available",
        lambda: {"dll_exists": True, "dll_path": "fake.dll"},
    )

    def fail_native(*args, **kwargs):
        raise RuntimeError("native RCS worker failed: synthetic fixture detail")

    monkeypatch.setattr("scan2bim.formats.rcs_native.read_rcs_native", fail_native)
    monkeypatch.setattr("scan2bim.formats.rcs.convert_rcs", lambda *args, **kwargs: None)

    with pytest.raises(RcsConversionRequired, match="native RCS worker failed: synthetic fixture detail"):
        read_cloud(path)


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
