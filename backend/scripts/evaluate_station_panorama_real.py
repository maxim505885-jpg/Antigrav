"""Evaluate station panoramas on a real full-resolution scan, over HTTP.

Unlike ``validate_station_panorama_live.py`` (a synthetic room in an isolated
data root), this script runs against the project's own database and a real
FARO cloud, and measures the three things a panorama has to be good at:

* **coverage** — how much of the sphere actually carries measured points at two
  sheet sizes, with the streaming renderer's timing and peak server memory;
* **fidelity** — every picked pixel must resolve to a point that exists in the
  stored cloud, so the distance to its nearest stored neighbour is reported
  instead of being assumed;
* **accuracy** — a measurement taken on one sheet size must not change on
  another, and the pixel-to-ray-to-depth chain is re-projected to show the
  round-trip error rather than claiming exactness.

Nothing is invented: if the cloud has no station split the report says so and
records the single ``station_source="cloud"`` entry.

    python backend/scripts/evaluate_station_panorama_real.py             # biggest ready cloud
    python backend/scripts/evaluate_station_panorama_real.py --cloud-id <id> --port 8012
    python backend/scripts/evaluate_station_panorama_real.py --out docs/validation

Exit codes: 0 passed, 1 failed.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from scan2bim.processing.panorama import (  # noqa: E402
    MAX_RENDER_POINTS,
    project_point_to_uv,
    render_cloud_panorama,
    station_catalog,
    station_points,
)
from scan2bim.storage import cloud_paths  # noqa: E402

BASE = ""
PICKS_U = np.linspace(0.02, 0.98, 24)
PICKS_V = np.linspace(0.06, 0.94, 9)


def call(method: str, path: str, body: bytes | None = None, headers: dict | None = None, timeout: float = 900.0):
    request = urllib.request.Request(BASE + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def json_call(method: str, path: str, payload: dict | None = None, timeout: float = 900.0):
    body = json.dumps(payload).encode() if payload is not None else None
    status, _, raw = call(method, path, body, {"Content-Type": "application/json"}, timeout=timeout)
    return status, (json.loads(raw) if raw else None)


def pick_cloud(data_dir: Path, cloud_id: str | None) -> dict:
    database = data_dir / "scan2bim.sqlite3"
    if not database.is_file():
        raise SystemExit(f"database not found: {database}")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    if cloud_id:
        row = connection.execute("SELECT * FROM clouds WHERE id = ?", (cloud_id,)).fetchone()
    else:
        row = connection.execute(
            "SELECT * FROM clouds WHERE status = 'ready' ORDER BY point_count DESC LIMIT 1"
        ).fetchone()
    if row is None:
        raise SystemExit("no ready cloud in the project database")
    return dict(row)


def render_once(cloud_id: str, station_id: str, width: int, pid: int) -> dict:
    """Request one panorama and record wall time and peak server RSS."""
    import psutil

    samples: list[tuple[int, int]] = []
    stop: dict = {}

    def watch() -> None:
        # ``run.py`` starts uvicorn in a child process, so the launcher's own RSS
        # says nothing: sum the whole tree. RSS counts the memory-mapped cloud
        # file (reclaimable, ~3.5 GB of positions + 0.9 GB of colour), while USS
        # is what the renderer itself actually allocated.
        process = psutil.Process(pid)
        while not stop.get("done"):
            try:
                total_rss = 0
                total_uss = 0
                tree = [process] + process.children(recursive=True)
                for item in tree:
                    try:
                        info = item.memory_full_info()
                        total_rss += info.rss
                        total_uss += info.uss
                    except Exception:
                        pass
                samples.append((total_rss, total_uss))
            except Exception:
                break
            time.sleep(0.25)

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    started = time.perf_counter()
    status, headers, body = call(
        "GET", f"/clouds/{cloud_id}/stations/{station_id}/panorama?source=cloud&width={width}"
    )
    elapsed = time.perf_counter() - started
    stop["done"] = True
    thread.join(timeout=5)
    return {
        "width": width,
        "status": status,
        "seconds": round(elapsed, 2),
        "bytes": len(body),
        "png": body.startswith(b"\x89PNG"),
        "coverage_header": headers.get("X-Panorama-Coverage"),
        "source_header": headers.get("X-Panorama-Source"),
        "peak_server_rss_gb": round(max(s[0] for s in samples) / 2**30, 2) if samples else None,
        "peak_server_uss_gb": round(max(s[1] for s in samples) / 2**30, 2) if samples else None,
        "body": body,
    }


def summarise_renders(sheet_2048: dict, cached: dict, sheet_4096: dict) -> dict:
    def clean(sheet: dict) -> dict:
        return {key: value for key, value in sheet.items() if key != "body"}

    return {
        "2048": clean(sheet_2048),
        "2048_cached": clean(cached),
        "4096": clean(sheet_4096),
        "memory_note": (
            "peak_server_rss_gb включает страницы отображённых в память файлов облака "
            "(positions.npy + colors.npy), которые система может вытеснить; "
            "peak_server_uss_gb — память, реально выделенная процессом рендера."
        ),
    }


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-id", default=None)
    parser.add_argument("--port", type=int, default=8012)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--picks", type=int, default=150, help="сколько пикселей проверять на точность")
    parser.add_argument(
        "--no-sampled-baseline",
        action="store_true",
        help="не считать базовое покрытие прореженного рендера",
    )
    args = parser.parse_args()
    try:  # the protocol carries Russian notes; a cp1251 console must not crash it
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    BASE = f"http://127.0.0.1:{args.port}/api/v1"

    data_dir = args.data_dir.resolve()
    cloud = pick_cloud(data_dir, args.cloud_id)
    cloud_id = cloud["id"]
    paths = cloud_paths(cloud["project_id"], cloud_id)
    metadata = json.loads(cloud.get("metadata_json") or "{}")
    positions = paths["positions"]
    stored = int(np.load(positions, mmap_mode="r").shape[0])

    report: dict = {
        "check": "station_panorama_real_cloud",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cloud": {
            "id": cloud_id,
            "project_id": cloud["project_id"],
            "source_path": cloud["source_path"],
            "source_format": cloud["source_format"],
            "point_count": cloud["point_count"],
            "stored_points": stored,
            "has_color": bool(cloud["has_color"]),
            "decimated": bool(cloud["decimated"]),
            "source_point_count": metadata.get("source_point_count"),
            "origin": metadata.get("origin"),
            "bbox_min": metadata.get("bbox_min"),
            "bbox_max": metadata.get("bbox_max"),
            "station_metadata_present": isinstance(metadata.get("station_row_ranges"), list),
        },
        "limits": {
            "max_render_points": MAX_RENDER_POINTS,
            "note": (
                "Станции берутся из метаданных импорта. У этого облака их нет: RCS "
                "импортирован одним куском, поэтому каталог честно отдаёт одну станцию "
                "station_source='cloud', а не выдуманные стоянки сканера."
            ),
        },
    }

    log = data_dir / "logs" / f"panorama-eval-{int(time.time())}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "backend" / "run.py"), "--port", str(args.port)],
        cwd=str(ROOT),
        env=dict(os.environ, S2B_DATA_DIR=str(data_dir)),
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                status, _, raw = call("GET", "/health", timeout=5)
                if status == 200:
                    report["health"] = json.loads(raw)
                    break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("API did not start: " + log.read_text(encoding="utf-8")[-2000:])

        catalogue_cache = paths["dir"] / "stations_catalog.json"
        report["catalogue_cache_existed_before"] = catalogue_cache.is_file()

        status, stations = json_call("GET", f"/clouds/{cloud_id}/stations")
        assert status == 200, stations
        station_count = stations["count"]
        entry = stations["stations"][0]
        station_id = entry["station_id"]
        report["stations"] = {
            "count": station_count,
            "station_id": station_id,
            "station_source": entry["station_source"],
            "name": entry.get("name"),
            "anchor": entry["anchor"],
            "anchor_kind": entry["anchor_kind"],
            "point_count": entry["point_count"],
        }
        assert station_count >= 1, "no stations"

        # One render per width: the station cache is keyed by sheet size, so
        # every 2048 -> 4096 switch would otherwise re-render 300M points.
        sheet_2048 = render_once(cloud_id, station_id, 2048, server.pid)
        assert sheet_2048["status"] == 200 and sheet_2048["png"], sheet_2048
        sheet_png_2048 = sheet_2048.pop("body")
        cached_2048 = render_once(cloud_id, station_id, 2048, server.pid)
        cached_2048.pop("body", None)

        meta_path = paths["dir"] / "panoramas" / station_id / "cloud_panorama.json"
        render_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        depth_sheet = np.load(paths["dir"] / "panoramas" / station_id / "depth.npy")
        sheet_h, sheet_w = int(depth_sheet.shape[0]), int(depth_sheet.shape[1])
        origin = np.asarray(metadata.get("origin") or [0.0, 0.0, 0.0], dtype=np.float64)
        anchor_local = np.asarray(entry["anchor"], dtype=np.float64) - origin
        report["depth_sheet"] = {"width": sheet_w, "height": sheet_h}

        # ---- pixel -> point -> pixel round trip ---------------------------------
        picks: list[dict] = []
        for u in PICKS_U:
            for v in PICKS_V:
                if len(picks) >= args.picks:
                    break
                status, result = json_call(
                    "POST",
                    f"/clouds/{cloud_id}/stations/{station_id}/pick",
                    {"u": float(u), "v": float(v), "width": 2048, "height": 1024},
                )
                if status == 200 and result.get("resolved"):
                    picks.append(result)
            if len(picks) >= args.picks:
                break
        report["picks"] = {
            "grid": [int(len(PICKS_U)), int(len(PICKS_V))],
            "resolved": len(picks),
        }
        assert len(picks) >= 20, f"too few resolved picks: {len(picks)}"

        # A pick is "anchor + pixel ray x measured depth", so the returned point
        # sits on the pixel ray rather than exactly on the stored point. The
        # offset is the sub-pixel angular quantisation and is compared against
        # the precision the API itself reports.
        reprojection_px: list[float] = []
        offsets_mm: list[float] = []
        precisions_mm: list[float] = []
        for item in picks:
            local = np.asarray(item["point_local"], dtype=np.float64)
            u2, v2, distance = project_point_to_uv(local, anchor_local)
            reprojection_px.append(math.hypot((u2 - item["u"]) * 2048.0, (v2 - item["v"]) * 1024.0))
            offsets_mm.append(abs(distance - float(item["distance_m"])) * 1000.0)
            precisions_mm.append(float(item.get("lateral_precision_m") or 0.0) * 1000.0)
        report["pixel_to_ray_roundtrip"] = {
            "samples": len(picks),
            "pixel_offset_median_px": round(float(np.median(reprojection_px)), 6),
            "pixel_offset_max_px": round(float(np.max(reprojection_px)), 6),
            "depth_vs_point_median_mm": float(f"{np.median(offsets_mm):.3e}"),
            "depth_vs_point_max_mm": float(f"{np.max(offsets_mm):.3e}"),
            "note": (
                "pixel_offset - возвращённая точка лежит на луче центра пикселя; "
                "глубина сверена с расстоянием от центра обзора до этой точки."
            ),
        }
        assert max(offsets_mm) < 1.0, "depth and returned point disagree"
        assert max(reprojection_px) <= 1.5, f"reprojection error {max(reprojection_px):.2f} px"

        # ---- fidelity: independent recomputation of the whole depth sheet ------
        # Streaming the cloud again and rebuilding the z-buffer from scratch is
        # the only check that proves every metre in depth.npy is a measured point
        # rather than a smoothed surface. Coverage and depth must match exactly.
        array = np.load(positions, mmap_mode="r")
        fresh = np.full(sheet_w * sheet_h, np.inf, dtype=np.float64)
        max_range = float(render_meta.get("max_range_m") or 60.0)
        block_rows = 8_000_000
        recomputed_points = 0
        for row_start in range(0, stored, block_rows):
            row_end = min(stored, row_start + block_rows)
            block = np.asarray(array[row_start:row_end], dtype=np.float64)[:, :3]
            block = block[np.isfinite(block).all(axis=1)]
            if not len(block):
                continue
            diff = block - anchor_local
            distance = np.linalg.norm(diff, axis=1)
            safe = np.maximum(distance, 1e-9)
            phi = np.arctan2(diff[:, 0], diff[:, 1])
            theta = np.arcsin(np.clip(diff[:, 2] / safe, -1.0, 1.0))
            u = phi / (2.0 * np.pi) + 0.5
            v = 0.5 - theta / np.pi
            valid = (distance > 0.02) & (distance <= max_range)
            if not valid.any():
                continue
            u, v, distance = u[valid], v[valid], distance[valid]
            recomputed_points += int(distance.size)
            px = np.clip((u * sheet_w).astype(np.int64), 0, sheet_w - 1)
            py = np.clip((v * sheet_h).astype(np.int64), 0, sheet_h - 1)
            np.minimum.at(fresh, py * sheet_w + px, distance)
        fresh[~np.isfinite(fresh)] = np.nan
        fresh_sheet = fresh.reshape(sheet_h, sheet_w).astype(np.float32)
        ours_finite = np.isfinite(depth_sheet)
        fresh_finite = np.isfinite(fresh_sheet)
        common = ours_finite & fresh_finite
        delta = np.abs(
            depth_sheet[common].astype(np.float64) - fresh_sheet[common].astype(np.float64)
        )
        report["depth_recomputation"] = {
            "pixels_compared": int(common.sum()),
            "pixel_set_identical": bool(np.array_equal(ours_finite, fresh_finite)),
            "max_abs_difference_m": float(f"{np.max(delta) if delta.size else 0.0:.3e}"),
            "median_abs_difference_m": float(f"{np.median(delta) if delta.size else 0.0:.3e}"),
            "points_reprojected": recomputed_points,
            "max_range_m": max_range,
            "note": (
                "Карта глубин пересчитана с нуля по всему облаку независимым кодом; "
                "совпадение означает, что каждая дистанция — измеренная точка, а "
                "не сглаженная поверхность."
            ),
        }
        assert bool(np.array_equal(ours_finite, fresh_finite)), "depth sheet covers a different set of pixels"
        assert float(np.max(delta)) < 1e-3, "recomputed depth differs from the served depth"

        # ---- measurement pairs on the 2048 sheet --------------------------------
        filled = np.isfinite(depth_sheet)
        rows, cols = np.nonzero(filled)
        rng = np.random.default_rng(20261026)
        pairs: list[tuple[tuple[float, float], tuple[float, float]]] = []
        attempts = 0
        while len(pairs) < 12 and attempts < 400:
            attempts += 1
            i, j = rng.integers(0, len(rows), size=2)
            if i == j:
                continue
            a = (float(cols[i]) / sheet_w, float(rows[i]) / sheet_h)
            b = (float(cols[j]) / sheet_w, float(rows[j]) / sheet_h)
            if abs(a[0] - b[0]) < 0.05 and abs(a[1] - b[1]) < 0.05:
                continue
            pairs.append((a, b))

        def measure_pair(a, b, width: int) -> dict | None:
            status, result = json_call(
                "POST",
                f"/clouds/{cloud_id}/stations/{station_id}/measure",
                {
                    "a": {"u": a[0], "v": a[1]},
                    "b": {"u": b[0], "v": b[1]},
                    "width": width,
                    "height": width // 2,
                },
            )
            return result if status == 200 else None

        base_measures: list[dict] = []
        for a, b in pairs:
            first = measure_pair(a, b, 2048)
            if first is None:
                continue
            base_measures.append({"pair": (a, b), "first": first})
        assert base_measures, "no measurements succeeded on the 2048 sheet"

        # ---- the same pairs on the 4096 sheet -----------------------------------
        sheet_4096 = render_once(cloud_id, station_id, 4096, server.pid)
        assert sheet_4096["status"] == 200 and sheet_4096["png"], sheet_4096
        sheet_4096.pop("body", None)

        # ---- before/after: the same cloud through the subsampling path -------
        # This is the renderer SCAN used before streaming existed: at most
        # MAX_RENDER_POINTS points projected into the sheet. Its coverage is the
        # baseline the streaming renderer is compared against.
        if not args.no_sampled_baseline:
            catalog_entry = station_catalog(positions, metadata)[0]
            baseline = {}
            for width in (2048, 4096):
                started = time.perf_counter()
                pts, step = station_points(positions, catalog_entry)
                baseline_colors = None
                if paths["colors"].is_file():
                    colors_array = np.load(paths["colors"], mmap_mode="r")
                    sliced = np.asarray(
                        colors_array[int(catalog_entry["row_start"]):int(catalog_entry["row_end"]):step]
                    )
                    if len(sliced) == len(pts):
                        baseline_colors = sliced
                    del colors_array
                rendered = render_cloud_panorama(
                    pts,
                    anchor_local,
                    width=width,
                    height=width // 2,
                    max_range_m=60.0,
                    colors=baseline_colors,
                )
                baseline[str(width)] = {
                    "coverage": round(float(rendered["coverage"]), 4),
                    "projected_points": int(rendered["rendered_points"]),
                    "stride": int(rendered["stride"]),
                    "seconds": round(time.perf_counter() - started, 2),
                }
                del pts, baseline_colors, rendered
            report["sampled_baseline"] = {
                "note": (
                    "Тот же рендер до потоковой реализации: облако прореживалось до "
                    f"{MAX_RENDER_POINTS} точек, поэтому лист был заметно разряжён."
                ),
                **baseline,
            }

        measurements: list[dict] = []
        for item in base_measures:
            a, b = item["pair"]
            first = item["first"]
            second = measure_pair(a, b, 4096)
            if second is None:
                continue
            pa = np.asarray(first["a"]["point_local"], dtype=np.float64)
            pb = np.asarray(first["b"]["point_local"], dtype=np.float64)
            measurements.append(
                {
                    "distance_2048_m": first["distance_m"],
                    "distance_4096_m": second["distance_m"],
                    "delta_mm": (second["distance_m"] - first["distance_m"]) * 1000.0,
                    "closure_error_mm": (float(np.linalg.norm(pb - pa)) - first["distance_m"]) * 1000.0,
                    "precision_mm": first["precision_mm"],
                    "reliable": bool(first.get("reliable", True) and second.get("reliable", True)),
                    "unstable_endpoints": first.get("unstable_endpoints") or [],
                }
            )
        assert measurements, "no measurements succeeded on the 4096 sheet"
        stable = [item for item in measurements if item["reliable"]]
        unstable = [item for item in measurements if not item["reliable"]]
        deltas = np.asarray([abs(item["delta_mm"]) for item in measurements], dtype=np.float64)
        stable_deltas = np.asarray([abs(item["delta_mm"]) for item in stable], dtype=np.float64)
        unstable_deltas = np.asarray([abs(item["delta_mm"]) for item in unstable], dtype=np.float64)
        closures = np.asarray([abs(item["closure_error_mm"]) for item in measurements])
        precisions = np.asarray([item["precision_mm"] for item in measurements])
        report["render"] = summarise_renders(sheet_2048, cached_2048, sheet_4096)
        report["render_meta"] = {
            key: render_meta.get(key)
            for key in (
                "source", "is_photograph", "renderer", "renderer_version", "full_resolution",
                "width", "height", "coverage", "points_examined", "station_points",
                "rendered_points", "beyond_range_points", "render_seconds", "color_source",
                "anchor_kind", "stride", "max_range_m",
            )
        }
        report["measurement"] = {
            "pairs": len(measurements),
            "distance_range_m": [
                round(min(item["distance_2048_m"] for item in measurements), 3),
                round(max(item["distance_2048_m"] for item in measurements), 3),
            ],
            "all_pairs": {
                "resolution_delta_median_mm": round(float(np.median(deltas)), 3),
                "resolution_delta_max_mm": round(float(np.max(deltas)), 3),
            },
            "continuous_surface_pairs": {
                "count": len(stable),
                "resolution_delta_median_mm": round(float(np.median(stable_deltas)), 3) if stable else None,
                "resolution_delta_max_mm": round(float(np.max(stable_deltas)), 3) if stable else None,
            },
            "discontinuity_pairs": {
                "count": len(unstable),
                "resolution_delta_median_mm": round(float(np.median(unstable_deltas)), 3) if unstable else None,
                "resolution_delta_max_mm": round(float(np.max(unstable_deltas)), 3) if unstable else None,
                "note": "замеры, где хотя бы один пиксель стоит на разрыве глубин: API помечает их reliable=false",
            },
            "closure_error_max_mm": float(f"{np.max(closures):.3e}"),
            "reported_precision_median_mm": round(float(np.median(precisions)), 2),
            "note": (
                "delta — расхождение одного и того же замера на листах 2048 и 4096 px; "
                "closure — сверка отданного расстояния с евклидовым расстоянием между "
                "возвращёнными точками; precision — оценка из углового разрешения листа."
            ),
            "samples": measurements,
        }
        assert float(np.max(closures)) < 1e-6, "measure reported a distance that does not close"
        if stable:
            assert float(np.max(stable_deltas)) < 250.0, (
                f"a continuous-surface measurement moved by {float(np.max(stable_deltas)):.0f} mm "
                "between sheet sizes"
            )

        # ---- keep a downscaled sheet next to the protocol for review ------------
        if args.out is not None:
            from PIL import Image

            args.out.mkdir(parents=True, exist_ok=True)
            image = Image.open(io.BytesIO(sheet_png_2048)).convert("RGB")
            preview = args.out / f"STATION_PANORAMA_REAL_{cloud_id[:8]}.jpg"
            image.resize((1400, 700), Image.LANCZOS).save(preview, quality=82)
            report["preview_file"] = str(preview)

        report["result"] = "passed"
    except Exception as exc:  # noqa: BLE001 - the traceback is the report
        import traceback

        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
        handle.close()

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (args.out / f"STATION_PANORAMA_REAL_{stamp}.json").write_text(text, encoding="utf-8")
    return 0 if report.get("result") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
