"""Choose exact source scans or a verified spatial index for point queries."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .index import IndexedPointProvider
from .provider import NpyPointProvider, PointQuery


def select_query_provider(
    source: NpyPointProvider,
    index_directory: str | Path | None,
    query: PointQuery,
    *,
    max_candidate_fraction: float = IndexedPointProvider.DEFAULT_MAX_CANDIDATE_FRACTION,
) -> tuple[Any, dict[str, int | str]]:
    """Use an index only when its source fingerprint matches and its query is sparse.

    Invalid, incomplete, or stale indexes safely fall back to the exact linear
    reader. Broad requests also use the linear reader because random cell reads
    are slower when they touch a large fraction of the cloud.
    """
    if index_directory is None:
        return source, {"strategy": "linear_no_index", "candidate_rows_estimate": source.count}
    directory = Path(index_directory)
    if not (directory / "manifest.json").is_file():
        return source, {"strategy": "linear_no_valid_index", "candidate_rows_estimate": source.count}
    try:
        indexed = IndexedPointProvider(source, directory)
        estimate = indexed.estimate_candidate_rows(query)
        if indexed.should_use_index(query, max_candidate_fraction=max_candidate_fraction):
            return indexed, {"strategy": "spatial_index", "candidate_rows_estimate": estimate}
        return source, {"strategy": "linear_broad_query", "candidate_rows_estimate": estimate}
    except (OSError, ValueError, KeyError, TypeError):
        return source, {"strategy": "linear_invalid_index", "candidate_rows_estimate": source.count}
