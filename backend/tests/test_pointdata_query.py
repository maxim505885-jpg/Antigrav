"""Indexed query selection preserves exact source rows and safe fallbacks."""
from __future__ import annotations

import os

import numpy as np
import pytest

import scan2bim.pointdata.query as point_query_module
from scan2bim.pointdata import NpyPointProvider, PointQuery, select_query_provider
from scan2bim.pointdata.index import build_index


def _rows(provider, query):
    batches = list(provider.iter_points(query))
    if not batches:
        return np.empty(0, dtype=np.int64), np.empty((0, 3), dtype=np.float64)
    rows = np.concatenate([batch.source_indices for batch in batches])
    xyz = np.concatenate([batch.xyz for batch in batches])
    order = np.argsort(rows)
    return rows[order], xyz[order]


def test_sparse_query_uses_verified_index_and_matches_linear_source(tmp_path):
    points_path = tmp_path / "positions.npy"
    color_path = tmp_path / "colors.npy"
    points = np.array([[x, y, z] for x in range(100) for y in range(20) for z in range(10)], dtype=np.float32)
    np.save(points_path, points)
    np.save(color_path, np.arange(len(points) * 3, dtype=np.uint8).reshape(-1, 3))
    source = NpyPointProvider(points_path, origin=(1000, -2000, 30), colors_path=color_path, chunk_size=17)
    index_dir = tmp_path / "spatial-index-v1"
    build_index(source, index_dir, cell_size=10)
    query = PointQuery((1000, -2000, 30, 1003, -1997, 32))

    selected, evidence = select_query_provider(source, index_dir, query)

    assert evidence["strategy"] == "spatial_index"
    assert evidence["candidate_rows_estimate"] < source.count * 0.2
    for actual, expected in zip(_rows(selected, query), _rows(source, query)):
        np.testing.assert_array_equal(actual, expected)


def test_broad_query_uses_linear_reader_and_reports_estimate(tmp_path):
    points_path = tmp_path / "positions.npy"
    np.save(points_path, np.array([[x, y, z] for x in range(8) for y in range(4) for z in range(2)], dtype=np.float32))
    source = NpyPointProvider(points_path, origin=(0, 0, 0), chunk_size=11)
    index_dir = tmp_path / "index"
    build_index(source, index_dir, cell_size=2)
    query = PointQuery((0, 0, 0, 7, 3, 1))

    selected, evidence = select_query_provider(source, index_dir, query)

    assert selected is source
    assert evidence == {"strategy": "linear_broad_query", "candidate_rows_estimate": source.count}


def test_missing_or_stale_index_falls_back_to_exact_linear_reader(tmp_path):
    points_path = tmp_path / "positions.npy"
    np.save(points_path, np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2]], dtype=np.float32))
    source = NpyPointProvider(points_path, origin=(0, 0, 0))
    query = PointQuery((0, 0, 0, 1, 1, 1))

    missing, missing_evidence = select_query_provider(source, tmp_path / "missing", query)
    assert missing is source
    assert missing_evidence["strategy"] == "linear_no_valid_index"

    index_dir = tmp_path / "index"
    build_index(source, index_dir)
    original = points_path.stat()
    os.utime(points_path, ns=(original.st_atime_ns, original.st_mtime_ns + 10_000_000_000))
    stale, stale_evidence = select_query_provider(source, index_dir, query)
    assert stale is source
    assert stale_evidence["strategy"] == "linear_invalid_index"
    rows, xyz = _rows(stale, query)
    np.testing.assert_array_equal(rows, [0, 1])
    np.testing.assert_array_equal(xyz, [[0, 0, 0], [1, 1, 1]])


