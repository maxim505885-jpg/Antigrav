"""Pluggable semantic-segmentation adapter.

The core product is fully functional without PyTorch. Heavy models
(Pointcept / Open3D-ML / BIM-Net++) must live in a separate environment; this
module only defines the contract and reports a truthful status. Nothing here
claims that a model is available.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..config import ML_MODEL_DIR, ML_PYTHON

# Classes the architecture is prepared for. Only a subset is produced by the
# geometric baseline; the rest require trained models.
TARGET_CLASSES = [
    "wall",
    "column",
    "beam",
    "girder",
    "slab",
    "roof",
    "truss",
    "brace",
    "stair",
    "opening",
    "pipe",
    "duct",
    "equipment",
    "other",
    "unknown",
]


class SemanticSegmenter(Protocol):
    name: str

    def available(self) -> bool: ...

    def segment(self, positions_path: Path, meta: dict[str, Any]) -> list[dict[str, Any]]: ...


@dataclass
class PointceptAdapter:
    """External Pointcept inference process.

    Expected contract: the configured python interpreter runs the project's
    inference wrapper and writes a JSON file with per-point or per-instance
    labels. This adapter intentionally does not pretend to work when the
    external environment or weights are missing.
    """

    name: str = "pointcept"
    python: str = ML_PYTHON
    model_dir: Path = Path(ML_MODEL_DIR)

    def available(self) -> bool:
        if not self.python or not Path(self.python).exists():
            return False
        return self.model_dir.exists()

    def segment(self, positions_path: Path, meta: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.available():
            raise RuntimeError(
                "Pointcept is not configured. Set S2B_ML_PYTHON to a separate "
                "PyTorch environment and S2B_ML_MODELS to the checkpoint directory. "
                "The geometric baseline remains available without it."
            )
        raise NotImplementedError(
            "Pointcept inference wrapper is not implemented in this build; "
            "the adapter contract is in place for the ML stage."
        )


@dataclass
class MLStatus:
    configured: bool
    available: bool
    provider: str
    python: str = ""
    model_dir: str = ""
    target_classes: list[str] = field(default_factory=lambda: list(TARGET_CLASSES))
    notes: list[str] = field(default_factory=list)


def ml_status() -> MLStatus:
    adapter = PointceptAdapter()
    notes = [
        "The baseline recognition is geometric and does not require a GPU.",
        "Heavy ML models are intentionally isolated from the core environment.",
    ]
    if not ML_PYTHON:
        notes.append("S2B_ML_PYTHON is not set.")
    if not Path(ML_MODEL_DIR).exists():
        notes.append("Model directory does not exist yet.")
    return MLStatus(
        configured=bool(ML_PYTHON),
        available=adapter.available(),
        provider=adapter.name,
        python=ML_PYTHON,
        model_dir=str(ML_MODEL_DIR),
        notes=notes,
    )


def semantic_segmenter() -> SemanticSegmenter | None:
    adapter = PointceptAdapter()
    return adapter if adapter.available() else None
