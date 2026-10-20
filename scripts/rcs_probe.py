"""Probe the installed Autodesk AdskRcExport.dll for a usable RCS reader.

AdskRcExport.dll ships with Autodesk ReCap and exports the MSVC-mangled
RCRcsDataSource API:

    RCRcsDataSource(std::wstring const&, bool)
    bool open()
    bool advancePoint()
    void getPosition(RCVector3<double>&) const
    void getColor(RCVector4<unsigned char>&) const
    size_t getPointCt() const
    bool close()

This is an UNDOCUMENTED, Autodesk-internal interface. It is used here purely as
a local, read-only probe on the machine where ReCap is already installed, so we
can state an honest verdict about RCS support instead of guessing. The original
file is opened read-only and is never modified.

Run as a standalone process: a bad ABI assumption crashes this process only.

    python scripts/rcs_probe.py <file.rcs> [--max-points N] [--out sample.ply]
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time

RECAP_DIR = r"C:\Program Files\Autodesk\Autodesk ReCap"
DLL_NAME = "AdskRcExport.dll"

# MSVC mangled exports (verified present in the installed DLL).
M_CTOR = r"??0RCRcsDataSource@Export@RealityComputing@Autodesk@@QEAA@AEBV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@_N@Z"
M_DTOR = r"??1RCRcsDataSource@Export@RealityComputing@Autodesk@@UEAA@XZ"
M_OPEN = r"?open@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEAA_NXZ"
M_ADV = r"?advancePoint@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEAA_NXZ"
M_POS = r"?getPosition@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEBAXAEAU?$RCVector3T@N@Common@34@@Z"
M_COLOR = r"?getColor@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEBAXAEAU?$RCVector4T@E@Common@34@@Z"
M_COUNT = r"?getPointCt@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEBA_KXZ"
M_CLOSE = r"?close@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEAA_NXZ"
M_PROGRESS = r"?getStatusProgress@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEBANXZ"
M_STATUS = r"?getStatusMessage@RCRcsDataSource@Export@RealityComputing@Autodesk@@UEBAXAEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@@Z"


class WStr(ctypes.Structure):
    """MSVC std::wstring layout on x64 (32 bytes)."""

    _fields_ = [
        ("ptr_or_buf0", ctypes.c_uint64),
        ("buf1", ctypes.c_uint64),
        ("size", ctypes.c_uint64),
        ("cap", ctypes.c_uint64),
    ]


def _load():
    dll_path = os.path.join(RECAP_DIR, DLL_NAME)
    if not os.path.exists(dll_path):
        raise SystemExit(f"not installed: {dll_path}")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(RECAP_DIR)
    os.environ["PATH"] = RECAP_DIR + os.pathsep + os.environ.get("PATH", "")
    return ctypes.CDLL(dll_path), dll_path


def _proc(handle: int, mangled: str):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    kernel32.GetProcAddress.restype = ctypes.c_void_p
    addr = kernel32.GetProcAddress(ctypes.c_void_p(handle), mangled.encode("ascii"))
    if not addr:
        raise SystemExit(f"export not found: {mangled[:70]}...")
    # x64 Windows has a single calling convention; this-pointer in RCX.
    return ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64)(addr)


def _proc0(handle: int, mangled: str):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    kernel32.GetProcAddress.restype = ctypes.c_void_p
    addr = kernel32.GetProcAddress(ctypes.c_void_p(handle), mangled.encode("ascii"))
    if not addr:
        raise SystemExit(f"export not found: {mangled[:70]}...")
    return ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint64)(addr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rcs")
    ap.add_argument("--max-points", type=int, default=50_000)
    ap.add_argument("--out", default="")
    ap.add_argument("--bool-arg", choices=["1", "0", "auto"], default="auto")
    ap.add_argument("--count-only", action="store_true", help="iterate to the end and report the true point count")
    args = ap.parse_args()

    rcs = os.path.abspath(args.rcs)
    if not os.path.exists(rcs):
        raise SystemExit(f"missing file: {rcs}")
    print(f"file: {rcs} ({os.path.getsize(rcs):,} bytes)", flush=True)

    lib, dll_path = _load()
    handle = lib._handle
    print(f"loaded: {dll_path}", flush=True)

    ctor = _proc(handle, M_CTOR)
    dtor = _proc0(handle, M_DTOR)
    opn = _proc0(handle, M_OPEN)
    adv = _proc0(handle, M_ADV)
    pos = _proc(handle, M_POS)
    color = _proc(handle, M_COLOR)
    count = _proc0(handle, M_COUNT)
    close = _proc0(handle, M_CLOSE)
    progress = _proc0(handle, M_PROGRESS)
    status = _proc(handle, M_STATUS)
    print("resolved 10 exports", flush=True)

    this_buf = ctypes.create_string_buffer(8192)  # generous object storage
    this_ptr = ctypes.addressof(this_buf)

    utf16 = rcs.encode("utf-16-le") + b"\x00\x00"
    path_buf = ctypes.create_string_buffer(utf16, len(utf16) + 128)
    ws = WStr()
    # Heap mode: capacity well above the 7-char SSO limit for wchar_t.
    ws.ptr_or_buf0 = ctypes.addressof(path_buf)
    ws.size = len(rcs)  # code points of the ABSOLUTE path actually encoded above
    ws.cap = 4096
    ws_buf = ctypes.create_string_buffer(bytes(ws), len(bytes(ws)))
    ws_ptr = ctypes.addressof(ws_buf)

    bool_candidates = [True, False] if args.bool_arg == "auto" else [args.bool_arg == "1"]
    opened = False
    for flag in bool_candidates:
        print(f"constructor(bool={flag}) ...", flush=True)
        try:
            ctor(this_ptr, ws_ptr, 1 if flag else 0)
        except Exception as exc:  # pragma: no cover - ABI guard
            print(f"  ctor raised: {exc}", flush=True)
            continue
        rc = opn(this_ptr)
        print(f"  open() -> {bool(rc)}", flush=True)
        if rc:
            opened = True
            break
        dtor(this_ptr)

    if not opened:
        print("RESULT: open() failed for both bool values", flush=True)
        return 2

    def read_status() -> tuple[float, str]:
        p = progress(this_ptr)
        # getStatusMessage appends into a caller-owned std::wstring; give it a
        # valid empty SSO string (size 0, capacity 7 fits the inline buffer).
        msg = WStr()
        msg.size = 0
        msg.cap = 7
        msg_buf = ctypes.create_string_buffer(bytes(msg), 64)
        try:
            status(this_ptr, ctypes.addressof(msg_buf))
            loaded = WStr.from_buffer_copy(msg_buf[: 32])
            n = loaded.size
            if 0 < n < 4096 and loaded.ptr_or_buf0:
                raw = ctypes.string_at(loaded.ptr_or_buf0, n * 2)
                return float(p), raw.decode("utf-16-le", "replace")
        except Exception:
            pass
        return float(p), ""

    # The data source loads asynchronously; poll until progress settles.
    last = -1.0
    for i in range(60):
        p, msg = read_status()
        if i == 0 or abs(p - last) > 1e-9 or i % 10 == 0:
            print(f"  status progress={p:.4f} msg={msg!r}", flush=True)
        last = p
        if p >= 1.0:
            break
        time.sleep(0.5)

    n_total = count(this_ptr)
    print(f"getPointCt() -> {n_total:,}", flush=True)

    if args.count_only:
        t0 = time.time()
        n = 0
        while adv(this_ptr):
            n += 1
            if n % 2_000_000 == 0:
                print(f"  counted {n:,} ({n/(time.time()-t0):,.0f} pts/s)", flush=True)
        print(f"TRUE_COUNT={n:,} in {time.time()-t0:.1f}s", flush=True)
        try:
            close(this_ptr)
            dtor(this_ptr)
        except Exception:
            pass
        return 0

    # Probe the iterator: try advancing before assuming readiness.
    first_ok = adv(this_ptr)
    print(f"first advancePoint() -> {bool(first_ok)}", flush=True)

    t0 = time.time()
    pts = []
    colors = []
    read = 0
    limit = min(args.max_points, n_total or args.max_points)
    got_first = bool(first_ok)
    while read < limit:
        if read == 0 and got_first:
            pass  # first advance already done
        elif not adv(this_ptr):
            break
        v = (ctypes.c_double * 3)()
        pos(this_ptr, ctypes.addressof(v))
        pts.append((v[0], v[1], v[2]))
        c = (ctypes.c_ubyte * 4)()
        color(this_ptr, ctypes.addressof(c))
        colors.append((c[0], c[1], c[2]))
        read += 1
        if read == 1:
            got_first = False
    dt_read = time.time() - t0
    print(f"read {read:,} points in {dt_read:.2f}s", flush=True)

    if pts:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        zs = [p[2] for p in pts]
        print(
            "bbox: "
            f"x[{min(xs):.3f},{max(xs):.3f}] "
            f"y[{min(ys):.3f},{max(ys):.3f}] "
            f"z[{min(zs):.3f},{max(zs):.3f}]",
            flush=True,
        )
        print("first 3:", pts[:3], flush=True)

    if args.out and pts:
        with open(args.out, "wb") as f:
            head = (
                "ply\nformat binary_little_endian 1.0\n"
                f"element vertex {len(pts)}\n"
                "property double x\nproperty double y\nproperty double z\n"
                "property uchar red\nproperty uchar green\nproperty uchar blue\n"
                "end_header\n"
            ).encode("ascii")
            f.write(head)
            import struct as st

            for p, c in zip(pts, colors):
                f.write(st.pack("<dddBBB", p[0], p[1], p[2], c[0], c[1], c[2]))
        print(f"wrote {args.out}", flush=True)

    try:
        close(this_ptr)
    except Exception:
        pass
    try:
        dtor(this_ptr)
    except Exception as exc:
        print(f"dtor: {exc}", flush=True)

    print(
        f"RESULT: OK total={n_total:,} sampled={read:,}",
        flush=True,
    )
    return 0 if read else 3


if __name__ == "__main__":
    sys.exit(main())
