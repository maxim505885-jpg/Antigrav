"""Versioned structural-member contract shared by recognition and exports."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, TypedDict

from jsonschema import Draft202012Validator


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "structural-model.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_SCHEMA)
_VALIDATOR = Draft202012Validator(_SCHEMA)


class StructuralMember(TypedDict):
    """Stable v1 domain shape; geometry and review remain separate concerns."""

    id: str
    element_id: str
    project_id: str
    cloud_id: str
    role: str
    class_name: str
    axis: dict[str, list[float]]
    local_frame: list[list[float]]
    cross_section: dict[str, Any]
    assemblies: list[str]
    measured_dimensions: dict[str, Any]
    evidence: dict[str, Any]
    method: dict[str, Any]
    confidence: float
    review_state: str
    transforms: dict[str, list[list[float]]]


class StructuralModel(TypedDict):
    schema: str
    units: str
    coordinate_frame: dict[str, Any]
    members: list[StructuralMember]


def _reject_nonfinite(value: Any, path: str = "model") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"structural model contains a non-finite number at {path}")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_nonfinite(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_nonfinite(child, f"{path}[{index}]")


def _matmul(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [[sum(left[row][k] * right[k][column] for k in range(4))
             for column in range(4)] for row in range(4)]


def validate_structural_model(model: dict[str, Any]) -> dict[str, Any]:
    """Validate v1 shape, stable identity, member axes and transform round-trips."""
    _reject_nonfinite(model)
    errors = sorted(_VALIDATOR.iter_errors(model), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "model"
        raise ValueError(f"structural model contract violation at {path}: {error.message}")

    seen: set[str] = set()
    for index, member in enumerate(model["members"]):
        member_id = member["id"]
        if member_id in seen:
            raise ValueError("structural model requires unique, stable member IDs")
        seen.add(member_id)
        start, end = member["axis"]["start"], member["axis"]["end"]
        if math.dist(start, end) <= 1e-9:
            raise ValueError(f"member {member_id!r} axis must have non-zero length")

        transforms = member["transforms"]
        round_trip = _matmul(transforms["local_to_world"], transforms["source_to_local"])
        if any(abs(round_trip[row][column] - (1.0 if row == column else 0.0)) > 1e-8
               for row in range(4) for column in range(4)):
            raise ValueError(f"member {member_id!r} source/local/world transform round-trip is invalid")

    return model
