"""API request/response schemas (Pydantic v2)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    units: str = "m"


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    units: str
    created_at: str
    updated_at: str
    cloud_count: int = 0
    element_count: int = 0


class CloudOut(BaseModel):
    id: str
    project_id: str
    name: str
    source_path: str
    source_format: str
    size_bytes: int
    point_count: int
    ingested_count: int
    decimated: bool
    origin: list[float] | None = None
    bbox_min: list[float] | None = None
    bbox_max: list[float] | None = None
    has_color: bool
    has_intensity: bool
    status: str
    error: str | None = None
    preview_count: int = 0
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    warning: str | None = None


class CloudImportPath(BaseModel):
    path: str
    name: str | None = None


class Region(BaseModel):
    min_u: float
    max_u: float
    min_v: float
    max_v: float


class SectionRequest(BaseModel):
    kind: Literal["horizontal", "vertical"] = "horizontal"
    position: float | None = None
    axis: Literal["x", "y"] | None = None
    thickness: float = Field(default=0.05, gt=0, le=2.0)
    grid_res: float = Field(default=0.02, gt=0.001, le=0.5)
    region: Region | None = None
    regularize: bool = True
    min_component_area: float = Field(default=0.03, ge=0, le=100)
    close_radius_m: float = Field(default=0.06, ge=0, le=1.0)

    @field_validator("position")
    @classmethod
    def _position_finite(cls, v: float | None) -> float | None:
        if v is not None and (v != v or abs(v) > 1e9):
            raise ValueError("position must be a finite number")
        return v


class SectionOut(BaseModel):
    id: str
    cloud_id: str
    kind: str
    axis: str | None
    position: float
    thickness: float
    grid_res: float
    point_count: int
    created_at: str
    result: dict[str, Any]


class ElementOut(BaseModel):
    id: str
    project_id: str
    cloud_id: str
    parent_id: str | None = None
    class_name: str
    geometry: dict[str, Any]
    bbox: dict[str, Any]
    confidence: float
    confidence_kind: str
    measured: bool
    inferred: bool
    source: str
    review_status: str
    dimensions: dict[str, Any]
    created_at: str
    updated_at: str


class ElementPatch(BaseModel):
    class_name: str | None = None
    review_status: Literal["unreviewed", "confirmed", "corrected", "rejected"] | None = None
    geometry: dict[str, Any] | None = None
    note: str = ""
    engineer: str = ""


class FeedbackCreate(BaseModel):
    action: Literal["confirm", "reclassify", "adjust_boundary", "merge", "split", "reject"]
    class_name: str | None = None
    geometry: dict[str, Any] | None = None
    other_element_id: str | None = None
    axis: Literal["x", "y", "z"] | None = None
    value: float | None = None
    note: str = ""
    engineer: str = ""


class TrainRequest(BaseModel):
    name: str = "geometric-knn"
    test_fraction: float = Field(default=0.25, ge=0.1, le=0.5)
    min_test_samples: int = Field(default=6, ge=1)
    min_macro_f1: float = Field(default=0.6, ge=0, le=1)
    notes: str = ""


class ModelOut(BaseModel):
    id: str
    name: str
    version: int
    kind: str
    path: str
    metrics: dict[str, Any]
    status: str
    notes: str
    created_at: str
    activated_at: str | None = None


class WebhookCreate(BaseModel):
    url: str
    secret: str = ""
    events: str = "*"


class JobOut(BaseModel):
    id: str
    project_id: str | None
    cloud_id: str | None
    type: str
    status: str
    progress: float
    message: str
    result: dict[str, Any]
    error: str | None
    created_at: str
    updated_at: str


class SampleOut(BaseModel):
    id: str
    project_id: str
    cloud_id: str
    element_id: str | None
    class_name: str
    features: dict[str, Any]
    split: str
    source: str
    created_at: str
