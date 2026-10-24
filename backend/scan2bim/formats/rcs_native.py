"""Native RCS reading through the ReCap DLL that is already installed locally.

Autodesk documents no RCS export API and the open-source ecosystem has no RCS
reader. What DOES exist on a machine where ReCap is installed is
``AdskRcExport.dll``, which exports the MSVC-mangled reader class::

    Autodesk::RealityComputing::Export::RCRcsDataSource
        RCRcsDataSource(std::wstring const&, bool)
        bool open()
        bool advancePoint()
        void getPosition(RCVector3<double>&) const
        void getColor(RCVector4<unsigned char>&) const
        size_t getPointCt() const
        bool close()

Verified on this machine (2026-10-20): the 7,196,593,757-byte ``1.rcs``
(ADOCT octree v3) opened and streamed 297,873,927 points at up to
~1.2M pts/s (advance) / ~254k pts/s (position+colour), with real RGB.

HONESTY RULES
-------------
* This is UNDOCUMENTED, Autodesk-internal ABI. It is used read-only, on the
  machine where the user's own ReCap installation lives; the source file is
  never opened for writing and never modified.
* Do not describe the product as "natively supporting RCS". The accurate
  wording is "read through the installed Autodesk ReCap library".
* ``getPointCt()`` returns INT32_MAX as a sentinel on this build, so the total
  point count is unknown up front and no honest progress percentage exists.
* The class is stateful C++ whose ABI we cannot fully verify, so every ctypes
  call happens in a SEPARATE PROCESS: a crash there can never take the API
  server down with it.

Sampling
--------
The iterator walks the octree in depth order, so "the first N points" is a
spatially clustered subset (measured: the first 20k points spanned
x[-83.7,-73.3] while the whole file spans x[-84,-46.9]). We therefore do one
full pass with Algorithm-R reservoir sampling so the retained sample is uniform
over the entire scan. Keep-decisions are computed vectorised per chunk before
any point is touched, so getPosition/getColor run only for survivors.

Protocol: parent runs ``python -m scan2bim.formats.rcs_native <rcs> <out_dir>
--max N`` for a uniform reservoir sample, writing ``xyz.npy`` (float32 Nx3)
and ``rgb.npy`` (uint8 Nx3). In full-resolution mode, ``--all`` writes every
point sequentially to ``xyz.f64`` and ``rgb.u8`` in bounded chunks. The child
prints::

    PROGRESS 0 <seen> read (<rate> pts/s, <kept> kept)
    DONE <kept> SEEN <seen>
    ERROR <message>
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..config import MAX_INGEST_POINTS

RECAP_DIR = Path(
    os.environ.get("S2B_RECAP_DIR", r"C:\Program Files\Autodesk\Autodesk ReCap")
)
DLL_NAME = "AdskRcExport.dll"

# MSVC-mangled exports, verified present in the installed AdskRcExport.dll.
M_CTOR = r"??0RCRcsDataSource@Export@RealityComputing@Autodesk@@QEAA@AEBV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@_N@Z"
M_DTOR = r"??1RCRcsDataSource@Export@RealityComputing@Autodesk@@UEAA@XZ"
M_OPEN = r"?open@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEAA_NXZ"
M_ADV = r"?advancePoint@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEAA_NXZ"
M_POS = r"?getPosition@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEBAXAEAU?$RCVector3T@N@Common@34@@Z"
M_COLOR = r"?getColor@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEBAXAEAU?$RCVector4T@E@Common@34@@Z"
M_CLOSE = r"?close@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEAA_NXZ"

CHUNK = 250_000
RNG_SEED = 20261020
MIN_FREE_DISK_BYTES = int(os.environ.get("S2B_INGEST_DISK_RESERVE_BYTES", str(1024**3)))
STREAM_CHECKPOINT_VERSION = 2


def _stream_source_identity(path: Path, source_sha256: str | None = None) -> dict[str, Any]:
    stat = path.stat()
    if source_sha256 is None:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while block := source.read(8 * 1024 * 1024):
                digest.update(block)
        source_sha256 = digest.hexdigest()
    return {
        "path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": source_sha256,
    }


def _write_stream_checkpoint(
    out_dir: Path,
    source_identity: dict[str, Any],
    committed_count: int,
    blocks: list[dict[str, Any]],
    *,
    complete: bool,
) -> None:
    checkpoint = {
        "version": STREAM_CHECKPOINT_VERSION,
        "source_identity": source_identity,
        "committed_count": committed_count,
        "chunk_size": CHUNK,
        "blocks": blocks,
        "complete": complete,
    }
    temporary = out_dir / "stream.json.tmp"
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(checkpoint, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    # Windows scanners and indexers can briefly hold the destination open. Keep
    # the last committed checkpoint intact and retry the atomic swap before
    # failing the whole (potentially multi-hour) native extraction.
    destination = out_dir / "stream.json"
    for attempt in range(5):
        try:
            os.replace(temporary, destination)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1 * (attempt + 1))


def _read_stream_checkpoint(out_dir: Path, source_identity: dict[str, Any]) -> dict[str, Any] | None:
    path = out_dir / "stream.json"
    if not path.exists():
        return None
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"RCS stream checkpoint is unreadable: {exc}") from exc
    if not isinstance(checkpoint, dict):
        raise RuntimeError("RCS stream checkpoint root must be a JSON object")
    if checkpoint.get("version") != STREAM_CHECKPOINT_VERSION:
        raise RuntimeError("RCS stream checkpoint version is unsupported")
    if checkpoint.get("source_identity") != source_identity:
        raise RuntimeError("RCS source identity changed; refusing to resume its stream checkpoint")
    committed = checkpoint.get("committed_count")
    if not isinstance(committed, int) or committed < 0:
        raise RuntimeError("RCS stream checkpoint has an invalid committed point count")
    chunk_size = checkpoint.get("chunk_size")
    blocks = checkpoint.get("blocks")
    if not isinstance(chunk_size, int) or chunk_size <= 0 or not isinstance(blocks, list):
        raise RuntimeError("RCS stream checkpoint has invalid block metadata")
    block_points = 0
    for block in blocks:
        if (
            not isinstance(block, dict)
            or not isinstance(block.get("points"), int)
            or block["points"] <= 0
            or block["points"] > chunk_size
            or not isinstance(block.get("xyz_sha256"), str)
            or not isinstance(block.get("rgb_sha256"), str)
        ):
            raise RuntimeError("RCS stream checkpoint contains a corrupt block record")
        block_points += block["points"]
    if block_points != committed:
        raise RuntimeError("RCS stream checkpoint block records do not match its point count")
    if not isinstance(checkpoint.get("complete"), bool):
        raise RuntimeError("RCS stream checkpoint has an invalid completion flag")
    return checkpoint


def _verify_stream_files(out_dir: Path, checkpoint: dict[str, Any], *, exact_size: bool) -> None:
    count = int(checkpoint["committed_count"])
    xyz_path = out_dir / "xyz.f64"
    rgb_path = out_dir / "rgb.u8"
    expected_xyz = count * 3 * np.dtype("<f8").itemsize
    expected_rgb = count * 3 * np.dtype("u1").itemsize
    if not xyz_path.is_file() or not rgb_path.is_file():
        raise RuntimeError("RCS stream checkpoint is missing its raw data files")
    xyz_size = xyz_path.stat().st_size
    rgb_size = rgb_path.stat().st_size
    if xyz_size < expected_xyz or rgb_size < expected_rgb:
        raise RuntimeError("RCS raw stream is shorter than its committed checkpoint")
    if exact_size and (xyz_size != expected_xyz or rgb_size != expected_rgb):
        raise RuntimeError("completed RCS stream checkpoint has invalid raw file sizes")
    with xyz_path.open("rb") as xyz_file, rgb_path.open("rb") as rgb_file:
        for block in checkpoint["blocks"]:
            points = block["points"]
            xyz_bytes = xyz_file.read(points * 3 * np.dtype("<f8").itemsize)
            rgb_bytes = rgb_file.read(points * 3 * np.dtype("u1").itemsize)
            if hashlib.sha256(xyz_bytes).hexdigest() != block["xyz_sha256"]:
                raise RuntimeError("RCS coordinate stream block checksum does not match checkpoint")
            if hashlib.sha256(rgb_bytes).hexdigest() != block["rgb_sha256"]:
                raise RuntimeError("RCS color stream block checksum does not match checkpoint")


def _prepare_stream_files(out_dir: Path, checkpoint: dict[str, Any] | None) -> tuple[Any, Any, int]:
    xyz_path = out_dir / "xyz.f64"
    rgb_path = out_dir / "rgb.u8"
    committed = int(checkpoint["committed_count"]) if checkpoint else 0
    expected_xyz = committed * 3 * np.dtype("<f8").itemsize
    expected_rgb = committed * 3 * np.dtype("u1").itemsize
    if checkpoint is None:
        xyz_out = xyz_path.open("w+b")
        rgb_out = rgb_path.open("w+b")
    else:
        _verify_stream_files(out_dir, checkpoint, exact_size=False)
        xyz_out = xyz_path.open("r+b")
        rgb_out = rgb_path.open("r+b")
        xyz_out.truncate(expected_xyz)
        rgb_out.truncate(expected_rgb)
    xyz_out.seek(expected_xyz)
    rgb_out.seek(expected_rgb)
    return xyz_out, rgb_out, committed


def native_available() -> dict[str, Any]:
    """Whether the local ReCap DLL path can be attempted at all."""
    dll = RECAP_DIR / DLL_NAME
    return {
        "dll_exists": dll.exists(),
        "dll_path": str(dll),
        "recap_dir": str(RECAP_DIR),
        "abi": "undocumented Autodesk internal (RCRcsDataSource), subprocess-isolated",
        "verified_file": "1.rcs (ADOCT v3, 7.2 GB, 297,873,927 points, 2026-10-20)",
    }


# --------------------------------------------------------------------------- child


class _WStr(ctypes.Structure):
    """MSVC std::wstring on x64: 16-byte union + size + capacity (32 bytes)."""

    _fields_ = [
        ("ptr_or_buf0", ctypes.c_uint64),
        ("buf1", ctypes.c_uint64),
        ("size", ctypes.c_uint64),
        ("cap", ctypes.c_uint64),
    ]


def _resolve(handle: int, mangled: str, nargs: int):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    kernel32.GetProcAddress.restype = ctypes.c_void_p
    addr = kernel32.GetProcAddress(ctypes.c_void_p(handle), mangled.encode("ascii"))
    if not addr:
        raise RuntimeError(f"export not found: {mangled[:60]}")
    # x64 Windows: one calling convention, this-pointer in RCX.
    return ctypes.CFUNCTYPE(ctypes.c_uint64, *([ctypes.c_uint64] * nargs))(addr)


def _stream(
    rcs_path: Path,
    out_dir: Path,
    max_points: int,
    stream_all: bool = False,
    source_sha256: str | None = None,
) -> int:
    """Read RCS in bounded chunks; optionally stream every point to raw files."""
    if max_points <= 0 and not stream_all:
        max_points = MAX_INGEST_POINTS
    if max_points <= 0 and not stream_all:
        raise RuntimeError("reservoir sampling needs a positive point budget")

    source_identity = (
        _stream_source_identity(rcs_path, source_sha256=source_sha256) if stream_all else None
    )
    checkpoint = None
    committed = 0
    if stream_all:
        out_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = _read_stream_checkpoint(out_dir, source_identity)
        if checkpoint and checkpoint["complete"]:
            count = int(checkpoint["committed_count"])
            _verify_stream_files(out_dir, checkpoint, exact_size=True)
            xyz_path = out_dir / "xyz.f64"
            rgb_path = out_dir / "rgb.u8"
            if (
                count > 0
            ):
                print(f"PROGRESS 0 {count:,} read ({count:,} kept)", flush=True)
                print(f"DONE {count} SEEN {count} MODE all", flush=True)
                return count
            raise RuntimeError("completed RCS stream checkpoint has invalid raw file sizes")

    dll = RECAP_DIR / DLL_NAME
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(RECAP_DIR))
    os.environ["PATH"] = str(RECAP_DIR) + os.pathsep + os.environ.get("PATH", "")
    lib = ctypes.CDLL(str(dll))
    h = lib._handle

    ctor = _resolve(h, M_CTOR, 3)
    dtor = _resolve(h, M_DTOR, 1)
    opn = _resolve(h, M_OPEN, 1)
    adv = _resolve(h, M_ADV, 1)
    pos = _resolve(h, M_POS, 2)
    color = _resolve(h, M_COLOR, 2)
    close = _resolve(h, M_CLOSE, 1)

    this_buf = ctypes.create_string_buffer(8192)  # generous object storage
    this_ptr = ctypes.addressof(this_buf)

    abs_path = str(rcs_path.resolve())
    utf16 = abs_path.encode("utf-16-le") + b"\x00\x00"
    path_buf = ctypes.create_string_buffer(utf16, len(utf16) + 256)
    ws = _WStr()
    ws.ptr_or_buf0 = ctypes.addressof(path_buf)  # heap mode: path > SSO capacity
    ws.size = len(abs_path)  # code POINTS of the absolute path, not bytes
    ws.cap = 4096
    ws_buf = ctypes.create_string_buffer(bytes(ws), 64)

    ctor(this_ptr, ctypes.addressof(ws_buf), 1)
    if not opn(this_ptr):
        ctor(this_ptr, ctypes.addressof(ws_buf), 0)
        if not opn(this_ptr):
            dtor(this_ptr)
            raise RuntimeError("RCRcsDataSource::open() failed for both ctor flags")

    rng = np.random.default_rng(RNG_SEED)
    if stream_all:
        xyz_out, rgb_out, committed = _prepare_stream_files(out_dir, checkpoint)
        blocks = list(checkpoint["blocks"]) if checkpoint else []
        keep_xyz = np.empty((CHUNK, 3), dtype=np.float64)
        keep_rgb = np.empty((CHUNK, 3), dtype=np.uint8)
        if checkpoint is None:
            _write_stream_checkpoint(out_dir, source_identity, 0, blocks, complete=False)
    else:
        xyz_out = rgb_out = None
        keep_xyz = np.empty((max_points, 3), dtype=np.float32)
        keep_rgb = np.empty((max_points, 3), dtype=np.uint8)
    kept = 0
    seen = committed
    slot = (ctypes.c_double * 3)()
    cs = (ctypes.c_ubyte * 4)()
    t0 = time.monotonic()

    try:
        skip = committed
        while skip:
            advanced = 0
            for _ in range(min(CHUNK, skip)):
                if not adv(this_ptr):
                    raise RuntimeError(
                        "RCS source ended before its committed stream checkpoint; refusing to append"
                    )
                advanced += 1
            skip -= advanced
            rate = advanced / max(time.monotonic() - t0, 1e-6)
            print(f"PROGRESS 0 {committed - skip:,} resumed ({rate:,.0f} pts/s)", flush=True)

        while True:
            # Decide the whole chunk's fate before touching a single point.
            idx = np.arange(seen, seen + CHUNK, dtype=np.int64)
            if stream_all:
                slots = np.arange(CHUNK, dtype=np.int32)
            else:
                replace = rng.integers(0, idx + 1)
                slots = np.where(idx < max_points, idx, np.where(replace < max_points, replace, -1))

            n = 0
            for s in slots:
                if not adv(this_ptr):
                    break
                if stream_all:
                    pos(this_ptr, ctypes.addressof(slot))
                    keep_xyz[n, 0] = slot[0]
                    keep_xyz[n, 1] = slot[1]
                    keep_xyz[n, 2] = slot[2]
                    color(this_ptr, ctypes.addressof(cs))
                    keep_rgb[n, 0] = cs[0]
                    keep_rgb[n, 1] = cs[1]
                    keep_rgb[n, 2] = cs[2]
                elif s >= 0:
                    pos(this_ptr, ctypes.addressof(slot))
                    keep_xyz[s, 0] = slot[0]
                    keep_xyz[s, 1] = slot[1]
                    keep_xyz[s, 2] = slot[2]
                    color(this_ptr, ctypes.addressof(cs))
                    keep_rgb[s, 0] = cs[0]
                    keep_rgb[s, 1] = cs[1]
                n += 1

            if stream_all and n:
                if shutil.disk_usage(out_dir).free < MIN_FREE_DISK_BYTES:
                    raise RuntimeError(
                        f"full-resolution RCS import paused to preserve disk reserve "
                        f"({MIN_FREE_DISK_BYTES:,} bytes)"
                    )
                keep_xyz[:n].tofile(xyz_out)
                keep_rgb[:n].tofile(rgb_out)
                xyz_out.flush()
                rgb_out.flush()
                os.fsync(xyz_out.fileno())
                os.fsync(rgb_out.fileno())
                blocks.append(
                    {
                        "points": n,
                        "xyz_sha256": hashlib.sha256(memoryview(keep_xyz[:n]).cast("B")).hexdigest(),
                        "rgb_sha256": hashlib.sha256(memoryview(keep_rgb[:n]).cast("B")).hexdigest(),
                    }
                )

            seen += n
            kept = seen if stream_all else min(seen, max_points)
            if stream_all:
                _write_stream_checkpoint(out_dir, source_identity, seen, blocks, complete=False)
            # The true total is unknown (sentinel count), so no honest fraction
            # exists: report absolute progress with the measured rate instead.
            if stream_all or seen % (CHUNK * 40) < CHUNK or n < CHUNK:
                rate = seen / max(time.monotonic() - t0, 1e-6)
                print(
                    f"PROGRESS 0 {seen:,} read ({rate:,.0f} pts/s, {kept:,} kept)",
                    flush=True,
                )
            if n < CHUNK:
                if stream_all:
                    _write_stream_checkpoint(out_dir, source_identity, seen, blocks, complete=seen > 0)
                break
    finally:
        try:
            close(this_ptr)
        finally:
            dtor(this_ptr)
            if xyz_out is not None:
                xyz_out.close()
            if rgb_out is not None:
                rgb_out.close()

    if kept == 0:
        raise RuntimeError("RCS iterator produced no points")

    out_dir.mkdir(parents=True, exist_ok=True)
    if stream_all:
        print(f"DONE {kept} SEEN {seen} MODE all", flush=True)
    else:
        np.save(out_dir / "xyz.npy", keep_xyz[:kept])
        np.save(out_dir / "rgb.npy", keep_rgb[:kept])
        print(f"DONE {kept} SEEN {seen}", flush=True)
    return kept


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="stream an RCS through the local ReCap DLL")
    ap.add_argument("rcs")
    ap.add_argument("out_dir")
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--all", action="store_true", help="write every point to bounded raw disk streams")
    ap.add_argument("--source-sha256", help="precomputed source digest for checkpoint identity")
    args = ap.parse_args(argv)
    try:
        _stream(
            Path(args.rcs),
            Path(args.out_dir),
            args.max,
            stream_all=args.all,
            source_sha256=args.source_sha256,
        )
    except Exception as exc:  # reported to the parent
        print(f"ERROR {exc}", flush=True)
        return 1
    return 0


# --------------------------------------------------------------------------- parent


def extract_rcs_native(path: Path, out_dir: Path, progress=None) -> dict[str, Any]:
    """Write all RCS points to bounded raw disk streams and return their layout."""
    from .readers import FormatError

    info = native_available()
    if not info["dll_exists"]:
        raise FormatError(f"ReCap DLL not found: {info['dll_path']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    source_identity = _stream_source_identity(path)
    checkpoint = _read_stream_checkpoint(out_dir, source_identity)
    if checkpoint and checkpoint["complete"]:
        count = int(checkpoint["committed_count"])
        _verify_stream_files(out_dir, checkpoint, exact_size=True)
        xyz_path = out_dir / "xyz.f64"
        rgb_path = out_dir / "rgb.u8"
        if count > 0:
            if progress:
                progress(0.55, f"RCS points already staged: {count:,}")
            return {
                "point_count": count,
                "xyz_path": xyz_path,
                "rgb_path": rgb_path,
                "reader": {
                    "reader": "recap-adskrcexport-dll",
                    "reader_abi": info["abi"],
                    "dll": info["dll_path"],
                    "native_rcs_verified": True,
                    "sampling": "none; full sequential RCS stream",
                },
            }
        raise FormatError("completed RCS stream checkpoint has invalid raw file sizes")
    cmd = [
        sys.executable,
        "-m",
        "scan2bim.formats.rcs_native",
        str(path),
        str(out_dir),
        "--all",
        "--source-sha256",
        source_identity["sha256"],
    ]
    env = dict(os.environ)
    pkg_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert proc.stdout is not None
    last = ""
    count = 0
    stray: list[str] = []
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            if line.startswith("PROGRESS "):
                last = line
                if progress:
                    parts = line.split(" ", 3)
                    progress(0.05, "RCS: " + (parts[2] if len(parts) > 2 else line))
            elif line.startswith("DONE"):
                last = line
                bits = line.split()
                if "SEEN" in bits:
                    count = int(bits[bits.index("SEEN") + 1])
            elif line.startswith("ERROR"):
                last = line
            else:
                stray.append(line)
                stray = stray[-12:]
        try:
            code = proc.wait(timeout=60 * 60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise FormatError("native RCS full-resolution read timed out after 60 minutes")
    except BaseException:
        if proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        raise

    xyz_path = out_dir / "xyz.f64"
    rgb_path = out_dir / "rgb.u8"
    if code != 0 or count <= 0 or not xyz_path.is_file() or not rgb_path.is_file():
        detail = last or (" | ".join(stray[-4:]) if stray else f"exit {code}")
        raise FormatError(f"native RCS full-resolution stream failed: {detail}")
    checkpoint = _read_stream_checkpoint(out_dir, source_identity)
    if not checkpoint or not checkpoint["complete"]:
        raise FormatError("native RCS child exited without completing its durable stream checkpoint")
    if checkpoint["committed_count"] != count:
        raise FormatError("native RCS stream count differs from its durable checkpoint")
    if xyz_path.stat().st_size != count * 3 * np.dtype("<f8").itemsize:
        raise FormatError("native RCS coordinate stream has an invalid byte count")
    if rgb_path.stat().st_size != count * 3 * np.dtype("u1").itemsize:
        raise FormatError("native RCS color stream has an invalid byte count")
    if progress:
        progress(0.55, f"RCS points staged: {count:,}")
    return {
        "point_count": count,
        "xyz_path": xyz_path,
        "rgb_path": rgb_path,
        "reader": {
            "reader": "recap-adskrcexport-dll",
            "reader_abi": info["abi"],
            "dll": info["dll_path"],
            "native_rcs_verified": True,
            "sampling": "none; full sequential RCS stream",
            "source_sha256": source_identity["sha256"],
        },
    }


def read_rcs_native(path: Path, max_points: int, progress=None):
    """Run the isolated child and return a RawCloud (xyz float64, rgb uint8)."""
    from .readers import FormatError, RawCloud

    info = native_available()
    if not info["dll_exists"]:
        raise FormatError(f"ReCap DLL not found: {info['dll_path']}")

    with tempfile.TemporaryDirectory(prefix="s2b_rcs_") as tmp:
        out_dir = Path(tmp)
        cmd = [
            sys.executable,
            "-m",
            "scan2bim.formats.rcs_native",
            str(path),
            str(out_dir),
            "--max",
            str(max_points or MAX_INGEST_POINTS),
        ]
        env = dict(os.environ)
        # rcs_native.py lives at backend/scan2bim/formats/rcs_native.py, so the
        # package root is parents[2].
        pkg_root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert proc.stdout is not None
        last = ""
        stray: list[str] = []
        seen_total = 0
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("PROGRESS "):
                    parts = line.split(" ", 3)
                    if progress:
                        try:
                            progress(float(parts[1]), f"streaming RCS: {parts[2]}")
                        except (IndexError, ValueError):
                            pass
                    last = line
                elif line.startswith("DONE"):
                    last = line
                    bits = line.split()
                    if "SEEN" in bits:
                        try:
                            seen_total = int(bits[bits.index("SEEN") + 1])
                        except (ValueError, IndexError):
                            seen_total = 0
                elif line.startswith("ERROR"):
                    last = line
                else:
                    stray.append(line)
                    stray = stray[-12:]
            try:
                code = proc.wait(timeout=60 * 60)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise FormatError("native RCS read timed out after 60 minutes")
        except BaseException:
            # A progress callback can cancel the job while this child is
            # streaming. Stop it before TemporaryDirectory removes its output.
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            raise
        xyz_path = out_dir / "xyz.npy"
        if code != 0 or not xyz_path.exists():
            detail = last or (" | ".join(stray[-4:]) if stray else f"exit {code}")
            raise FormatError(f"native RCS read failed: {detail}")

        xyz = np.load(xyz_path)
        rgb = np.load(out_dir / "rgb.npy")

    if progress:
        progress(0.85, f"RCS stream complete: {len(xyz):,} points kept")
    return RawCloud(
        xyz=np.asarray(xyz, dtype=np.float64),
        rgb=np.asarray(rgb, dtype=np.uint8),
        metadata={
            "reader": "recap-adskrcexport-dll",
            "reader_abi": info["abi"],
            "dll": info["dll_path"],
            "native_rcs_verified": True,
            "source_point_count": seen_total or None,
            "sampling": "uniform reservoir over one full octree pass",
            "rng_seed": RNG_SEED,
        },
    )


if __name__ == "__main__":
    sys.exit(main())
