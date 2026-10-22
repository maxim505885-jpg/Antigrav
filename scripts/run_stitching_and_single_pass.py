"""Unified Multi-Station Stitching & Single-Pass Scan-to-BIM Pipeline.

Performs:
1. ICP Registration between Station 1 (1.rcs - 40M pts) and Station 2 (2.rcs - 3.5M stream pts).
2. Unified point cloud merging into a single coordinated dataset (43.5M pts) with metadata and SE(3) manifest.
3. Voxel LOD Octree pyramid construction.
4. Structural frame recognition (columns, crane beams, roof trusses) with industrial clutter filtering.
5. Official SPDS drawing album release with native binary AutoCAD .dwg (AC1032), .dxf, and .pdf.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import time
import numpy as np

# Ensure backend is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from scan2bim.registration.stitching import rigid_icp, create_recap_registration_project
from scan2bim.pipeline_single_pass import WorkshopPipeline
from scan2bim.cad.dwg_compiler import batch_convert_album_to_dwg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("unified_pipeline")


def run_unified_pipeline(
    output_root: str | Path = "data/output/unified_stitched_release",
    project_title: str = "Сводная модель цеха (1.rcs + 2.rcs)",
) -> dict:
    t_start = time.time()
    out_dir = Path(output_root).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 70)
    print("=== ЗАПУСК СКВОЗНОЙ СШИВКИ СКАНОВ И ВЫПУСКА РАБОЧЕЙ ДОКУМЕНТАЦИИ (DWG) ===")
    print("=" * 70)

    # 1. ЗАГРУЗКА ИСХОДНЫХ СКАНОB
    print("\n[Этап 1/5] Загрузка станций сканирования...")
    c1_meta_path = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e/meta.json")
    c1_pos_path = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e/positions.npy")
    c1_meta = json.loads(c1_meta_path.read_text(encoding="utf-8"))
    c1_pts = np.load(c1_pos_path, mmap_mode="r")
    origin1 = np.asarray(c1_meta.get("origin", [0.0, 0.0, 0.0]), dtype=np.float64)

    c2_dir = Path("data/projects/cloud_2_rcs_stream")
    c2_stream = json.loads((c2_dir / "stream.json").read_text(encoding="utf-8"))
    count2 = c2_stream["committed_count"]
    c2_pts = np.memmap(c2_dir / "xyz.f64", dtype=np.float64, mode="r", shape=(count2, 3))

    print(f"  * Станция 1 (1.rcs): {len(c1_pts):,} точек (отсчетная база)")
    print(f"  * Станция 2 (2.rcs): {count2:,} точек (дополнительная стоянка)")

    # 2. РЕГИСТРАЦИЯ И СШИВКА (ICP)
    print("\n[Этап 2/5] Пространственная сшивка методом ICP (SE(3) Alignment)...")
    idx1 = np.random.randint(0, len(c1_pts), size=20000)
    pts1_world = c1_pts[idx1].astype(np.float64) + origin1

    idx2 = np.random.randint(0, count2, size=20000)
    pts2_raw = np.array(c2_pts[idx2], dtype=np.float64)

    icp_res = rigid_icp(pts2_raw, pts1_world, max_iterations=30, max_correspondence_distance_m=1.0, sample_size=10000)
    print(f"  [OK] ICP сошелся: {icp_res['converged']} (итераций: {icp_res['iterations']}, RMSE: {icp_res['rmse_mm']:.2f} мм)")
    t_vec = [round(x, 4) for x in icp_res['translation']]
    print(f"  [OK] Вектор смещения T: {t_vec}")

    # 3. ФОРМИРОВАНИЕ СВОДНОГО МАССИВА ТОЧЕК
    print("\n[Этап 3/5] Формирование единого координатного массива (Unified Dataset)...")
    unified_cloud_dir = out_dir / "unified_cloud"
    unified_cloud_dir.mkdir(parents=True, exist_ok=True)
    unified_positions_path = unified_cloud_dir / "positions.npy"
    total_pts = len(c1_pts) + count2

    mat2 = np.asarray(icp_res["matrix_4x4"], dtype=np.float64)
    r2 = mat2[:3, :3]
    t2 = mat2[:3, 3]

    if not (unified_positions_path.is_file() and (unified_cloud_dir / "meta.json").is_file()):
        # Pre-allocate unified array in float32 with valid NPY format header
        from numpy.lib.format import open_memmap

        if unified_positions_path.exists():
            try:
                unified_positions_path.unlink()
            except Exception:
                pass

        unified_mmap = open_memmap(unified_positions_path, mode="w+", dtype=np.float32, shape=(total_pts, 3))

        # Chunk copy Cloud 1 world points
        chunk_sz = 5_000_000
        for i in range(0, len(c1_pts), chunk_sz):
            end = min(i + chunk_sz, len(c1_pts))
            unified_mmap[i:end] = c1_pts[i:end] + origin1.astype(np.float32)

        # Chunk copy Cloud 2 transformed points
        offset = len(c1_pts)
        for i in range(0, count2, chunk_sz):
            end = min(i + chunk_sz, count2)
            pts_chunk = np.array(c2_pts[i:end], dtype=np.float64)
            transformed_chunk = (r2 @ pts_chunk.T).T + t2
            unified_mmap[offset + i:offset + end] = transformed_chunk.astype(np.float32)

        # Measure exact global bounding box and center
        world_min = np.asarray(unified_mmap.min(axis=0), dtype=np.float64)
        world_max = np.asarray(unified_mmap.max(axis=0), dtype=np.float64)
        global_origin = ((world_min + world_max) / 2.0).astype(np.float64)

        # In-place center so that positions match CloudGeometry contract: local = world - origin
        for i in range(0, total_pts, chunk_sz):
            end = min(i + chunk_sz, total_pts)
            unified_mmap[i:end] -= global_origin.astype(np.float32)

        unified_mmap.flush()
        del unified_mmap

        # Compute SHA-256 and bounds for meta.json
        local_check = np.load(unified_positions_path, mmap_mode="r")
        local_min = np.asarray(local_check.min(axis=0), dtype=np.float64)
        local_max = np.asarray(local_check.max(axis=0), dtype=np.float64)

        import hashlib
        hasher = hashlib.sha256()
        with open(unified_positions_path, "rb") as f:
            while b := f.read(8 * 1024 * 1024):
                hasher.update(b)
        sha256 = hasher.hexdigest()

        meta = {
            "reader": "multi_scan_unified_stitcher",
            "name": project_title,
            "source_point_count": total_pts,
            "stored_point_count": total_pts,
            "origin": global_origin.tolist(),
            "bbox_min": (local_min + global_origin).tolist(),
            "bbox_max": (local_max + global_origin).tolist(),
            "checksum_sha256": sha256,
            "station_count": 2,
            "unified_merge": True,
        }
        (unified_cloud_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        print(f"  * Использован ранее подготовленный сводный массив точек: {total_pts:,} точек")

    # Registration manifest
    stations_data = [
        {"id": "station_01_rcs_1", "path": "1.rcs", "point_count": len(c1_pts), "matrix_4x4": np.eye(4).tolist(), "rmse_mm": 0.0},
        {"id": "station_02_rcs_2", "path": "2.rcs", "point_count": count2, "matrix_4x4": mat2.tolist(), "rmse_mm": icp_res["rmse_mm"]},
    ]
    manifest_path = out_dir / "registration_manifest.json"
    create_recap_registration_project(stations_data, project_title, manifest_path)
    print(f"  [OK] Сводное облако создано: {total_pts:,} точек в {unified_positions_path}")
    print(f"  [OK] Метаданные и манифест ReCap сохранены в {manifest_path.name}")

    # 4. ВЫПОЛНЕНИЕ КОНВЕЙЕРА РАСПОЗНАВАНИЯ И ВЫПУСКА РАБОЧЕЙ ДОКУМЕНТАЦИИ
    print("\n[Этап 4/5] Распознавание несущего каркаса и генерация чертежей СПДС...")
    pipeline = WorkshopPipeline(output_root=out_dir / "spds_release")
    summary = pipeline.execute_pipeline(unified_positions_path, project_title=project_title)

    # 5. ПАКЕТНАЯ КОМПИЛЯЦИЯ В БИНАРНЫЙ DWG (AC1032)
    print("\n[Этап 5/5] Автоматическая компиляция нативных бинарных .DWG файлов (AutoCAD 2026)...")
    album_dir = out_dir / "spds_release" / "spds_draft"
    dwgs = batch_convert_album_to_dwg(album_dir)
    print(f"  [OK] Скомпилировано {len(dwgs)} бинарных DWG чертежей:")
    for dwg in dwgs:
        print(f"    - {dwg.name} ({dwg.stat().st_size / 1024:.1f} KB, AC1032)")

    duration = time.time() - t_start
    print("\n" + "=" * 70)
    print(f"=== СКВОЗНОЙ ПРОЦЕСС ПОЛНОСТЬЮ ЗАВЕРШЕН ЗА {duration:.1f} СЕК! ===")
    print(f"  Всего обработано точек: {total_pts:,}")
    print(f"  Распознано колонн: {summary.get('candidate_counts_by_class', {}).get('column', 'N/A')}")
    print(f"  Готовые DWG чертежи: {album_dir}")
    print("=" * 70 + "\n")

    return {
        "status": "success",
        "duration_sec": round(duration, 2),
        "total_points": total_pts,
        "icp_registration": icp_res,
        "manifest_path": str(manifest_path),
        "unified_cloud": str(unified_positions_path),
        "dwg_files": [str(d) for d in dwgs],
        "album_dir": str(album_dir),
    }


if __name__ == "__main__":
    run_unified_pipeline()
