"""Choose exact source scans or a verified spatial index for point queries."""
from __future__ import annotations

import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from .index import IndexedPointProvider, build_index
from .provider import NpyPointProvider, PointQuery

_AUTO_INDEX_MIN_POINTS = 1_000_000
_AUTO_INDEX_MAX_POINTS = 50_000_000
_AUTO_INDEX_RESERVE_BYTES = 128 * 1024 * 1024
_index_locks_guard = threading.Lock()
_index_locks: dict[str, threading.Lock] = {}


def _index_lock(directory: Path) -> threading.Lock:
    key = str(directory.resolve())
    with _index_locks_guard:
        return _index_locks.setdefault(key, threading.Lock())


def _try_build_index(
    source: NpyPointProvider, directory: Path,
) -> tuple[bool, float | None, str | None]:
    """Build an index for a manageable cloud without exposing partial output."""
    if source.count < _AUTO_INDEX_MIN_POINTS:
        return False, None, "point_count_below_threshold"
    if source.count > _AUTO_INDEX_MAX_POINTS:
        return False, None, "point_limit_exceeded"
    try:
        free_bytes = shutil.disk_usage(directory.parent).free
    except OSError:
        return False, None, "disk_space_unavailable"
    estimated_bytes = source.count * np.dtype(np.int64).itemsize + _AUTO_INDEX_RESERVE_BYTES
    if free_bytes < estimated_bytes:
        return False, None, "insufficient_disk_space"

    lock = _index_lock(directory)
    with lock:
        if (directory / "manifest.json").is_file():
            return False, 0.0, None
        # An existing incomplete directory may belong to a previous interrupted
        # or external build. Leave it untouched and use the exact linear reader.
        if directory.exists():
            return False, None, "incomplete_index_exists"

        staging = directory.with_name(f"{directory.name}.building-{uuid.uuid4().hex}")
        started = time.perf_counter()
        try:
            metadata = build_index(source, staging)
            # Validate all source and index metadata before publishing the
            # manifest-bearing directory to concurrent readers.
            IndexedPointProvider(source, staging)
            if directory.exists():
                return False, None, "index_created_concurrently"
            staging.replace(directory)
            return True, round(time.perf_counter() - started, 3), None
        except (OSError, RuntimeError, ValueError, KeyError, TypeError):
            return False, None, "index_build_failed"
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)


def select_query_provider(
    source: NpyPointProvider,
    index_directory: str | Path | None,
    query: PointQuery,
    *,
    max_candidate_fraction: float = IndexedPointProvider.DEFAULT_MAX_CANDIDATE_FRACTION,
    build_missing_index: bool = False,
) -> tuple[Any, dict[str, int | float | str | bool]]:
    """Use an index only when its source fingerprint matches and its query is sparse.

    Invalid, incomplete, or stale indexes safely fall back to the exact linear
    reader. Broad requests also use the linear reader because random cell reads
    are slower when they touch a large fraction of the cloud.
    """
    if index_directory is None:
        return source, {"strategy": "linear_no_index", "candidate_rows_estimate": source.count}
    directory = Path(index_directory)
    if not (directory / "manifest.json").is_file():
        if build_missing_index and not directory.exists():
            built, build_seconds, reason = _try_build_index(source, directory)
            if built or (directory / "manifest.json").is_file():
                try:
                    indexed = IndexedPointProvider(source, directory)
                    estimate = indexed.estimate_candidate_rows(query)
                    if indexed.should_use_index(query, max_candidate_fraction=max_candidate_fraction):
                        return indexed, {
                            "strategy": "spatial_index",
                            "candidate_rows_estimate": estimate,
                            "index_built": bool(built),
                            "index_build_seconds": build_seconds or 0,
                        }
                    return source, {
                        "strategy": "linear_broad_query",
                        "candidate_rows_estimate": estimate,
                        "index_built": bool(built),
                        "index_build_seconds": build_seconds or 0,
                    }
                except (OSError, ValueError, KeyError, TypeError):
                    return source, {"strategy": "linear_invalid_index", "candidate_rows_estimate": source.count}
            return source, {
                "strategy": "linear_index_unavailable",
                "candidate_rows_estimate": source.count,
                "index_built": False,
                "index_build_reason": reason or "index_unavailable",
            }
        return source, {"strategy": "linear_no_valid_index", "candidate_rows_estimate": source.count}
    try:
        indexed = IndexedPointProvider(source, directory)
        estimate = indexed.estimate_candidate_rows(query)
        if indexed.should_use_index(query, max_candidate_fraction=max_candidate_fraction):
            return indexed, {"strategy": "spatial_index", "candidate_rows_estimate": estimate}
        return source, {"strategy": "linear_broad_query", "candidate_rows_estimate": estimate}
    except (OSError, ValueError, KeyError, TypeError):
        return source, {"strategy": "linear_invalid_index", "candidate_rows_estimate": source.count}
