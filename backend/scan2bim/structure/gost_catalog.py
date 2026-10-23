"""Standard Russian GOST steel profile assortment and catalog matcher.

Implements standard profiles from:
- GOST 57837-2017 / STO ASChM 20-93 (I-beams: B, Sh, K - Б, Ш, К)
- GOST 8240-97 (Channels: U, P - У, П)
- GOST 30245-2003 (Square and rectangular hollow sections - профильные трубы)
- GOST 10704-91 / GOST 8732-78 (Round steel pipes - круглые трубы)

Matches measured geometry to standard assortment with tolerances and reports deviations.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Optional


@dataclass(frozen=True)
class SteelProfileStandard:
    standard: str
    designation: str
    profile_type: str  # "i_beam", "channel", "box_tube", "round_pipe"
    height_mm: float
    width_mm: float
    web_thickness_mm: float
    flange_thickness_mm: float
    mass_kg_m: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Representative standard profiles commonly used in industrial workshop halls
GOST_STEEL_CATALOG: list[SteelProfileStandard] = [
    # I-Beams GOST 57837-2017 / STO ASChM 20-93
    # Column I-beams (K)
    SteelProfileStandard("СТО АСЧМ 20-93", "20К1", "i_beam", 195.0, 200.0, 6.5, 10.0, 41.4),
    SteelProfileStandard("СТО АСЧМ 20-93", "25К1", "i_beam", 246.0, 249.0, 8.0, 12.0, 63.8),
    SteelProfileStandard("СТО АСЧМ 20-93", "30К1", "i_beam", 296.0, 299.0, 9.0, 14.0, 84.8),
    SteelProfileStandard("СТО АСЧМ 20-93", "30К2", "i_beam", 300.0, 300.0, 10.0, 15.0, 94.8),
    SteelProfileStandard("СТО АСЧМ 20-93", "35К1", "i_beam", 343.0, 348.0, 10.0, 15.0, 109.1),
    SteelProfileStandard("СТО АСЧМ 20-93", "40К1", "i_beam", 393.0, 398.0, 11.0, 16.5, 137.8),
    # Wide flange I-beams (Sh)
    SteelProfileStandard("СТО АСЧМ 20-93", "20Ш1", "i_beam", 193.0, 150.0, 6.0, 9.0, 30.6),
    SteelProfileStandard("СТО АСЧМ 20-93", "25Ш1", "i_beam", 244.0, 175.0, 7.0, 11.0, 44.1),
    SteelProfileStandard("СТО АСЧМ 20-93", "30Ш1", "i_beam", 291.0, 200.0, 8.0, 11.0, 56.8),
    SteelProfileStandard("СТО АСЧМ 20-93", "35Ш1", "i_beam", 340.0, 250.0, 9.0, 12.0, 79.7),
    SteelProfileStandard("СТО АСЧМ 20-93", "40Ш1", "i_beam", 388.0, 300.0, 9.5, 14.0, 96.1),
    SteelProfileStandard("СТО АСЧМ 20-93", "50Ш1", "i_beam", 488.0, 300.0, 11.0, 15.5, 128.2),
    # Normal I-beams (B) - Crane girders & beams
    SteelProfileStandard("СТО АСЧМ 20-93", "25Б1", "i_beam", 248.0, 124.0, 5.0, 8.0, 25.7),
    SteelProfileStandard("СТО АСЧМ 20-93", "30Б1", "i_beam", 298.0, 149.0, 5.5, 8.0, 32.0),
    SteelProfileStandard("СТО АСЧМ 20-93", "35Б1", "i_beam", 346.0, 174.0, 6.0, 9.0, 41.4),
    SteelProfileStandard("СТО АСЧМ 20-93", "40Б1", "i_beam", 396.0, 199.0, 7.0, 10.0, 56.6),
    SteelProfileStandard("СТО АСЧМ 20-93", "45Б1", "i_beam", 446.0, 199.0, 8.0, 11.0, 66.2),
    SteelProfileStandard("СТО АСЧМ 20-93", "50Б1", "i_beam", 496.0, 199.0, 9.0, 12.0, 79.5),
    # Rectangular and square hollow tubes (GOST 30245-2003) - Trusses & Braces
    SteelProfileStandard("ГОСТ 30245-2003", "Гн.кв. 100х100х4", "box_tube", 100.0, 100.0, 4.0, 4.0, 12.0),
    SteelProfileStandard("ГОСТ 30245-2003", "Гн.кв. 120х120х5", "box_tube", 120.0, 120.0, 5.0, 5.0, 18.0),
    SteelProfileStandard("ГОСТ 30245-2003", "Гн.кв. 140х140х5", "box_tube", 140.0, 140.0, 5.0, 5.0, 21.2),
    SteelProfileStandard("ГОСТ 30245-2003", "Гн.кв. 160х160х6", "box_tube", 160.0, 160.0, 6.0, 6.0, 28.7),
    SteelProfileStandard("ГОСТ 30245-2003", "Гн.кв. 180х180х6", "box_tube", 180.0, 180.0, 6.0, 6.0, 32.5),
    SteelProfileStandard("ГОСТ 30245-2003", "Гн.кв. 200х200х8", "box_tube", 200.0, 200.0, 8.0, 8.0, 47.7),
    # Channels (GOST 8240-97)
    SteelProfileStandard("ГОСТ 8240-97", "16П", "channel", 160.0, 64.0, 5.0, 8.4, 14.2),
    SteelProfileStandard("ГОСТ 8240-97", "20П", "channel", 200.0, 76.0, 5.2, 9.0, 18.4),
    SteelProfileStandard("ГОСТ 8240-97", "24П", "channel", 240.0, 90.0, 5.6, 10.0, 24.0),
    SteelProfileStandard("ГОСТ 8240-97", "30П", "channel", 300.0, 100.0, 6.5, 11.0, 31.8),
]


def match_steel_profile(
    measured_height_mm: float,
    measured_width_mm: float,
    measured_web_th_mm: Optional[float] = None,
    measured_flange_th_mm: Optional[float] = None,
    profile_type: Optional[str] = None,
    max_height_diff_mm: float = 25.0,
    max_width_diff_mm: float = 25.0,
) -> list[dict[str, Any]]:
    """Match point-measured section dimensions to GOST assortment profiles.

    Returns ranked list of candidate standard matches with dimensional residuals.
    """
    h_m = float(measured_height_mm)
    w_m = float(measured_width_mm)

    if h_m < w_m and profile_type == "i_beam":
        # Ensure height is major dimension for standard I-beam comparison
        h_m, w_m = w_m, h_m

    candidates = []

    for item in GOST_STEEL_CATALOG:
        if profile_type and item.profile_type != profile_type:
            continue

        dh = abs(item.height_mm - h_m)
        dw = abs(item.width_mm - w_m)

        if dh <= max_height_diff_mm and dw <= max_width_diff_mm:
            # Score composite penalty
            penalty = dh + dw
            if measured_web_th_mm is not None:
                penalty += abs(item.web_thickness_mm - measured_web_th_mm) * 2.0
            if measured_flange_th_mm is not None:
                penalty += abs(item.flange_thickness_mm - measured_flange_th_mm) * 2.0

            candidates.append({
                "profile": item.to_dict(),
                "delta_height_mm": round(item.height_mm - h_m, 1),
                "delta_width_mm": round(item.width_mm - w_m, 1),
                "residual_mm": round(penalty, 2),
                "match_confidence": round(max(0.0, 1.0 - penalty / 50.0), 3),
            })

    candidates.sort(key=lambda x: x["residual_mm"])
    return candidates
