"""API request/response schemas (Pydantic v2)."""
from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


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
    import_job_id: str | None = None
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
    metadata: dict[str, Any] = Field(default_factory=dict)
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


class ColumnTypeReview(BaseModel):
    cloud_id: str
    engineer: str = "engineer"
    note: str = ""
    linear_tolerance_m: float = Field(default=0.005, ge=0, le=0.5, allow_inf_nan=False)
    relative_tolerance: float = Field(default=0.01, ge=0, le=0.25, allow_inf_nan=False)


class ColumnTypeConfirm(ColumnTypeReview):
    mark: str | None = None


class ColumnTypeReject(ColumnTypeReview):
    pass


class ColumnTypeAssign(BaseModel):
    type_id: str | None = None
    engineer: str = "engineer"
    note: str = ""


class ColumnTypeUndo(BaseModel):
    engineer: str = "engineer"
    note: str = ""


class ColumnAnnotationSourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_point_row_id_count: StrictInt = Field(gt=0)
    source_point_row_id_sample: list[StrictInt] = Field(min_length=1, max_length=100)
    source_index_space: Literal["derived_positions_row_index/1"]
    analysis_algorithm: str = Field(min_length=1, max_length=200)


class ColumnAnnotationHeightMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    z_m: float = Field(allow_inf_nan=False)
    sides_m: dict[str, float] | None = None
    note: str = ""
    source_provenance: ColumnAnnotationSourceProvenance | None = None


class ColumnAnnotationSave(BaseModel):
    source_snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    annotator: str = Field(min_length=1, max_length=200)
    state: Literal["labeled", "unknown", "excluded"]
    physical_instance_id: str | None = Field(default=None, max_length=200)
    type_label: str | None = Field(default=None, max_length=120)
    shape_label: Literal["rectangular_solid", "built_up", "stepped", "circular", "other", "unknown"] | None = None
    structural_role: Literal["column", "crane_column", "other", "unknown"] | None = None
    sides_m: dict[str, float] | None = None
    measurement_source: Literal["manual_cloud", "field_measurement"] | None = None
    z_measurements: list[ColumnAnnotationHeightMeasurement] = Field(default_factory=list)
    algorithm_suggestions_verified: StrictBool = False
    visible_faces: list[Literal["u+", "u-", "v+", "v-"]] = Field(default_factory=list)
    hidden_faces: list[Literal["u+", "u-", "v+", "v-"]] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    reason_unknown: str = Field(default="", max_length=2000)
    note: str = Field(default="", max_length=4000)


class ColumnSectionFitRequest(BaseModel):
    slice_z_m: float | None = Field(default=None, ge=-1e9, le=1e9, allow_inf_nan=False)
    thickness_m: float = Field(default=0.2, gt=0, le=1.0, allow_inf_nan=False)
    known_sides_m: list[float] | None = Field(default=None, min_length=2, max_length=2)
    distance_tolerance_m: float = Field(default=0.004, gt=0, le=0.05, allow_inf_nan=False)
    candidate_margin_m: float = Field(default=0.2, ge=0, le=1.0, allow_inf_nan=False)

    @field_validator("known_sides_m")
    @classmethod
    def _known_sides_positive(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and any(not value_i > 0 or not math.isfinite(value_i) for value_i in value):
            raise ValueError("known_sides_m must contain two finite positive lengths")
        return value


class ColumnSectionBatchFitRequest(BaseModel):
    slice_z_values_m: list[float] = Field(min_length=3, max_length=9)
    thickness_m: float = Field(default=0.2, gt=0, le=1.0, allow_inf_nan=False)
    known_sides_m: list[float] | None = Field(default=None, min_length=2, max_length=2)
    distance_tolerance_m: float = Field(default=0.004, gt=0, le=0.05, allow_inf_nan=False)
    candidate_margin_m: float = Field(default=0.2, ge=0, le=1.0, allow_inf_nan=False)

    @field_validator("slice_z_values_m")
    @classmethod
    def _unique_finite_slice_heights(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(height) or height < -1e9 or height > 1e9 for height in value):
            raise ValueError("slice_z_values_m must contain finite heights between -1e9 and 1e9")
        if len(set(value)) != len(value):
            raise ValueError("slice_z_values_m must contain unique heights")
        return value

    @field_validator("known_sides_m")
    @classmethod
    def _known_sides_positive(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and any(not value_i > 0 or not math.isfinite(value_i) for value_i in value):
            raise ValueError("known_sides_m must contain two finite positive lengths")
        return value


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


class SampleCreate(BaseModel):
    element_id: str
    class_name: str | None = None


class CleanupRequest(BaseModel):
    """Non-destructive cleanup of a registered cloud.

    Only the requested filter runs; the source cloud is never rewritten. The
    result is a derived artefact with its own positions file and metadata.
    """

    method: Literal["statistical", "radius", "voxel"] = "voxel"
    voxel_m: float = Field(default=0.05, gt=0.0005, le=2.0)
    k: int = Field(default=16, ge=1, le=200)
    std_ratio: float = Field(default=2.0, gt=0.1, le=10.0)
    radius_m: float = Field(default=0.05, gt=0.0005, le=5.0)
    min_neighbors: int = Field(default=4, ge=1, le=500)


class CloudExportRequest(BaseModel):
    """Export a stored cloud to an interchange format.

    The written file is read back and coordinate deviation is measured; the
    job result reports it instead of trusting the write.
    """

    format: Literal["e57", "las", "laz", "ply", "xyz"] = "e57"
    derived_id: str | None = Field(default=None, max_length=64)
    verify: bool = True
