"""Measured section descriptors and type suggestions for structural columns."""
from __future__ import annotations

import math
from hashlib import sha256
from statistics import median
from typing import Any


_SECTION_EVIDENCE_FIELDS = (
    "section_profile",
    "section_fill",
    "section_coverage",
    "base_area_m2",
    "top_area_m2",
)


def _finite_positive(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _measured_side(
    geometry: dict[str, Any], dimensions: dict[str, Any], box_key: str, dimension_key: str
) -> tuple[float | None, str | None, bool]:
    """Return a side, its provenance, and whether the preferred value was invalid."""
    sizes = geometry.get("sizes")
    if isinstance(sizes, dict) and box_key in sizes:
        value = _finite_positive(sizes[box_key])
        return value, f"geometry.sizes.{box_key}" if value is not None else None, value is None

    if dimension_key in dimensions:
        value = _finite_positive(dimensions[dimension_key])
        return value, f"dimensions.{dimension_key}" if value is not None else None, value is None

    return None, None, False


def _canonical_angle(length: float, thickness: float, angle: float | None) -> float | None:
    """Angle of the long side, normalized for the 180-degree rectangle symmetry."""
    if angle is None:
        return None
    long_axis = angle if length >= thickness else angle + math.pi / 2
    normalized = long_axis % math.pi
    return 0.0 if math.isclose(normalized, math.pi, abs_tol=1e-12) else normalized


def column_descriptor(element: dict[str, Any]) -> dict[str, Any]:
    """Describe a column using only measured side lengths and explicit evidence.

    The descriptor does not assign a catalogue profile and never modifies the
    source element. Missing or invalid dimensions remain visible as ineligible
    proposals rather than being filled from a nominal type.
    """
    geometry = element.get("geometry") if isinstance(element.get("geometry"), dict) else {}
    dimensions = element.get("dimensions") if isinstance(element.get("dimensions"), dict) else {}
    reasons: list[str] = []

    if not str(element.get("id") or "").strip():
        reasons.append("missing_element_id")
    if element.get("class_name") != "column":
        reasons.append("not_a_column")
    if element.get("measured") is not True:
        reasons.append("not_measured")
    if element.get("inferred") is True:
        reasons.append("inferred_geometry")

    length, length_source, invalid_length = _measured_side(
        geometry, dimensions, "length", "length_m"
    )
    thickness, thickness_source, invalid_thickness = _measured_side(
        geometry, dimensions, "thickness", "thickness_m"
    )
    if length is None:
        reasons.append("invalid_long_side" if invalid_length else "missing_long_side")
    if thickness is None:
        reasons.append("invalid_short_side" if invalid_thickness else "missing_short_side")

    angle_value: float | None = None
    angle_source: str | None = None
    if "rotation_z" in geometry:
        try:
            candidate_angle = float(geometry["rotation_z"])
        except (TypeError, ValueError):
            candidate_angle = math.nan
        if math.isfinite(candidate_angle):
            angle_value = candidate_angle
            angle_source = "geometry.rotation_z"
        else:
            reasons.append("invalid_rotation")

    coverage: float | None = None
    if "section_coverage" in dimensions:
        try:
            candidate_coverage = float(dimensions["section_coverage"])
        except (TypeError, ValueError):
            candidate_coverage = math.nan
        if math.isfinite(candidate_coverage) and 0 <= candidate_coverage <= 1:
            coverage = candidate_coverage

    evidence = {
        key: dimensions[key]
        for key in _SECTION_EVIDENCE_FIELDS
        if key in dimensions
    }
    if length is None or thickness is None:
        long_side = short_side = None
        area = None
        long_source = short_source = None
        long_axis_angle = None
    else:
        if length >= thickness:
            long_side, short_side = length, thickness
            long_source, short_source = length_source, thickness_source
        else:
            long_side, short_side = thickness, length
            long_source, short_source = thickness_source, length_source
        area = length * thickness
        long_axis_angle = _canonical_angle(length, thickness, angle_value)

    return {
        "element_id": str(element.get("id") or ""),
        "eligible": not reasons,
        "reasons": reasons,
        "long_side_m": long_side,
        "short_side_m": short_side,
        "area_m2": area,
        "long_axis_angle_rad": long_axis_angle,
        "morphology": str(dimensions.get("column_type") or "unknown"),
        "morphology_evidence": evidence,
        "evidence_coverage": coverage,
        "measurement_sources": {
            "long_side_m": long_source,
            "short_side_m": short_source,
            "rotation_z": angle_source,
        },
    }


def _within_tolerance(a: float, b: float, linear_tolerance_m: float, relative_tolerance: float) -> bool:
    difference = abs(a - b)
    threshold = max(linear_tolerance_m, relative_tolerance * max(abs(a), abs(b)))
    return difference <= threshold or math.isclose(difference, threshold, rel_tol=1e-12, abs_tol=1e-12)


def _proposal_id(member_ids: list[str], morphology: str, long_side: float, short_side: float) -> str:
    material = "|".join((morphology, f"{long_side:.9f}", f"{short_side:.9f}", *member_ids))
    return f"column-type-{sha256(material.encode('utf-8')).hexdigest()[:12]}"


def propose_column_types(
    elements: list[dict[str, Any]],
    *,
    linear_tolerance_m: float,
    relative_tolerance: float = 0.01,
) -> list[dict[str, Any]]:
    """Cluster eligible measured columns into review-only, repeatable proposals.

    Matching uses the maximum of absolute and relative tolerance independently
    for each measured side. It never uses position or orientation, and never
    changes the member's source geometry. Morphology labels must agree exactly;
    uncertain ``unknown`` geometry therefore cannot merge with a known profile.
    """
    if not math.isfinite(linear_tolerance_m) or linear_tolerance_m < 0:
        raise ValueError("linear_tolerance_m must be a finite non-negative value")
    if not math.isfinite(relative_tolerance) or relative_tolerance < 0:
        raise ValueError("relative_tolerance must be a finite non-negative value")

    descriptors = [column_descriptor(element) for element in elements]
    descriptors = [descriptor for descriptor in descriptors if descriptor["eligible"]]
    descriptors.sort(key=lambda descriptor: (
        descriptor["morphology"],
        descriptor["long_side_m"],
        descriptor["short_side_m"],
        descriptor["element_id"],
    ))

    groups: list[list[dict[str, Any]]] = []
    for descriptor in descriptors:
        matches: list[tuple[float, int]] = []
        for index, group in enumerate(groups):
            representative_long = median(item["long_side_m"] for item in group)
            representative_short = median(item["short_side_m"] for item in group)
            if group[0]["morphology"] != descriptor["morphology"]:
                continue
            if not (
                all(
                    _within_tolerance(descriptor["long_side_m"], item["long_side_m"], linear_tolerance_m, relative_tolerance)
                    and _within_tolerance(descriptor["short_side_m"], item["short_side_m"], linear_tolerance_m, relative_tolerance)
                    for item in group
                )
            ):
                continue
            scale = max(linear_tolerance_m, relative_tolerance * representative_long, 1e-12)
            distance = abs(descriptor["long_side_m"] - representative_long) / scale
            distance += abs(descriptor["short_side_m"] - representative_short) / max(
                linear_tolerance_m, relative_tolerance * representative_short, 1e-12
            )
            matches.append((distance, index))
        if matches:
            _, best_index = min(matches)
            groups[best_index].append(descriptor)
        else:
            groups.append([descriptor])

    proposals: list[dict[str, Any]] = []
    for group in groups:
        group = sorted(group, key=lambda descriptor: descriptor["element_id"])
        long_side = median(item["long_side_m"] for item in group)
        short_side = median(item["short_side_m"] for item in group)
        member_ids = [item["element_id"] for item in group]
        residuals = {
            item["element_id"]: {
                "long_side_m": item["long_side_m"] - long_side,
                "short_side_m": item["short_side_m"] - short_side,
            }
            for item in group
        }
        coverages = [item["evidence_coverage"] for item in group if item["evidence_coverage"] is not None]
        maximum_residual = max(
            (abs(value) for residual in residuals.values() for value in residual.values()),
            default=0.0,
        )
        tolerance_scale = max(linear_tolerance_m, relative_tolerance * long_side, 1e-12)
        dimensional_fit = max(0.0, 1.0 - maximum_residual / tolerance_scale)
        evidence_factor = sum(coverages) / len(coverages) if coverages else 0.5
        repeat_factor = min(1.0, 0.65 + 0.1 * (len(group) - 1))
        proposals.append({
            "proposal_key": _proposal_id(member_ids, group[0]["morphology"], long_side, short_side),
            "member_element_ids": member_ids,
            "representative_sides_m": {"long": long_side, "short": short_side},
            "residuals_m": residuals,
            "morphology": group[0]["morphology"],
            "morphology_agreement": True,
            "evidence_summary": {
                "member_count": len(group),
                "coverage_min": min(coverages) if coverages else None,
                "coverage_max": max(coverages) if coverages else None,
                "measurement_sources": sorted({
                    source
                    for descriptor in group
                    for source in descriptor["measurement_sources"].values()
                    if source is not None
                }),
            },
            "confidence": round(repeat_factor * dimensional_fit * evidence_factor, 3),
            "confidence_kind": "heuristic",
            "status": "proposed",
        })

    return sorted(proposals, key=lambda proposal: proposal["member_element_ids"])
