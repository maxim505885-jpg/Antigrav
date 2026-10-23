"""Keep manual review decisions safe when geometric recognition is rerun."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from typing import Any

REVIEWED_STATUSES = {"confirmed", "corrected", "rejected"}
REVIEW_CONFLICT_OVERLAP = 0.5


@dataclass(frozen=True)
class ReconciliationResult:
    candidates: list[dict[str, Any]]
    preserved_ids: list[str]
    reused_candidate_ids: list[str]
    conflicts: list[dict[str, Any]]


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None
    return value


def _geometry_key(value: Any) -> str:
    return json.dumps(_decode_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _box(bbox_value: Any) -> tuple[list[float], list[float]] | None:
    bbox = _decode_json(bbox_value)
    if not isinstance(bbox, dict):
        return None
    try:
        low = [float(v) for v in bbox["min"]]
        high = [float(v) for v in bbox["max"]]
    except (KeyError, TypeError, ValueError):
        return None
    if len(low) != 3 or len(high) != 3 or not all(math.isfinite(v) for v in low + high):
        return None
    if any(b < a for a, b in zip(low, high)):
        return None
    return low, high


def _overlap_of_smaller(a_value: Any, b_value: Any) -> float:
    a, b = _box(a_value), _box(b_value)
    if a is None or b is None:
        return 0.0
    a_low, a_high = a
    b_low, b_high = b
    inter = [max(0.0, min(ah, bh) - max(al, bl)) for al, ah, bl, bh in zip(a_low, a_high, b_low, b_high)]
    a_size = [ah - al for al, ah in zip(a_low, a_high)]
    b_size = [bh - bl for bl, bh in zip(b_low, b_high)]
    a_volume = math.prod(a_size)
    b_volume = math.prod(b_size)
    smaller_volume = min(a_volume, b_volume)
    if smaller_volume <= 1e-12:
        return 0.0
    return math.prod(inter) / smaller_volume


def protect_reviewed_candidates(
    candidates: list[dict[str, Any]],
    reviewed_elements: list[dict[str, Any]],
    reusable_candidates: list[dict[str, Any]] | None = None,
) -> ReconciliationResult:
    """Preserve decisions and identities for exact repeat detections.

    Reviewed elements themselves are never changed. Similar-but-not-identical
    candidates remain visible and carry the IDs of protected elements they may
    conflict with, so a correction is not silently overwritten or hidden.
    Exact unreviewed matches reuse their database ID so existing feedback/undo
    history remains attached to the source-linked candidate after rerunning.
    """
    protected = [
        item for item in reviewed_elements
        if item.get("review_status") in REVIEWED_STATUSES
    ]
    exact: dict[tuple[str, str], list[str]] = {}
    for item in protected:
        exact.setdefault(
            (str(item.get("class_name") or ""), _geometry_key(item.get("geometry_json"))), []
        ).append(str(item["id"]))

    reusable: dict[tuple[str, str], list[str]] = {}
    for item in reusable_candidates or []:
        if item.get("review_status") not in {None, "unreviewed"}:
            continue
        reusable.setdefault(
            (str(item.get("class_name") or ""), _geometry_key(item.get("geometry_json"))), []
        ).append(str(item["id"]))

    kept: list[dict[str, Any]] = []
    preserved_ids: list[str] = []
    reused_candidate_ids: list[str] = []
    conflicts: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        key = (str(candidate.get("class_name") or ""), _geometry_key(candidate.get("geometry")))
        matches = exact.get(key, [])
        if matches:
            preserved_ids.extend(matches)
            continue

        prior_ids = reusable.get(key, [])
        copied = deepcopy(candidate)
        if prior_ids:
            copied["id"] = prior_ids.pop(0)
            reused_candidate_ids.append(str(copied["id"]))

        overlapping = [
            str(item["id"])
            for item in protected
            if _overlap_of_smaller(candidate.get("bbox"), item.get("bbox_json")) >= REVIEW_CONFLICT_OVERLAP
        ]
        if overlapping:
            copied.setdefault("dimensions", {})["review_conflict_with"] = overlapping
            copied["metadata"] = {
                **(copied.get("metadata") or {}),
                "review_conflict": {
                    "status": "requires_review",
                    "protected_element_ids": overlapping,
                },
            }
            conflicts.append({"candidate_index": index, "protected_ids": overlapping})
        kept.append(copied)

    return ReconciliationResult(
        candidates=kept,
        preserved_ids=sorted(set(preserved_ids)),
        reused_candidate_ids=sorted(set(reused_candidate_ids)),
        conflicts=conflicts,
    )
