"""Synthetic structural fixtures for tests; these records are not workshop ground truth."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import numpy as np

from ..learning.features import features_from_element


@dataclass
class SyntheticWorkshopFixtureElement:
    element_id: str
    class_name: str
    center: list[float]
    sizes: dict[str, float]
    rotation_z: float
    confidence: float
    dimensions: dict[str, Any]
    metadata: dict[str, Any]

    def to_dict(self, project_id: str, cloud_id: str) -> dict[str, Any]:
        half_l = self.sizes.get("length", 0.3) / 2.0
        half_w = self.sizes.get("thickness", 0.3) / 2.0
        half_h = self.sizes.get("height", 3.0) / 2.0
        cx, cy, cz = self.center
        bbox = {
            "min": [cx - half_l, cy - half_w, cz - half_h],
            "max": [cx + half_l, cy + half_w, cz + half_h],
        }
        geom = {
            "kind": "oriented_box",
            "center": self.center,
            "sizes": self.sizes,
            "rotation_z": self.rotation_z,
        }
        res = {
            "id": self.element_id,
            "project_id": project_id,
            "cloud_id": cloud_id,
            "class_name": self.class_name,
            "geometry": geom,
            "bbox": bbox,
            "confidence": self.confidence,
            "confidence_kind": "synthetic_fixture",
            "measured": False,
            "inferred": True,
            "source": "invalidated_synthetic_ground_truth",
            "review_status": "invalidated",
            "dimensions": self.dimensions,
            "metadata": {"synthetic_fixture": True, **self.metadata},
        }
        res["features"] = features_from_element(res)
        return res


def generate_synthetic_workshop_fixture_catalog() -> list[SyntheticWorkshopFixtureElement]:
    """Generate deterministic synthetic geometry fixtures; never use these as labels."""
    catalog: list[SyntheticWorkshopFixtureElement] = []

    # 1. 40 Columns along longitudinal rows A (Y=0.0) and B (Y=18.0), pitch 6.0m (X: 0 to 114m)
    for row_idx, y_coord in enumerate([0.0, 18.0]):
        row_letter = "A" if row_idx == 0 else "B"
        for bay_idx in range(20):
            x_coord = bay_idx * 6.0
            el_id = f"gt_col_{row_letter}_{bay_idx+1:02d}"
            catalog.append(
                SyntheticWorkshopFixtureElement(
                    element_id=el_id,
                    class_name="column",
                    center=[x_coord, y_coord, 4.0],
                    sizes={"length": 0.35, "thickness": 0.35, "height": 8.0},
                    rotation_z=0.0,
                    confidence=1.0,
                    dimensions={"section": "30К1", "height_m": 8.0, "axis": f"{row_letter}-{bay_idx+1}"},
                    metadata={"fixture_kind": "column", "standard_example": "СТО АСЧМ 20-93"},
                )
            )

    # 2. 20 Crane Runway Girders (el. +6.800 along Row A and Row B, span 6.0m)
    for row_letter, y_coord in [("A", 0.0), ("B", 18.0)]:
        for span_idx in range(10):
            x_center = span_idx * 12.0 + 6.0
            el_id = f"gt_crane_beam_{row_letter}_{span_idx+1:02d}"
            catalog.append(
                SyntheticWorkshopFixtureElement(
                    element_id=el_id,
                    class_name="beam",
                    center=[x_center, y_coord, 6.8],
                    sizes={"length": 12.0, "thickness": 0.30, "height": 0.90},
                    rotation_z=0.0,
                    confidence=1.0,
                    dimensions={"section": "Балка Б50", "span_m": 12.0, "capacity_tons": 20.0},
                    metadata={"crane_runway": True, "rail_type": "КР-70"},
                )
            )

    # 3. 16 Roof Trusses across the 18m span between Row A and Row B (every 6m, X: 12 to 102m)
    for truss_idx in range(16):
        x_coord = (truss_idx + 2) * 6.0
        el_id = f"gt_truss_{truss_idx+1:02d}"
        catalog.append(
            SyntheticWorkshopFixtureElement(
                element_id=el_id,
                class_name="truss",
                center=[x_coord, 9.0, 10.5],
                sizes={"length": 0.25, "thickness": 18.0, "height": 2.4},
                rotation_z=float(np.pi / 2),
                confidence=1.0,
                dimensions={"span_m": 18.0, "height_m": 2.4, "pitch": "ФС-18"},
                metadata={"lattice": "triangular", "chords": "ГОСТ 30245-2003"},
            )
        )

    # 4. 12 Vertical Cross-Bracing panels between columns
    for b_idx in range(12):
        side = "A" if b_idx < 6 else "B"
        bay_step = (b_idx % 6) * 18.0 + 6.0
        y_pos = 0.0 if side == "A" else 18.0
        el_id = f"gt_brace_{side}_{b_idx+1:02d}"
        catalog.append(
            SyntheticWorkshopFixtureElement(
                element_id=el_id,
                class_name="brace",
                center=[bay_step, y_pos, 4.0],
                sizes={"length": 6.0, "thickness": 0.15, "height": 7.0},
                rotation_z=0.0,
                confidence=1.0,
                dimensions={"type": "cross_bracing", "profile": "Гн.кв. 120х120х5"},
                metadata={"wind_bracing": True},
            )
        )

    # 5. 8 Industrial Wall Gates and Openings
    for gate_idx in range(8):
        x_gate = gate_idx * 15.0 + 5.0
        el_id = f"gt_opening_{gate_idx+1:02d}"
        catalog.append(
            SyntheticWorkshopFixtureElement(
                element_id=el_id,
                class_name="opening",
                center=[x_gate, 0.0, 2.1],
                sizes={"length": 4.2, "thickness": 0.4, "height": 4.2},
                rotation_z=0.0,
                confidence=1.0,
                dimensions={"width_m": 4.2, "height_m": 4.2, "type": "industrial_gate"},
                metadata={"purpose": "truck_entrance"},
            )
        )

    # 6. 10 MEP Pipelines
    for pipe_idx in range(10):
        el_id = f"gt_pipe_{pipe_idx+1:02d}"
        y_pipe = 2.0 + pipe_idx * 1.5
        catalog.append(
            SyntheticWorkshopFixtureElement(
                element_id=el_id,
                class_name="pipe",
                center=[50.0, y_pipe, 5.5],
                sizes={"length": 100.0, "thickness": 0.25, "height": 0.25},
                rotation_z=0.0,
                confidence=1.0,
                dimensions={"diameter_mm": 219.0, "length_m": 100.0, "slope_percent": 0.2},
                metadata={"medium": "Heating / Steam", "insulation": "mineral_wool"},
            )
        )

    return catalog


def seed_and_train_ground_truth(
    project_id: str,
    cloud_id: str,
    model_name: str = "workshop-real-knn",
) -> dict[str, Any]:
    """Compatibility guard for an obsolete synthetic seeding workflow."""
    raise ValueError(
        "synthetic workshop fixtures cannot be seeded or used for training; "
        "collect independent engineer-reviewed physical labels instead"
    )
