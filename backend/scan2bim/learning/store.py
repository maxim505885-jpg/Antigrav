"""Storage of engineer-reviewed examples and their source points."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..db import dumps, execute, loads, new_id, one, rows, utcnow
from ..storage import cloud_paths, project_dir
from .features import features_from_element

CHUNK = 2_000_000
MAX_SAMPLE_POINTS = 20000


def _cloud(cloud_id: str) -> dict[str, Any]:
    cloud = one("SELECT * FROM clouds WHERE id = ?", (cloud_id,))
    if not cloud:
        raise ValueError(f"cloud {cloud_id} not found")
    return cloud


def extract_element_points(
    cloud_id: str,
    bbox: dict[str, Any],
    limit: int = MAX_SAMPLE_POINTS,
    margin: float = 0.05,
) -> np.ndarray:
    cloud = _cloud(cloud_id)
    paths = cloud_paths(cloud["project_id"], cloud_id)
    if not paths["positions"].exists():
        return np.empty((0, 3), dtype=np.float32)
    origin = np.array(
        [cloud["origin_x"] or 0.0, cloud["origin_y"] or 0.0, cloud["origin_z"] or 0.0],
        dtype=np.float64,
    )
    try:
        mn = np.array(bbox["min"], dtype=np.float64) - origin - margin
        mx = np.array(bbox["max"], dtype=np.float64) - origin + margin
    except Exception:
        return np.empty((0, 3), dtype=np.float32)
    arr = np.load(paths["positions"], mmap_mode="r")
    parts: list[np.ndarray] = []
    found = 0
    for start in range(0, arr.shape[0], CHUNK):
        chunk = np.asarray(arr[start : start + CHUNK])
        mask = np.all(chunk >= mn, axis=1) & np.all(chunk <= mx, axis=1)
        if not np.any(mask):
            continue
        picked = chunk[mask]
        if len(picked) > limit:
            idx = np.random.default_rng(3).choice(len(picked), size=limit, replace=False)
            picked = picked[idx]
        parts.append(picked.astype(np.float32) + origin.astype(np.float32))
        found += len(picked)
        if found >= limit:
            break
    if not parts:
        return np.empty((0, 3), dtype=np.float32)
    points = np.concatenate(parts)
    if len(points) > limit:
        idx = np.random.default_rng(4).choice(len(points), size=limit, replace=False)
        points = points[idx]
    return points


def create_sample(
    project_id: str,
    cloud_id: str,
    element: dict[str, Any],
    class_name: str | None = None,
    split: str = "train",
    source: str = "engineer",
    element_id: str | None = None,
) -> dict[str, Any]:
    sample_id = new_id()
    label = class_name or element.get("class_name") or "unknown"
    features = features_from_element(element)
    points_path = project_dir(project_id) / "training" / f"{sample_id}.npy"
    points_path.parent.mkdir(parents=True, exist_ok=True)
    points = extract_element_points(cloud_id, element.get("bbox") or {})
    np.save(points_path, points)
    execute(
        """
        INSERT INTO training_samples
        (id, project_id, cloud_id, element_id, class_name, features_json, points_path, split, source, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            sample_id,
            project_id,
            cloud_id,
            element_id or element.get("id"),
            label,
            dumps(features),
            str(points_path),
            split,
            source,
            utcnow(),
        ),
    )
    return {
        "id": sample_id,
        "project_id": project_id,
        "cloud_id": cloud_id,
        "element_id": element_id or element.get("id"),
        "class_name": label,
        "features": features,
        "split": split,
        "source": source,
        "point_count": int(len(points)),
        "created_at": utcnow(),
    }


def list_samples(project_id: str, split: str | None = None) -> list[dict[str, Any]]:
    if split:
        records = rows(
            "SELECT * FROM training_samples WHERE project_id = ? AND split = ? ORDER BY created_at DESC",
            (project_id, split),
        )
    else:
        records = rows(
            "SELECT * FROM training_samples WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
    result = []
    for rec in records:
        rec = dict(rec)
        rec["features"] = loads(rec.get("features_json"), {})
        rec.pop("features_json", None)
        result.append(rec)
    return result


def samples_for_training(project_id: str) -> list[dict[str, Any]]:
    return [sample for sample in list_samples(project_id) if sample.get("source") != "undone"]


def similar_samples(project_id: str, features: dict[str, float], k: int = 5) -> list[dict[str, Any]]:
    samples = [sample for sample in list_samples(project_id) if sample.get("source") != "undone"]
    if not samples:
        return []
    names = list(features.keys())
    X = np.asarray(
        [[float(s["features"].get(name, 0.0)) for name in names] for s in samples],
        dtype=np.float64,
    )
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-9] = 1.0
    v = (np.asarray([float(features.get(name, 0.0)) for name in names]) - mean) / std
    distances = np.linalg.norm((X - mean) / std - v, axis=1)
    order = np.argsort(distances)[:k]
    out = []
    for idx in order:
        sample = dict(samples[int(idx)])
        sample["distance"] = round(float(distances[int(idx)]), 5)
        sample["features"] = sample["features"]
        out.append(sample)
    return out
