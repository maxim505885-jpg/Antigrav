"""Experimental full-resolution multi-station registration and draft pipeline.

Performs:
1. Require complete, non-decimated station data before registration or release output.
2. Run reproducible ICP and retain selected source-row IDs as registration evidence.
3. Merge full-resolution stations into a single coordinated dataset.
4. Voxel LOD Octree pyramid construction.
5. Structural frame recognition (columns, crane beams, roof trusses) with industrial clutter filtering.

Outputs remain drafts. The station manifest is metadata only and does not create an
Autodesk ReCap RCP/RCS project or verify registration against independent controls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
import numpy as np

# Ensure backend is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from scan2bim.registration.stitching import (
    rigid_icp,
    create_recap_registration_project,
    validate_full_resolution_station,
    validate_unified_cloud_cache,
    write_centered_unified_positions,
)
from scan2bim.formats.rcs_native import _read_stream_checkpoint, _verify_stream_files
from scan2bim.pipeline_single_pass import WorkshopPipeline
from scan2bim.cad.dwg_compiler import batch_convert_album_to_dwg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("unified_pipeline")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_unified_pipeline(
    output_root: str | Path = "data/output/unified_stitched_release",
    project_title: str = "Сводная модель цеха (1.rcs + 2.rcs)",
) -> dict:
    t_start = time.time()
    out_dir = Path(output_root).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 70)
    print("=== ПРОВЕРКА ПОЛНОТЫ СТАНЦИЙ И ЧЕРНОВОЙ КОНВЕЙЕР Scan-to-BIM ===")
    print("=" * 70)

    # 1. ЗАГРУЗКА ИСХОДНЫХ СКАНОB
    print("\n[Этап 1/5] Загрузка станций сканирования...")
    c1_meta_path = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e/meta.json")
    c1_pos_path = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e/positions.npy")
    c1_meta = json.loads(c1_meta_path.read_text(encoding="utf-8"))
    c1_pts = np.load(c1_pos_path, mmap_mode="r")
    origin1 = np.asarray(c1_meta.get("origin", [0.0, 0.0, 0.0]), dtype=np.float64)
    c1_source_count = c1_meta.get("source_point_count")
    c1_complete = (
        c1_meta.get("decimated") is False
        and c1_source_count == len(c1_pts)
        and c1_meta.get("stored_point_count") == len(c1_pts)
    )
    validate_full_resolution_station(
        "station_01_rcs_1", c1_source_count, len(c1_pts),
        complete=c1_complete, decimated=c1_meta.get("decimated"),
    )

    c2_dir = Path("data/projects/cloud_2_rcs_stream")
    c2_stream = json.loads((c2_dir / "stream.json").read_text(encoding="utf-8"))
    count2 = c2_stream["committed_count"]
    c2_source_count = c2_stream.get("source_point_count")
    if c2_source_count is None and c2_stream.get("complete") is True:
        c2_source_count = count2
    validate_full_resolution_station(
        "station_02_rcs_2", c2_source_count, count2,
        complete=c2_stream.get("complete") is True,
        decimated=c2_stream.get("decimated"),
    )
    stream_checkpoint = _read_stream_checkpoint(
        c2_dir, c2_stream.get("source_identity"),
    )
    if stream_checkpoint is None or stream_checkpoint != c2_stream:
        raise ValueError("station_02_rcs_2 stream checkpoint changed while preparing registration")
    _verify_stream_files(c2_dir, stream_checkpoint, exact_size=True)
    c2_source_sha256 = c2_stream.get("source_identity", {}).get("sha256")
    if not isinstance(c2_source_sha256, str) or len(c2_source_sha256) != 64:
        raise ValueError("station_02_rcs_2 complete stream has no valid source SHA-256 identity")
    c2_xyz_path = c2_dir / "xyz.f64"
    if not c2_xyz_path.is_file() or c2_xyz_path.stat().st_size != count2 * 3 * np.dtype(np.float64).itemsize:
        raise ValueError("station_02_rcs_2 XYZ stream size does not match its committed point count")
    c2_pts = np.memmap(c2_xyz_path, dtype=np.float64, mode="r", shape=(count2, 3))

    print(f"  * Станция 1 (1.rcs): {len(c1_pts):,} точек (отсчетная база)")
    print(f"  * Станция 2 (2.rcs): {count2:,} точек (дополнительная стоянка)")
    total_pts = len(c1_pts) + count2
    station_row_ranges = [
        {
            "station_id": "station_01_rcs_1",
            "source_row_start": 0,
            "source_row_end_exclusive": len(c1_pts),
            "source_row_count": len(c1_pts),
            "source_row_index_base": 0,
        },
        {
            "station_id": "station_02_rcs_2",
            "source_row_start": len(c1_pts),
            "source_row_end_exclusive": total_pts,
            "source_row_count": count2,
            "source_row_index_base": 0,
        },
    ]

    # 2. РЕГИСТРАЦИЯ И СШИВКА (ICP)
    print("\n[Этап 2/5] Пространственная сшивка методом ICP (SE(3) Alignment)...")
    rng = np.random.default_rng(20261023)
    idx1 = np.sort(rng.choice(len(c1_pts), size=min(20000, len(c1_pts)), replace=False))
    pts1_world = c1_pts[idx1].astype(np.float64) + origin1

    idx2 = np.sort(rng.choice(count2, size=min(20000, count2), replace=False))
    pts2_raw = np.array(c2_pts[idx2], dtype=np.float64)

    icp_res = rigid_icp(
        pts2_raw, pts1_world, max_iterations=30,
        max_correspondence_distance_m=1.0, sample_size=10000,
        random_seed=20261023,
    )
    icp_res["source_sample_row_ids"] = idx2[np.asarray(icp_res["source_sample_indices"], dtype=np.int64)].tolist()
    icp_res["target_sample_row_ids"] = idx1[np.asarray(icp_res["target_sample_indices"], dtype=np.int64)].tolist()
    source_row_start = station_row_ranges[1]["source_row_start"]
    target_row_start = station_row_ranges[0]["source_row_start"]
    icp_res["source_sample_unified_row_ids"] = [
        source_row_start + row_id for row_id in icp_res["source_sample_row_ids"]
    ]
    icp_res["target_sample_unified_row_ids"] = [
        target_row_start + row_id for row_id in icp_res["target_sample_row_ids"]
    ]
    evidence_path = out_dir / "registration_evidence.json"
    evidence = {
        "algorithm": "rigid_icp",
        "random_seed": 20261023,
        "source_station_id": "station_02_rcs_2",
        "target_station_id": "station_01_rcs_1",
        "source_point_count": count2,
        "target_point_count": len(c1_pts),
        "source_station_unified_row_range": station_row_ranges[1],
        "target_station_unified_row_range": station_row_ranges[0],
        "unified_row_index_space": "unified positions.npy row index",
        "registration_verified": False,
        "notice": "ICP result is a review proposal; it has not been checked against independent targets or controls.",
        **icp_res,
    }
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    if not icp_res["converged"] or icp_res["rmse_mm"] is None:
        raise RuntimeError(
            f"ICP registration did not converge; no unified cloud or drawing release was produced. "
            f"See {evidence_path} for the sampled point-row evidence."
        )
    print(f"  [OK] ICP сходимость получена, но требует внешней проверки (итераций: {icp_res['iterations']}, RMSE: {icp_res['rmse_mm']:.2f} мм)")
    t_vec = [round(x, 4) for x in icp_res['translation']]
    print(f"  [OK] Вектор смещения T: {t_vec}")

    # 3. ФОРМИРОВАНИЕ СВОДНОГО МАССИВА ТОЧЕК
    print("\n[Этап 3/5] Формирование единого координатного массива (Unified Dataset)...")
    unified_cloud_dir = out_dir / "unified_cloud"
    unified_cloud_dir.mkdir(parents=True, exist_ok=True)
    unified_positions_path = unified_cloud_dir / "positions.npy"
    unified_meta_path = unified_cloud_dir / "meta.json"
    station_input_fingerprints = {
        "station_01_rcs_1": {
            "source_point_count": int(c1_source_count),
            "stored_point_count": len(c1_pts),
            "unified_row_start": 0,
            "unified_row_end_exclusive": len(c1_pts),
            "origin": origin1.tolist(),
            "stored_positions_sha256": _sha256_file(c1_pos_path),
        },
        "station_02_rcs_2": {
            "source_point_count": int(c2_source_count),
            "stored_point_count": count2,
            "unified_row_start": len(c1_pts),
            "unified_row_end_exclusive": total_pts,
            "source_sha256": c2_source_sha256,
        },
    }

    mat2 = np.asarray(icp_res["matrix_4x4"], dtype=np.float64)
    r2 = mat2[:3, :3]
    t2 = mat2[:3, 3]

    has_cached_positions = unified_positions_path.is_file()
    has_cached_meta = unified_meta_path.is_file()
    if has_cached_positions != has_cached_meta:
        raise ValueError("cached unified cloud is incomplete; choose a new output directory")
    if has_cached_positions:
        cached_positions = np.load(unified_positions_path, mmap_mode="r")
        cached_meta = json.loads(unified_meta_path.read_text(encoding="utf-8"))
        validate_unified_cloud_cache(
            cached_meta,
            expected_point_count=total_pts,
            actual_point_count=len(cached_positions),
            expected_station_inputs=station_input_fingerprints,
            expected_registration_matrix=mat2,
            actual_file_sha256=_sha256_file(unified_positions_path),
        )
        print(f"  * Проверенный ранее подготовленный сводный массив: {total_pts:,} точек")
    else:
        merge_info = write_centered_unified_positions(
            [
                {"id": "station_01_rcs_1", "points": c1_pts, "origin": origin1},
                {"id": "station_02_rcs_2", "points": c2_pts, "matrix_4x4": mat2},
            ],
            unified_positions_path,
            chunk_size=1_000_000,
        )
        if merge_info["station_row_ranges"] != station_row_ranges:
            raise RuntimeError("merged station source-row ranges do not match current full-resolution inputs")
        global_origin = merge_info["origin"]

        # Compute SHA-256 and bounds for meta.json
        local_check = np.load(unified_positions_path, mmap_mode="r")
        local_min = np.asarray(local_check.min(axis=0), dtype=np.float64)
        local_max = np.asarray(local_check.max(axis=0), dtype=np.float64)

        unified_sha256 = _sha256_file(unified_positions_path)

        meta = {
            "reader": "multi_scan_unified_stitcher",
            "name": project_title,
            "source_point_count": total_pts,
            "stored_point_count": total_pts,
            "origin": global_origin.tolist(),
            "bbox_min": (local_min + global_origin).tolist(),
            "bbox_max": (local_max + global_origin).tolist(),
            "checksum_sha256": unified_sha256,
            "station_count": 2,
            "unified_merge": True,
            "station_input_fingerprints": station_input_fingerprints,
            "station_row_ranges": station_row_ranges,
            "registration_matrix_station_02": mat2.tolist(),
            "registration_verified": False,
            "recap_project_generated": False,
        }
        unified_meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # Registration manifest
    stations_data = [
        {"id": "station_01_rcs_1", "path": "1.rcs", "point_count": len(c1_pts),
         "source_row_start": 0, "source_row_end_exclusive": len(c1_pts),
         "matrix_4x4": np.eye(4).tolist(), "rmse_mm": None},
        {"id": "station_02_rcs_2", "path": "2.rcs", "point_count": count2,
         "source_row_start": len(c1_pts), "source_row_end_exclusive": total_pts,
         "matrix_4x4": mat2.tolist(), "rmse_mm": icp_res["rmse_mm"]},
    ]
    manifest_path = out_dir / "registration_manifest.json"
    create_recap_registration_project(stations_data, project_title, manifest_path)
    print(f"  [OK] Черновое сводное облако создано: {total_pts:,} точек в {unified_positions_path}")
    print(f"  [OK] Сохранены metadata-only манифест и ICP evidence; RCP не создан и регистрация не принята")

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
    print(f"=== ЧЕРНОВОЙ КОНВЕЙЕР ЗАВЕРШЕН ЗА {duration:.1f} СЕК; ПРИЁМКА НЕ ПРОЙДЕНА ===")
    print(f"  Всего обработано точек: {total_pts:,}")
    print(f"  Распознано колонн: {summary.get('candidate_counts_by_class', {}).get('column', 'N/A')}")
    print(f"  Черновые DWG файлы: {album_dir}")
    print("  ReCap RCP/RCS и инженерная регистрация остаются неподтверждёнными")
    print("=" * 70 + "\n")

    return {
        "status": "draft_success",
        "release_accepted": False,
        "duration_sec": round(duration, 2),
        "total_points": total_pts,
        "icp_registration": icp_res,
        "manifest_path": str(manifest_path),
        "registration_evidence": str(evidence_path),
        "unified_cloud": str(unified_positions_path),
        "dwg_files": [str(d) for d in dwgs],
        "album_dir": str(album_dir),
    }


if __name__ == "__main__":
    run_unified_pipeline()
