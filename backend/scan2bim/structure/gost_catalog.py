"""Cited, partial I-beam assortment used only for review suggestions.

Dimensions below are transcribed from the base edition of ГОСТ 35087-2024.
The standard is active, but the corrections listed by Rosstandart after the
base edition (including the October 2026 correction) have not been checked
against their full text. Results therefore remain provisional candidates and
must never set a project type, mark, tolerance, or engineering acceptance.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


GOST_35087_SOURCE = "https://protect.gost.ru/gost/details/63278470-4edb-4de1-88ca-2da45c12d7d4"
CATALOG_STATUS = "base_edition_only_latest_corrections_unverified"


@dataclass(frozen=True)
class SteelProfileStandard:
    standard: str
    designation: str
    profile_type: str
    height_mm: float
    width_mm: float
    web_thickness_mm: float
    flange_thickness_mm: float
    mass_kg_m: float
    source_url: str = GOST_35087_SOURCE
    review_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Small audited subset; extend only after transcribing and testing named rows
# from the cited edition and reviewing its corrigenda.
GOST_STEEL_CATALOG: tuple[SteelProfileStandard, ...] = (
    SteelProfileStandard("ГОСТ 35087-2024", "20К1", "i_beam", 196.0, 199.0, 6.5, 10.0, 41.4),
    SteelProfileStandard("ГОСТ 35087-2024", "25К1", "i_beam", 246.0, 249.0, 8.0, 12.0, 62.6),
    SteelProfileStandard("ГОСТ 35087-2024", "30К1", "i_beam", 298.0, 299.0, 9.0, 14.0, 87.0),
    SteelProfileStandard("ГОСТ 35087-2024", "30К2", "i_beam", 300.0, 300.0, 10.0, 15.0, 94.0),
    SteelProfileStandard("ГОСТ 35087-2024", "35К1", "i_beam", 342.0, 348.0, 10.0, 15.0, 109.1),
    SteelProfileStandard("ГОСТ 35087-2024", "40К1", "i_beam", 394.0, 398.0, 11.0, 18.0, 146.7),
    SteelProfileStandard("ГОСТ 35087-2024", "20Ш1", "i_beam", 194.0, 150.0, 6.0, 9.0, 30.6),
    SteelProfileStandard("ГОСТ 35087-2024", "25Ш1", "i_beam", 244.0, 175.0, 7.0, 11.0, 44.2),
    SteelProfileStandard("ГОСТ 35087-2024", "25Б1", "i_beam", 248.0, 124.0, 5.0, 8.0, 25.7),
    SteelProfileStandard("ГОСТ 35087-2024", "30Б1", "i_beam", 298.0, 149.0, 5.5, 8.0, 32.0),
    SteelProfileStandard("ГОСТ 35087-2024", "35Б1", "i_beam", 346.0, 174.0, 6.0, 9.0, 41.4),
)


def match_steel_profile(
    measured_height_mm: float,
    measured_width_mm: float,
    measured_web_th_mm: float | None = None,
    measured_flange_th_mm: float | None = None,
    profile_type: str | None = None,
    max_height_diff_mm: float = 25.0,
    max_width_diff_mm: float = 25.0,
) -> list[dict[str, Any]]:
    """Return provisional dimension-nearby catalog candidates for human review.

    Search-window values only limit candidate retrieval. They are not
    engineering tolerances and the ranking score is not a calibrated probability.
    """
    dimensions = [measured_height_mm, measured_width_mm]
    optional_dimensions = [value for value in (measured_web_th_mm, measured_flange_th_mm) if value is not None]
    windows = [max_height_diff_mm, max_width_diff_mm]
    if not all(math.isfinite(float(value)) and float(value) > 0 for value in dimensions + optional_dimensions):
        raise ValueError("profile dimensions must be finite positive numbers")
    if not all(math.isfinite(float(value)) and float(value) >= 0 for value in windows):
        raise ValueError("catalog search windows must be finite non-negative numbers")

    # Preserve the caller's measured h/b axes. A valid standard profile such
    # as 30К1 has h=298 mm and b=299 mm; sorting dimensions would corrupt it.
    height = float(measured_height_mm)
    width = float(measured_width_mm)

    matches: list[dict[str, Any]] = []
    for item in GOST_STEEL_CATALOG:
        if profile_type and item.profile_type != profile_type:
            continue
        delta_height = item.height_mm - height
        delta_width = item.width_mm - width
        if abs(delta_height) > max_height_diff_mm or abs(delta_width) > max_width_diff_mm:
            continue
        score = abs(delta_height) + abs(delta_width)
        if measured_web_th_mm is not None:
            score += 2.0 * abs(item.web_thickness_mm - float(measured_web_th_mm))
        if measured_flange_th_mm is not None:
            score += 2.0 * abs(item.flange_thickness_mm - float(measured_flange_th_mm))
        matches.append({
            "profile": item.to_dict(),
            "delta_height_mm": round(delta_height, 1),
            "delta_width_mm": round(delta_width, 1),
            "ranking_score_mm": round(score, 2),
            "catalog_status": CATALOG_STATUS,
            "review_required": True,
        })

    matches.sort(key=lambda result: result["ranking_score_mm"])
    return matches