def test_opt_in_builds_missing_index_atomically_and_keeps_exact_rows(tmp_path, monkeypatch):
    points_path = tmp_path / "positions.npy"
    points = np.array(
        [[x, y, z] for x in range(30) for y in range(12) for z in range(8)],
        dtype=np.float32,
    )
    np.save(points_path, points)
    source = NpyPointProvider(points_path, origin=(10, 20, 30), chunk_size=71)
    index_dir = tmp_path / "spatial-index-v1"
    query = PointQuery((12, 22, 31, 14, 24, 34))
    monkeypatch.setattr(point_query_module, "_AUTO_INDEX_MIN_POINTS", 1)

    selected, evidence = select_query_provider(
        source, index_dir, query, build_missing_index=True,
    )

    assert evidence["strategy"] == "spatial_index"
    assert evidence["index_built"] is True
    assert (index_dir / "manifest.json").is_file()
    for actual, expected in zip(_rows(selected, query), _rows(source, query)):
        np.testing.assert_array_equal(actual, expected)


def test_auto_index_limit_keeps_exact_linear_fallback(tmp_path, monkeypatch):
    points_path = tmp_path / "positions.npy"
    np.save(points_path, np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2]], dtype=np.float32))
    source = NpyPointProvider(points_path, origin=(0, 0, 0))
    index_dir = tmp_path / "spatial-index-v1"
    monkeypatch.setattr(point_query_module, "_AUTO_INDEX_MIN_POINTS", 1)
    monkeypatch.setattr(point_query_module, "_AUTO_INDEX_MAX_POINTS", 2)

    selected, evidence = select_query_provider(
        source, index_dir, PointQuery((0, 0, 0, 1, 1, 1)), build_missing_index=True,
    )

    assert selected is source
    assert evidence["strategy"] == "linear_index_unavailable"
    assert evidence["index_build_reason"] == "point_limit_exceeded"
    assert not index_dir.exists()


def test_auto_index_skips_small_clouds_without_affecting_exact_fallback(tmp_path):
    points_path = tmp_path / "positions.npy"
    np.save(points_path, np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float32))
    source = NpyPointProvider(points_path, origin=(0, 0, 0))
    index_dir = tmp_path / "spatial-index-v1"

    selected, evidence = select_query_provider(
        source, index_dir, PointQuery((0, 0, 0, 1, 1, 1)), build_missing_index=True,
    )

    assert selected is source
    assert evidence["strategy"] == "linear_index_unavailable"
    assert evidence["index_build_reason"] == "point_count_below_threshold"
    assert not index_dir.exists()


def test_auto_index_failure_cleans_only_its_staging_directory(tmp_path, monkeypatch):
    points_path = tmp_path / "positions.npy"
    np.save(points_path, np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2]], dtype=np.float32))
    source = NpyPointProvider(points_path, origin=(0, 0, 0))
    index_dir = tmp_path / "spatial-index-v1"
    monkeypatch.setattr(point_query_module, "_AUTO_INDEX_MIN_POINTS", 1)

    def fail_build(_source, staging, **kwargs):
        os.makedirs(staging)
        with open(os.path.join(staging, "partial-rows.tmp"), "wb") as partial:
            partial.write(b"partial")
        raise OSError("simulated disk failure")

    monkeypatch.setattr(point_query_module, "build_index", fail_build)
    selected, evidence = select_query_provider(
        source, index_dir, PointQuery((0, 0, 0, 1, 1, 1)), build_missing_index=True,
    )

    assert selected is source
    assert evidence["strategy"] == "linear_index_unavailable"
    assert evidence["index_build_reason"] == "index_build_failed"
    assert not index_dir.exists()
    assert list(tmp_path.glob("spatial-index-v1.building-*")) == []


def test_auto_index_leaves_preexisting_incomplete_directory_untouched(tmp_path):
    points_path = tmp_path / "positions.npy"
    np.save(points_path, np.array([[0, 0, 0], [1, 1, 1], [2, 2, 2]], dtype=np.float32))
    source = NpyPointProvider(points_path, origin=(0, 0, 0))
    index_dir = tmp_path / "spatial-index-v1"
    index_dir.mkdir()
    sentinel = index_dir / "operator-file.txt"
    sentinel.write_text("keep", encoding="utf-8")

    selected, evidence = select_query_provider(
        source, index_dir, PointQuery((0, 0, 0, 1, 1, 1)), build_missing_index=True,
    )

    assert selected is source
    assert evidence["strategy"] == "linear_no_valid_index"
    assert sentinel.read_text(encoding="utf-8") == "keep"
