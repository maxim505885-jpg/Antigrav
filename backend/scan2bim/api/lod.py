"""Streaming LOD Octree endpoints for web 3D viewer."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..db import one
from ..pointdata.octree import StreamingLodBuilder
from ..storage import cloud_paths
from ..config import DATA_DIR

router = APIRouter(tags=["lod"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _find_unified_release_dir() -> Path:
    candidates = [
        DATA_DIR / "output" / "unified_stitched_release",
        PROJECT_ROOT / "data" / "output" / "unified_stitched_release",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def _get_or_build_lod_for_unified() -> tuple[Path, dict[str, Any]]:
    """Return LOD directory and manifest for unified stitched cloud."""
    unified_dir = _find_unified_release_dir()
    lod_dir = unified_dir / "lod"
    manifest_path = lod_dir / "lod_manifest.json"
    
    if manifest_path.is_file():
        try:
            return lod_dir, json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Build LOD pyramid for unified cloud
    pos_path = unified_dir / "unified_cloud" / "positions.npy"
    if not pos_path.is_file():
        raise HTTPException(status_code=404, detail="Сводное облако точек не найдено на сервере")

    builder = StreamingLodBuilder()
    manifest = builder.build_lod_pyramid(pos_path, lod_dir, cloud_id="unified")
    return lod_dir, manifest


def _get_or_build_lod_for_cloud(cloud_id: str) -> tuple[Path, dict[str, Any]]:
    """Return LOD directory and manifest for a specific registered cloud."""
    if cloud_id in ("unified", "unified_stitched", "stitched"):
        return _get_or_build_lod_for_unified()

    row = one("SELECT project_id, name, status FROM clouds WHERE id = ?", (cloud_id,))
    if not row:
        raise HTTPException(status_code=404, detail=f"Облако {cloud_id} не найдено")

    if row["status"] != "ready":
        raise HTTPException(status_code=409, detail=f"Облако {cloud_id} еще не готово (статус: {row['status']})")

    paths = cloud_paths(row["project_id"], cloud_id)
    lod_dir = paths["dir"] / "lod"
    manifest_path = lod_dir / "lod_manifest.json"

    if manifest_path.is_file():
        try:
            return lod_dir, json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    pos_path = paths["positions"]
    if not pos_path.is_file():
        raise HTTPException(status_code=404, detail="Файл positions.npy не найден")

    col_path = paths["colors"] if paths["colors"].is_file() else None
    builder = StreamingLodBuilder()
    manifest = builder.build_lod_pyramid(pos_path, lod_dir, colors_path=col_path, cloud_id=cloud_id)
    return lod_dir, manifest


@router.get("/clouds/{cloud_id}/lod/manifest")
def get_cloud_lod_manifest(cloud_id: str) -> dict[str, Any]:
    """Get streaming LOD octree manifest with levels, camera distance thresholds, and bounds."""
    _, manifest = _get_or_build_lod_for_cloud(cloud_id)
    return manifest


@router.get("/clouds/{cloud_id}/lod/{level}")
def get_cloud_lod_binary(cloud_id: str, level: int):
    """Stream binary point slice for the requested LOD level (stride 15: float32 x,y,z + uint8 r,g,b)."""
    lod_dir, manifest = _get_or_build_lod_for_cloud(cloud_id)
    
    valid_levels = {item["level"]: item["file"] for item in manifest.get("levels", [])}
    if level not in valid_levels:
        raise HTTPException(status_code=404, detail=f"Уровень LOD {level} не найден (доступны: {sorted(valid_levels.keys())})")

    bin_path = lod_dir / valid_levels[level]
    if not bin_path.is_file():
        raise HTTPException(status_code=404, detail=f"Файл бинарного среза {bin_path.name} не найден")

    return FileResponse(
        bin_path,
        media_type="application/octet-stream",
        headers={"Cache-Control": "public, max-age=3600"},
    )
