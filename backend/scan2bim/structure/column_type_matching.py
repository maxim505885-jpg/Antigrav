"""Explainable reuse of explicitly confirmed project section prototypes."""
from __future__ import annotations

import math
from typing import Any

from .column_types import _finite_positive, _within_tolerance, column_descriptor


def match_project_column_types(
    project_id: str,
    elements: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    source_elements: list[dict[str, Any]],
    *,
    linear_tolerance_m: float,
    relative_tolerance: float = 0.01,
) -> dict[str, Any]:
    """Return review suggestions; never assign a type or replace measurements.

    Current members must still support their confirmed prototype. Deleted,
    rejected or changed source members disable reuse until engineering review.
    Coverage 0.5 is a provisional visibility flag, not an accuracy guarantee.
    Even a unique high-coverage dimensional match requires explicit review.
    """
    for tolerance in (linear_tolerance_m, relative_tolerance):
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("matching tolerances must be finite and non-negative")
    types = sorted((item for item in catalog
        if item.get("project_id") == project_id and item.get("status") == "confirmed"),
        key=lambda item: item["id"])
    sources = {item["id"]: item for item in source_elements if item.get("project_id") == project_id}
    assigned = {member for item in types for member in item["member_element_ids"]}
    valid_types, issues = [], []

    def compatible(descriptor, sides, morphology):
        return descriptor["eligible"] and descriptor["morphology"] == morphology and all(
            _within_tolerance(descriptor[f"{side}_side_m"], sides[side], linear_tolerance_m, relative_tolerance)
            for side in ("long", "short"))

    for item in types:
        prototype = item.get("prototype") or {}
        sides = prototype.get("representative_sides_m") or {}
        morphology = prototype.get("morphology", "unknown")
        reasons = []
        members = item["member_element_ids"]
        if not members:
            reasons.append("no_active_members")
        if not all(_finite_positive(sides.get(side)) is not None for side in ("long", "short")):
            reasons.append("invalid_prototype")
        else:
            sides = {side: float(sides[side]) for side in ("long", "short")}
        source_cloud_ids = set()
        if not reasons:
            for member in members:
                source = sources.get(member)
                if source is None:
                    reasons.append("missing_source_member")
                elif source.get("review_status") == "rejected":
                    reasons.append("rejected_source_member")
                elif not compatible(column_descriptor(source), sides, morphology):
                    reasons.append("source_prototype_conflict")
                else:
                    source_cloud_ids.add(source["cloud_id"])
        if reasons:
            issues.append({"type_id": item["id"], "mark": item["mark"], "reasons": sorted(set(reasons))})
        else:
            valid_types.append((item, sides, morphology, sorted(source_cloud_ids)))

    suggestions = []
    for element in sorted(elements, key=lambda item: item["id"]):
        if (element.get("project_id") != project_id or element.get("class_name") != "column"
            or element["id"] in assigned or element.get("review_status") == "rejected"):
            continue
        descriptor = column_descriptor(element)
        matches = []
        if descriptor["eligible"]:
            for item, sides, morphology, clouds in valid_types:
                if compatible(descriptor, sides, morphology):
                    matches.append({"type_id": item["id"], "mark": item["mark"],
                        "representative_sides_m": dict(sides), "source_cloud_ids": clouds,
                        "residuals_m": {f"{side}_side_m": descriptor[f"{side}_side_m"] - sides[side]
                            for side in ("long", "short")}})
        reasons = list(descriptor["reasons"])
        coverage = descriptor["evidence_coverage"]
        if coverage is None:
            reasons.append("unknown_coverage")
        elif coverage < 0.5:
            reasons.append("low_coverage")
        if descriptor["morphology"] == "unknown":
            reasons.append("unknown_morphology")
        if (element.get("dimensions") or {}).get("review_conflict_with"):
            reasons.append("recognition_conflict")
        if not descriptor["eligible"]:
            status = "ineligible"
        elif not matches:
            status = "unknown"
        elif len(matches) > 1:
            status = "ambiguous"
        elif reasons:
            status = "insufficient_evidence"
        else:
            status = "match"
        suggestions.append({"element_id": element["id"], "status": status,
            "review_required": True, "matches": matches, "reasons": reasons,
            "evidence_coverage": coverage, "morphology": descriptor["morphology"],
            "measurement_sources": descriptor["measurement_sources"]})
    return {"suggestions": suggestions, "catalog_issues": issues,
        "visibility_threshold": 0.5, "threshold_status": "provisional"}
