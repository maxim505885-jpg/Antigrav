from __future__ import annotations

import io
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from scan2bim import ingest
from scan2bim.formats import rcs_native
from scan2bim.db import execute, new_id, one, utcnow
from scan2bim.storage import cloud_paths


def _block_record(xyz: np.ndarray, rgb: np.ndarray) -> dict[str, object]:
    return {
        "points": len(xyz),
        "xyz_sha256": hashlib.sha256(np.ascontiguousarray(xyz, dtype="<f8").tobytes()).hexdigest(),
        "rgb_sha256": hashlib.sha256(np.ascontiguousarray(rgb, dtype="u1").tobytes()).hexdigest(),
    }


@pytest.mark.parametrize("replace_source_during_read", [False, True])
def test_unlimited_rcs_ingest_uses_disk_stream_and_preserves_all_points(
    client, tmp_path, monkeypatch, replace_source_during_read
):
    monkeypatch.setattr(ingest, "MIN_INGEST_DISK_RESERVE_BYTES", 0)
    monkeypatch.setattr(rcs_native, "MIN_FREE_DISK_BYTES", 0)
    source = tmp_path / "synthetic-faro.rcs"
    source.write_bytes(b"synthetic RCS marker; the proprietary reader is replaced in this test")
    project = client.post("/api/v1/projects", json={"name": "streamed RCS"}).json()
    cloud_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds
        (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (cloud_id, project["id"], source.name, str(source), "rcs", source.stat().st_size, "processing", now, now),
    )
    xyz = np.array(
        [[100.0 + i, 200.0 - i * 0.5, 3.0 + i * 2.0] for i in range(7)],
        dtype=np.float64,
    )
    rgb = np.array([[i, 20 + i, 200 - i] for i in range(7)], dtype=np.uint8)
    original_source_sha256 = rcs_native._stream_source_identity(source)["sha256"]
    monkeypatch.setattr(ingest, "MAX_INGEST_POINTS", 0)
    stage_dir = cloud_paths(project["id"], cloud_id)["dir"] / ".ingest-stage"
    raw_dir = stage_dir / "raw"
    raw_dir.mkdir(parents=True)
    partial_xyz = np.array([[10.0, 20.0, 30.0]], dtype="<f8")
    partial_rgb = np.array([[1, 2, 3]], dtype="u1")
    partial_xyz.tofile(raw_dir / "xyz.f64")
    partial_rgb.tofile(raw_dir / "rgb.u8")
    (raw_dir / "stream.json").write_text(
        json.dumps(
            {
                "version": rcs_native.STREAM_CHECKPOINT_VERSION,
                "source_identity": rcs_native._stream_source_identity(source),
                "committed_count": 1,
                "chunk_size": 3,
                "complete": False,
            }
        ),
        encoding="utf-8",
    )

    def write_synthetic_raw_stream(_source, out_dir: Path, progress=None):
        assert (out_dir / "stream.json").is_file()
        np.testing.assert_array_equal(
            np.fromfile(out_dir / "xyz.f64", dtype="<f8").reshape(-1, 3), partial_xyz
        )
        np.testing.assert_array_equal(
            np.fromfile(out_dir / "rgb.u8", dtype="u1").reshape(-1, 3), partial_rgb
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        xyz_path = out_dir / "xyz.f64"
        rgb_path = out_dir / "rgb.u8"
        xyz.tofile(xyz_path)
        rgb.tofile(rgb_path)
        if replace_source_during_read:
            source_stat = source.stat()
            source.write_bytes(b"X" * source_stat.st_size)
            os.utime(source, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
        return {
            "point_count": len(xyz),
            "xyz_path": xyz_path,
            "rgb_path": rgb_path,
            "reader": {
                "reader": "synthetic-stream",
                "reader_abi": "test",
                "source_sha256": original_source_sha256,
            },
        }

    monkeypatch.setattr(ingest, "extract_rcs_native", write_synthetic_raw_stream)
    monkeypatch.setattr(ingest, "native_available", lambda: {"dll_exists": True})
    monkeypatch.setattr(ingest, "read_cloud", lambda *_args, **_kwargs: pytest.fail("whole-cloud reader used"))

    if replace_source_during_read:
        with pytest.raises(RuntimeError, match="source content changed"):
            ingest.ingest_cloud(project["id"], cloud_id, source)
        assert not (stage_dir / "raw").exists()
        return

    result = ingest.ingest_cloud(project["id"], cloud_id, source)

    paths = cloud_paths(project["id"], cloud_id)
    origin = (xyz.min(axis=0) + xyz.max(axis=0)) / 2
    np.testing.assert_allclose(np.load(paths["positions"]), (xyz - origin).astype(np.float32))
    np.testing.assert_array_equal(np.load(paths["colors"]), rgb)
    assert result["ingested_count"] == len(xyz)
    assert result["decimated"] is False
    assert one("SELECT ingested_count FROM clouds WHERE id = ?", (cloud_id,))["ingested_count"] == len(xyz)
    assert one("SELECT status FROM clouds WHERE id = ?", (cloud_id,))["status"] == "ready"
    assert not (paths["dir"] / ".ingest-stage").exists()


def test_native_rcs_child_writes_every_point_in_bounded_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(rcs_native, "MIN_FREE_DISK_BYTES", 0)
    source = tmp_path / "synthetic.rcs"
    source.write_bytes(b"synthetic")
    out_dir = tmp_path / "raw"
    xyz_expected = np.array([[i + 0.25, -i * 2.0, i * 3.0] for i in range(8)], dtype=np.float64)
    rgb_expected = np.array([[i, 100 + i, 200 + i] for i in range(8)], dtype=np.uint8)
    state = {"index": 0}

    def advance(_this):
        if state["index"] >= len(xyz_expected):
            return 0
        state["index"] += 1
        return 1

    def write_position(_this, address):
        index = state["index"] - 1
        target = (rcs_native.ctypes.c_double * 3).from_address(address)
        for axis, value in enumerate(xyz_expected[index]):
            target[axis] = value

    def write_color(_this, address):
        index = state["index"] - 1
        target = (rcs_native.ctypes.c_ubyte * 4).from_address(address)
        for channel, value in enumerate(rgb_expected[index]):
            target[channel] = value
        target[3] = 255

    implementations = {
        rcs_native.M_CTOR: lambda *_args: 1,
        rcs_native.M_DTOR: lambda *_args: 1,
        rcs_native.M_OPEN: lambda *_args: 1,
        rcs_native.M_ADV: advance,
        rcs_native.M_POS: write_position,
        rcs_native.M_COLOR: write_color,
        rcs_native.M_CLOSE: lambda *_args: 1,
    }
    monkeypatch.setattr(rcs_native, "RECAP_DIR", tmp_path)
    monkeypatch.setattr(rcs_native.os, "add_dll_directory", lambda *_args: None, raising=False)
    monkeypatch.setattr(rcs_native.ctypes, "CDLL", lambda *_args: type("Lib", (), {"_handle": 1})())
    monkeypatch.setattr(rcs_native, "_resolve", lambda _handle, symbol, _nargs: implementations[symbol])
    monkeypatch.setattr(rcs_native, "CHUNK", 3)
    allocations: list[int] = []
    real_empty = np.empty

    def bounded_empty(shape, *args, **kwargs):
        array = real_empty(shape, *args, **kwargs)
        allocations.append(array.size)
        return array

    monkeypatch.setattr(rcs_native.np, "empty", bounded_empty)

    kept = rcs_native._stream(source, out_dir, max_points=0, stream_all=True)

    assert kept == len(xyz_expected)
    assert max(allocations) <= rcs_native.CHUNK * 3
    xyz = np.memmap(out_dir / "xyz.f64", mode="r", dtype="<f8", shape=(kept, 3))
    rgb = np.memmap(out_dir / "rgb.u8", mode="r", dtype="u1", shape=(kept, 3))
    np.testing.assert_array_equal(xyz, xyz_expected)
    np.testing.assert_array_equal(rgb, rgb_expected)
    xyz._mmap.close()
    rgb._mmap.close()


def test_native_rcs_parent_requires_all_stream_and_validates_raw_file_sizes(tmp_path, monkeypatch):
    source = tmp_path / "synthetic.rcs"
    source.write_bytes(b"synthetic")
    xyz = np.arange(18, dtype="<f8").reshape(6, 3)
    rgb = np.arange(18, dtype="u1").reshape(6, 3)
    calls: list[list[str]] = []

    class FinishedProcess:
        stdout = io.StringIO("PROGRESS 0 6 read\nDONE 6 SEEN 6 MODE all\n")

        def __init__(self, command, **_kwargs):
            calls.append(command)
            out_dir = Path(command[4])
            out_dir.mkdir(parents=True, exist_ok=True)
            xyz.tofile(out_dir / "xyz.f64")
            rgb.tofile(out_dir / "rgb.u8")
            (out_dir / "stream.json").write_text(
                json.dumps(
                    {
                        "version": rcs_native.STREAM_CHECKPOINT_VERSION,
                        "source_identity": rcs_native._stream_source_identity(source),
                        "committed_count": len(xyz),
                        "chunk_size": rcs_native.CHUNK,
                        "blocks": [_block_record(xyz, rgb)],
                        "complete": True,
                    }
                ),
                encoding="utf-8",
            )

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(rcs_native, "native_available", lambda: {"dll_exists": True, "abi": "test", "dll_path": "fake.dll"})
    monkeypatch.setattr(rcs_native.subprocess, "Popen", FinishedProcess)

    stream = rcs_native.extract_rcs_native(source, tmp_path / "out")

    assert "--all" in calls[0]
    assert stream["point_count"] == 6
    assert stream["xyz_path"].stat().st_size == 6 * 3 * 8
    assert stream["rgb_path"].stat().st_size == 6 * 3


def test_native_rcs_parent_reuses_complete_checkpoint_without_starting_child(tmp_path, monkeypatch):
    source = tmp_path / "synthetic-complete.rcs"
    source.write_bytes(b"synthetic")
    out_dir = tmp_path / "complete-raw"
    out_dir.mkdir()
    xyz = np.arange(12, dtype="<f8").reshape(4, 3)
    rgb = np.arange(12, dtype="u1").reshape(4, 3)
    xyz.tofile(out_dir / "xyz.f64")
    rgb.tofile(out_dir / "rgb.u8")
    (out_dir / "stream.json").write_text(
        json.dumps(
            {
                "version": rcs_native.STREAM_CHECKPOINT_VERSION,
                "source_identity": rcs_native._stream_source_identity(source),
                "committed_count": 4,
                "chunk_size": rcs_native.CHUNK,
                "blocks": [_block_record(xyz, rgb)],
                "complete": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rcs_native, "native_available", lambda: {"dll_exists": True, "abi": "test", "dll_path": "fake.dll"})
    monkeypatch.setattr(
        rcs_native.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("complete raw stream should be reused"),
    )

    stream = rcs_native.extract_rcs_native(source, out_dir)

    assert stream["point_count"] == 4
    assert stream["xyz_path"].stat().st_size == 4 * 3 * 8
    assert stream["rgb_path"].stat().st_size == 4 * 3
    with (out_dir / "xyz.f64").open("r+b") as handle:
        handle.write(b"corrupt!")
    with pytest.raises(RuntimeError, match="coordinate stream block checksum"):
        rcs_native.extract_rcs_native(source, out_dir)


def test_native_rcs_stream_checkpoint_rejects_corrupt_json_root(tmp_path):
    source = tmp_path / "synthetic-corrupt.rcs"
    source.write_bytes(b"synthetic")
    out_dir = tmp_path / "corrupt-raw"
    out_dir.mkdir()
    (out_dir / "stream.json").write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="root must be a JSON object"):
        rcs_native._read_stream_checkpoint(out_dir, rcs_native._stream_source_identity(source))


def test_native_rcs_stream_resume_rejects_changed_source_identity(tmp_path):
    source = tmp_path / "synthetic-changed.rcs"
    source.write_bytes(b"original")
    out_dir = tmp_path / "changed-raw"
    out_dir.mkdir()
    checkpoint = {
        "version": rcs_native.STREAM_CHECKPOINT_VERSION,
        "source_identity": rcs_native._stream_source_identity(source),
        "committed_count": 0,
        "chunk_size": rcs_native.CHUNK,
        "blocks": [],
        "complete": False,
    }
    (out_dir / "stream.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    source.write_bytes(b"replacement with another size")

    with pytest.raises(RuntimeError, match="source identity changed"):
        rcs_native._read_stream_checkpoint(out_dir, rcs_native._stream_source_identity(source))


def test_native_rcs_source_identity_detects_same_size_same_mtime_replacement(tmp_path):
    source = tmp_path / "synthetic-same-metadata.rcs"
    source.write_bytes(b"original content")
    before_stat = source.stat()
    before = rcs_native._stream_source_identity(source)
    source.write_bytes(b"replaced content")
    os.utime(source, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))

    after = rcs_native._stream_source_identity(source)

    assert before["size_bytes"] == after["size_bytes"]
    assert before["mtime_ns"] == after["mtime_ns"]
    assert before != after


def test_native_rcs_stream_resumes_after_last_committed_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(rcs_native, "MIN_FREE_DISK_BYTES", 0)
    source = tmp_path / "synthetic-resumable.rcs"
    source.write_bytes(b"synthetic")
    out_dir = tmp_path / "resumable-raw"
    expected_xyz = np.array([[i, i + 0.5, -i] for i in range(8)], dtype=np.float64)
    expected_rgb = np.array([[i, i + 10, i + 20] for i in range(8)], dtype=np.uint8)
    state = {"index": 0, "interrupt": True}

    def advance(_this):
        if state["index"] >= len(expected_xyz):
            return 0
        state["index"] += 1
        return 1

    def write_position(_this, address):
        index = state["index"] - 1
        if state["interrupt"] and index == 4:
            raise RuntimeError("simulated process failure mid-chunk")
        target = (rcs_native.ctypes.c_double * 3).from_address(address)
        for axis, value in enumerate(expected_xyz[index]):
            target[axis] = value

    def write_color(_this, address):
        index = state["index"] - 1
        target = (rcs_native.ctypes.c_ubyte * 4).from_address(address)
        for channel, value in enumerate(expected_rgb[index]):
            target[channel] = value

    implementations = {
        rcs_native.M_CTOR: lambda *_args: 1,
        rcs_native.M_DTOR: lambda *_args: 1,
        rcs_native.M_OPEN: lambda *_args: 1,
        rcs_native.M_ADV: advance,
        rcs_native.M_POS: write_position,
        rcs_native.M_COLOR: write_color,
        rcs_native.M_CLOSE: lambda *_args: 1,
    }
    monkeypatch.setattr(rcs_native, "RECAP_DIR", tmp_path)
    monkeypatch.setattr(rcs_native.os, "add_dll_directory", lambda *_args: None, raising=False)
    monkeypatch.setattr(rcs_native.ctypes, "CDLL", lambda *_args: type("Lib", (), {"_handle": 1})())
    monkeypatch.setattr(rcs_native, "_resolve", lambda _handle, symbol, _nargs: implementations[symbol])
    monkeypatch.setattr(rcs_native, "CHUNK", 3)

    with pytest.raises(RuntimeError, match="simulated process failure"):
        rcs_native._stream(source, out_dir, max_points=0, stream_all=True)

    checkpoint = out_dir / "stream.json"
    assert checkpoint.exists()
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["committed_count"] == 3
    assert saved["complete"] is False
    assert (out_dir / "xyz.f64").stat().st_size == 3 * 3 * 8
    assert (out_dir / "rgb.u8").stat().st_size == 3 * 3
    # Simulate a crash after a later block reached the data files but before
    # the atomic manifest replacement acknowledged that block.
    with (out_dir / "xyz.f64").open("ab") as handle:
        handle.write(np.full(3, -99, dtype="<f8").tobytes())
    with (out_dir / "rgb.u8").open("ab") as handle:
        handle.write(bytes([255, 255, 255]))
    state["index"] = 0
    state["interrupt"] = False
    kept = rcs_native._stream(source, out_dir, max_points=0, stream_all=True)

    assert kept == len(expected_xyz)
    xyz = np.memmap(out_dir / "xyz.f64", mode="r", dtype="<f8", shape=(kept, 3))
    rgb = np.memmap(out_dir / "rgb.u8", mode="r", dtype="u1", shape=(kept, 3))
    np.testing.assert_array_equal(xyz, expected_xyz)
    np.testing.assert_array_equal(rgb, expected_rgb)
    xyz._mmap.close()
    rgb._mmap.close()


def test_native_rcs_stream_pauses_at_disk_reserve_and_resumes(tmp_path, monkeypatch):
    source = tmp_path / "synthetic-low-disk.rcs"
    source.write_bytes(b"synthetic")
    out_dir = tmp_path / "low-disk-raw"
    expected_xyz = np.array([[i + 0.25, i + 0.5, -i] for i in range(4)], dtype=np.float64)
    expected_rgb = np.array([[i, i + 10, i + 20] for i in range(4)], dtype=np.uint8)
    state = {"index": 0, "disk_checks": 0}

    def advance(_this):
        if state["index"] >= len(expected_xyz):
            return 0
        state["index"] += 1
        return 1

    def write_position(_this, address):
        index = state["index"] - 1
        target = (rcs_native.ctypes.c_double * 3).from_address(address)
        for axis, value in enumerate(expected_xyz[index]):
            target[axis] = value

    def write_color(_this, address):
        index = state["index"] - 1
        target = (rcs_native.ctypes.c_ubyte * 4).from_address(address)
        for channel, value in enumerate(expected_rgb[index]):
            target[channel] = value

    implementations = {
        rcs_native.M_CTOR: lambda *_args: 1,
        rcs_native.M_DTOR: lambda *_args: 1,
        rcs_native.M_OPEN: lambda *_args: 1,
        rcs_native.M_ADV: advance,
        rcs_native.M_POS: write_position,
        rcs_native.M_COLOR: write_color,
        rcs_native.M_CLOSE: lambda *_args: 1,
    }
    monkeypatch.setattr(rcs_native, "RECAP_DIR", tmp_path)
    monkeypatch.setattr(rcs_native.os, "add_dll_directory", lambda *_args: None, raising=False)
    monkeypatch.setattr(rcs_native.ctypes, "CDLL", lambda *_args: type("Lib", (), {"_handle": 1})())
    monkeypatch.setattr(rcs_native, "_resolve", lambda _handle, symbol, _nargs: implementations[symbol])
    monkeypatch.setattr(rcs_native, "CHUNK", 2)

    class Usage:
        def __init__(self, free):
            self.free = free

    def low_disk_after_one_block(_path):
        state["disk_checks"] += 1
        return Usage(10**12 if state["disk_checks"] == 1 else 0)

    monkeypatch.setattr(rcs_native.shutil, "disk_usage", low_disk_after_one_block)
    with pytest.raises(RuntimeError, match="preserve disk reserve"):
        rcs_native._stream(source, out_dir, max_points=0, stream_all=True)

    paused = json.loads((out_dir / "stream.json").read_text(encoding="utf-8"))
    assert paused["committed_count"] == 2
    np.testing.assert_array_equal(
        np.fromfile(out_dir / "xyz.f64", dtype="<f8").reshape(-1, 3), expected_xyz[:2]
    )
    np.testing.assert_array_equal(
        np.fromfile(out_dir / "rgb.u8", dtype="u1").reshape(-1, 3), expected_rgb[:2]
    )

    monkeypatch.setattr(rcs_native.shutil, "disk_usage", lambda _path: Usage(10**12))
    state["index"] = 0
    kept = rcs_native._stream(source, out_dir, max_points=0, stream_all=True)
    xyz = np.memmap(out_dir / "xyz.f64", mode="r", dtype="<f8", shape=(kept, 3))
    rgb = np.memmap(out_dir / "rgb.u8", mode="r", dtype="u1", shape=(kept, 3))
    np.testing.assert_array_equal(xyz, expected_xyz)
    np.testing.assert_array_equal(rgb, expected_rgb)
    xyz._mmap.close()
    rgb._mmap.close()
