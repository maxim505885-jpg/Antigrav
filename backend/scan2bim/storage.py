"""Filesystem layout and safe helpers.

Original uploads are stored under the project directory and are never modified.
Imported-by-path files stay where they are; only their metadata is recorded.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from .config import PROJECTS_DIR
from .db import new_id

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str, fallback: str = "cloud") -> str:
    name = Path(name).name
    cleaned = _SAFE.sub("_", name).strip("._")
    return cleaned or fallback


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def cloud_dir(project_id: str, cloud_id: str) -> Path:
    return project_dir(project_id) / "clouds" / cloud_id


def ensure_cloud_dir(project_id: str, cloud_id: str) -> Path:
    path = cloud_dir(project_id, cloud_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def cloud_paths(project_id: str, cloud_id: str) -> dict[str, Path]:
    base = cloud_dir(project_id, cloud_id)
    return {
        "dir": base,
        "source": base / "source",
        "positions": base / "positions.npy",
        "colors": base / "colors.npy",
        "intensity": base / "intensity.npy",
        "preview": base / "preview.bin",
        "meta": base / "meta.json",
    }


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, indent=2)
        Path(tmp).replace(path)
    finally:
        if Path(tmp).exists():
            Path(tmp).unlink()


def sha256_file(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def copy_stream(src: BinaryIO, dest: Path, chunk: int = 8 * 1024 * 1024) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with dest.open("wb") as out:
        while True:
            block = src.read(chunk)
            if not block:
                break
            out.write(block)
            total += len(block)
    return total


def free_space_bytes(path: Path = PROJECTS_DIR) -> int:
    target = path
    while not target.exists() and target.parent != target:
        target = target.parent
    return shutil.disk_usage(target).free


def new_export_dir(project_id: str, prefix: str) -> tuple[str, Path]:
    export_id = new_id()[:12]
    path = project_dir(project_id) / "exports" / f"{prefix}_{export_id}"
    path.mkdir(parents=True, exist_ok=True)
    return export_id, path
