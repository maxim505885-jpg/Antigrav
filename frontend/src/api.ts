import type { Cloud, Element, Job, ModelInfo, Project, Section, LodManifest } from "./types";

const BASE = "/api/v1";

export interface ColumnTypeProposal {
  proposal_key: string;
  member_element_ids: string[];
  representative_sides_m: { long: number; short: number };
  residuals_m: Record<string, { long_side_m: number; short_side_m: number }>;
  morphology: string;
  confidence: number;
  evidence_summary: { member_count: number; coverage_min: number | null; coverage_max: number | null };
  status: "proposed";
}

export interface RcpImportBatch {
  project_id: string;
  project_file: string;
  project_sha256: string;
  import_job_id: string;
  node_count: number;
  stations: { node_id: string | null; node_name: string; cloud: import("./types").Cloud }[];
}

export interface ConfirmedColumnType {
  id: string;
  mark: string;
  member_element_ids: string[];
  prototype: ColumnTypeProposal;
  status: "confirmed";
}

export interface ColumnTypesResponse {
  cloud_id: string;
  project_id: string;
  linear_tolerance_m: number;
  relative_tolerance: number;
  tolerance_status: "provisional";
  proposals: ColumnTypeProposal[];
  confirmed_types: ConfirmedColumnType[];
  catalog_reuse: {
    visibility_threshold: number;
    threshold_status: "provisional";
    suggestions: {
      element_id: string;
      status: "match" | "ambiguous" | "insufficient_evidence" | "unknown" | "ineligible";
      review_required: true;
      evidence_coverage: number | null;
      reasons: string[];
      matches: {
        type_id: string; mark: string; source_cloud_ids: string[];
        representative_sides_m: { long: number; short: number };
        residuals_m: { long_side_m: number; short_side_m: number };
      }[];
    }[];
    catalog_issues: { type_id: string; mark: string; reasons: string[] }[];
  };
  rejected_proposals: {
    proposal_key: string;
    proposal: ColumnTypeProposal;
    action_id: string;
    status: "rejected";
    note: string;
  }[];
}

interface ColumnTypeAction { action_id: string | null; changed: boolean }

export interface ColumnSectionFitResponse {
  element_id: string;
  algorithm: { name: string; version: string };
  parameters: {
    slice_z_m: number;
    thickness_m: number;
    known_sides_m: number[] | null;
    distance_tolerance_m: number;
    candidate_margin_m: number;
  };
  source_rows: {
    kind: "derived_cloud_zero_based_row_index";
    count: number;
    sample_limit_per_face: number;
    description: string;
  };
  point_query: { strategy: string; candidate_rows_estimate: number };
  point_support: {
    selected_point_count: number;
    unique_observed_face_point_count: number;
    unassigned_point_count: number;
    observed_face_point_fraction: number | null;
    scope: string;
  };
  slice_z_m: number;
  slice_thickness_m: number;
  point_count: number;
  preview_points_xy_local_m: [number, number][];
  status: "proposed" | "ambiguous" | "open_section" | "unknown" | "insufficient_points";
  hypotheses: {
    side_lengths_m: number[];
    corners_world_m: [number, number][];
    edge_evidence: ("observed" | "inferred")[];
    observed_edge_count: number;
    inferred_edge_count: number;
    dimension_source: string;
    inferred: boolean;
    review_required: true;
    edge_observation_coverage: {
      edge_index: number;
      length_m: number;
      observed_span_m: number;
      unobserved_m: number;
      coverage_fraction: number;
      unobserved_fraction: number;
      source_face_ids: string[];
      evidence: "observed" | "no_observed_points" | "invalid_edge";
    }[];
  }[];
  observed_faces: {
    face_id: string;
    start_world_m: [number, number];
    end_world_m: [number, number];
    observed_span_m: number;
    support_count: number;
    rmse_m: number;
    p95_residual_m: number;
    span_kind: string;
    ingested_point_row_id_sample: number[];
    ingested_point_row_id_count: number;
  }[];
  open_corners: { world_m: [number, number]; face_ids: string[]; observed_spans_m: number[] }[];
  dimension_conflicts: Record<string, unknown>[];
  review_required: true;
  engineering_status: "not_assessed";
  persisted: false;
  source_geometry_modified: false;
}

export interface ColumnSectionBatchFitResponse {
  element_id: string;
  algorithm: { name: string; version: string };
  slice_count: number;
  review_required: true;
  persisted: false;
  source_geometry_modified: false;
  slices: ColumnSectionFitResponse[];
}

export interface ColumnSurfaceTrackAnalysisResponse {
  schema: "scan.column-surface-track-analysis/1";
  candidate_id: string;
  cloud_id: string;
  algorithm: { surface_extraction: string; section_series: string };
  parameters: { candidate_margin_m: number; vertical_context_margin_m: number; distance_tolerance_m: number; voxel_m: number; vertical_bin_m: number; maximum_crop_points: number };
  point_query: { strategy: string; candidate_rows_estimate: number };
  input_points: { count: number; source_row_kind: string; description: string };
  surface_result: { surfaces: { plane_id: string; source_point_row_id_count: number; source_point_row_id_sample: number[] }[] };
  surface_association: { association_status: string; candidate_edge_count: number; candidate_edges: string[]; surface_associations: { plane_id: string; candidate_edge_id: string | null; association_status: string }[] };
  tracks: {
    track_id: string; candidate_edge_id: string | null; surface_ids: string[];
    vertical_support_m: number; vertical_support_fraction: number;
    track_status: string; source_point_row_id_count: number; source_point_row_id_sample: number[];
  }[];
  section_series: {
    status: string;
    section_slices: {
      z_m: number; status: string; shape_status: string;
      hypotheses: ColumnSectionFitResponse["hypotheses"];
      built_up_hypotheses?: {
        shape: "built_up_i"; envelope_side_lengths_m: number[]; web_thickness_m: number;
        flange_thicknesses_m: number[]; source_point_row_id_count: number;
        source_point_row_id_sample: number[]; review_required: true;
        engineering_status: "not_assessed";
        catalog_matches?: Array<{
          profile: { standard: string; designation: string; profile_type: string; height_mm: number; width_mm: number; mass_kg_m: number; source_url: string; review_required: true };
          delta_height_mm: number;
          delta_width_mm: number;
          ranking_score_mm: number;
          catalog_status: string;
          review_required: true;
        }>;
      }[];
      source_point_row_id_count: number; source_point_row_id_sample: number[];
      track_ids: string[]; track_evidence: { track_id: string; edge_id: string; source_point_count: number }[];
    }[];
    dimensions_by_height_m: { z_m: number; side_lengths_m: number[] }[];
    profile_variation_status: string;
  };
  excluded_tracks: { track_id: string; reason: string; detail_reasons?: string[] }[];
  confirmed: false;
  review_required: true;
  engineering_status: "not_assessed";
  persisted: false;
  source_geometry_modified: false;
}

export interface ColumnAnnotationDraft {
  source_snapshot_sha256: string;
  annotator: string;
  state: "labeled" | "unknown" | "excluded";
  physical_instance_id: string | null;
  type_label: string | null;
  shape_label: "rectangular_solid" | "built_up" | "stepped" | "circular" | "other" | "unknown" | null;
  structural_role: "column" | "crane_column" | "other" | "unknown" | null;
  sides_m: { long: number; short: number } | null;
  measurement_source: "manual_cloud" | "field_measurement" | null;
  z_measurements: {
    z_m: number;
    sides_m: { long: number; short: number } | null;
    note: string;
    source_provenance?: {
      source_point_row_id_count: number;
      source_point_row_id_sample: number[];
      source_index_space: "derived_positions_row_index/1";
      analysis_algorithm: string;
    };
  }[];
  algorithm_suggestions_verified: boolean;
  visible_faces: ("u+" | "u-" | "v+" | "v-")[];
  hidden_faces: ("u+" | "u-" | "v+" | "v-")[];
  confidence: number | null;
  reason_unknown: string;
  note: string;
}

export interface ColumnAnnotation extends Omit<ColumnAnnotationDraft, "state"> {
  state: ColumnAnnotationDraft["state"] | "pending";
  element_id: string;
  revision: number;
  created_at: string | null;
}

export interface TrainingSample {
  id: string;
  project_id: string;
  cloud_id: string;
  element_id: string | null;
  class_name: string;
  physical_instance_id: string | null;
  source_snapshot_id: string | null;
  features: Record<string, number>;
  split: string;
  source: string;
  created_at: string;
}

export interface LearningManifestPreview {
  schema_version: 1;
  project_id: string;
  manifest_sha256: string;
  eligible_sample_count: number;
  class_counts: Record<string, number>;
  excluded_sample_counts: Record<string, number>;
  training_started: false;
  model_activated: false;
}

export interface LearningManifestExportResult {
  manifest_sha256: string;
  relative_path: string;
  eligible_sample_count: number;
  training_started: false;
  model_activated: false;
}

export interface ProjectColumnReferenceTypes {
  schema: "scan.column-reference-types/1";
  project_id: string;
  annotation_origin: "independent_manual";
  tolerance_status: "not_applied";
  current_column_cloud_count: number;
  reviewed_column_cloud_count: number;
  labeled_annotation_count: number;
  unique_physical_instance_count: number;
  groups: Array<{
    type_label: string;
    physical_instance_count: number;
    physical_instance_ids: string[];
    source_cloud_ids: string[];
    measurement_count: number;
    measurement_sources: string[];
    measured_sides_range_m: {
      long: { min: number; max: number } | null;
      short: { min: number; max: number } | null;
    };
  }>;
  conflicts: Array<{ physical_instance_id: string; type_labels: string[]; source_cloud_ids: string[] }>;
}

export interface ColumnAnnotationDataset {
  schema: "scan.column-type-reference/1";
  dataset_id: string;
  project_id: string;
  cloud_id: string;
  source_snapshot_sha256: string;
  annotation_origin: "independent_manual";
  engineering_tolerance_m: null;
  annotations: ColumnAnnotation[];
  history: ColumnAnnotation[];
}

export interface ColumnAnnotationArchiveResponse {
  cloud_id: string;
  project_id: string;
  history: (ColumnAnnotation & { dataset_id: string; source_snapshot_sha256: string })[];
}

export interface ElementAnnotationDraft {
  source_snapshot_sha256: string;
  annotator: string;
  state: "labeled" | "unknown" | "excluded";
  physical_instance_id: string | null;
  class_label: string | null;
  role_label: string | null;
  type_label: string | null;
  reason: string;
  note: string;
}

export interface ElementAnnotation extends Omit<ElementAnnotationDraft, "source_snapshot_sha256" | "state"> {
  state: ElementAnnotationDraft["state"] | "pending";
  element_id: string;
  revision: number;
  created_at: string | null;
}

export interface ElementAnnotationDataset {
  schema: "scan.element-role-reference/1";
  dataset_id: string;
  project_id: string;
  cloud_id: string;
  source_snapshot_sha256: string;
  annotation_origin: "independent_manual";
  classification_evaluation: ElementRoleEvaluation;
  annotations: ElementAnnotation[];
  history: ElementAnnotation[];
}

export interface ElementAnnotationArchiveResponse {
  cloud_id: string;
  project_id: string;
  history: (ElementAnnotation & { dataset_id: string; source_snapshot_sha256: string })[];
}

export interface ElementRoleEvaluation {
  scope: "reviewed_existing_candidates_only";
  holdout_status: "not_declared";
  missed_physical_elements_included: false;
  reviewed_counts: { labeled: number; unknown: number; excluded: number; pending: number };
  candidate_validity: {
    reviewed_candidate_count: number;
    confirmed_real_candidate_count: number;
    excluded_false_candidate_count: number;
    reviewed_candidate_validity_rate: number | null;
  };
  class_metrics: { evaluated_count: number; correct_count: number; accuracy: number | null };
  role_metrics: { evaluated_count: number; correct_count: number; accuracy: number | null };
}

export interface RecognitionEvaluationRequest {
  source_snapshot_sha256: string;
  reference_set_id: string;
  reference_origin: "independent_manual";
  reference_kind: "manual_cloud" | "field_measurement" | "mixed";
  annotator: string;
  iou_threshold?: number;
  reference_elements: {
    physical_instance_id: string;
    class_name: string;
    role_label?: string | null;
    bbox: { min: [number, number, number]; max: [number, number, number] };
  }[];
}

export interface RecognitionEvaluationReport {
  reference_set_id: string;
  reference_kind: string;
  reference_element_count: number;
  total_detected_candidates: number;
  unscorable_detection_geometry_count: number;
  unscorable_detection_ids: string[];
  centerline_extent_match_count: number;
  mean_matched_centerline_extent_iou: number | null;
  overall_precision: number | null;
  overall_recall: number | null;
  overall_f1: number | null;
  mean_matched_iou: number | null;
  holdout_status: "not_verified";
  missed_reference_elements_counted_as_false_negatives: boolean;
  role_metrics: {
    evaluated_reference_count: number;
    evaluated_detection_count: number;
    unassigned_detection_count: number;
    correct_count: number;
    accuracy: number | null;
    precision: number | null;
    recall: number | null;
    f1: number | null;
    per_role: Record<string, {
      reference_count: number; predicted_count: number; true_positives: number;
      false_positives: number; false_negatives: number;
      precision: number | null; recall: number | null; f1: number | null;
    }>;
  };
  per_class: Record<string, {
    reference_count: number; detected_count: number; true_positives: number;
    centerline_extent_match_count: number;
    false_positives: number; false_negatives: number;
    precision: number | null; recall: number | null; f1: number | null;
  }>;
}

export interface SourceEvidenceAudit {
  cloud_id: string;
  candidate_count: number;
  status_counts: { consistent: number; mismatch: number; unverifiable: number };
  status_counts_by_class: Record<string, { consistent: number; mismatch: number; unverifiable: number }>;
  source_snapshot_counts: { current: number; missing: number; stale: number; unchecked: number };
  attention_count: number;
  accuracy_status: "not_measured";
  candidates: {
    id: string;
    class_name: string;
    review_status: string;
    evidence: import("./elementPointEvidence").SourcePointEvidence;
  }[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    let detail: any = response.statusText;
    try {
      detail = await response.json();
    } catch {
      /* keep status text */
    }
    const error = new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail?.detail ?? detail),
    );
    (error as any).detail = detail;
    throw error;
  }
  return (await response.json()) as T;
}

async function download(path: string, method: "GET" | "POST" = "POST", fallback = "export.bin") {
  const response = await fetch(`${BASE}${path}`, { method });
  if (!response.ok) {
    let detail: any = response.statusText;
    try {
      detail = await response.json();
    } catch {
      /* ignore */
    }
    const error = new Error(JSON.stringify(detail?.detail ?? detail));
    (error as any).detail = detail;
    throw error;
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const match = /filename\*?=(?:UTF-8''|")?([^\";]+)/i.exec(disposition);
  const filename = match ? decodeURIComponent(match[1]) : fallback;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export type CloudExportFormat = "e57" | "las" | "laz" | "ply" | "xyz";

export interface CloudExportMeta {
  export_id: string;
  cloud_id: string;
  format: CloudExportFormat;
  point_count: number;
  size_bytes: number;
  has_color: boolean;
  has_intensity: boolean;
  verified: boolean;
  max_deviation_m?: number;
  tolerance_m?: number;
  elapsed_s?: number;
  path?: string;
}

export interface DerivedCloud {
  derived_id: string;
  method: "statistical" | "radius" | "voxel" | string;
  input_count: number;
  output_count: number;
  removed_count: number;
  has_colors: boolean;
  duration_s: number;
  stats?: { voxel_mode?: "representative" | "centroid"; compute_backend?: "cpu" | "cuda" };
  created_at?: string;
}

export interface RegistrationPointPair {
  source_point: [number, number, number];
  target_point: [number, number, number];
  label?: string;
}

export interface PairAlignResponse {
  status: string;
  accuracy_status: "not_measured";
  independent_control_count: number;
  fit_residuals_are_independent: boolean;
  method: string;
  source_cloud_id: string;
  target_cloud_id: string;
  pairs_count: number;
  matrix_4x4: number[][];
  world_matrix_4x4: number[][] | null;
  coordinate_frame: {
    matrix_4x4: "stored_local_source_to_stored_local_target";
    world_matrix_4x4: "source_world_to_target_world" | null;
    source_origin_world_m: number[] | null;
    target_origin_world_m: number[] | null;
  };
  rotation_3x3: number[][];
  translation: number[];
  rmse_mm: number;
  max_error_mm: number;
  residuals_mm: number[];
  pair_details: Array<{
    label: string;
    source: number[];
    target: number[];
    residual_mm: number;
  }>;
  refined_with_icp?: boolean;
  icp_rmse_mm?: number;
  icp_warning?: string;
}

export interface RegistrationControlEvaluationResponse {
  status: "controls_evaluated";
  accuracy_status: "independent_controls_measured";
  independent_control_count: number;
  independence_attested_by_user: true;
  fit_residuals_are_independent: true;
  acceptance_rmse_mm: number;
  rmse_mm: number;
  max_error_mm: number;
  p95_error_mm: number;
  criterion_passed: boolean;
  residuals_mm: number[];
  source_cloud_id: string;
  target_cloud_id: string;
  matrix_4x4: number[][];
  world_matrix_4x4: number[][] | null;
  coordinate_frame: PairAlignResponse["coordinate_frame"];
  control_details: Array<{
    label: string;
    source: number[];
    target: number[];
    residual_mm: number;
  }>;
}

export interface StationRegistrationProposal {
  id: string;
  project_id: string;
  source_station_id: string;
  target_station_id: string;
  source_station_name: string;
  target_station_name: string;
  method: "rigid_icp" | "manual_kabsch" | "manual_kabsch_icp";
  matrix_4x4: number[][];
  world_matrix_4x4: number[][] | null;
  fit_rmse_mm: number | null;
  independent_control_count: number;
  control_rmse_mm: number | null;
  acceptance_rmse_mm: number | null;
  status: "proposed" | "verified";
  matrix_applied: boolean;
  rcp_updated: boolean;
  created_at: string;
  updated_at: string;
}

export interface StationPhotoMeta {
  file: string;
  source: "photo";
  is_photograph: true;
  original_filename: string | null;
  format: string;
  width: number;
  height: number;
  size_bytes: number;
  sha256: string;
  projection: "equirectangular";
  yaw_offset_deg: number;
  station_id: string;
  uploaded_at: string;
}

export interface StationCloudPanoramaMeta {
  cache_key: string;
  station_id: string;
  source: "point_cloud";
  is_photograph: false;
  width: number;
  height: number;
  max_range_m: number;
  anchor: number[];
  anchor_kind: string;
  anchor_note: string;
  coverage: number;
  rendered_points: number;
  source_points: number;
  stride: number;
  color_source: "cloud_rgb" | "height_ramp";
  rendered_at: string;
}

export interface StationPanoramaSummary {
  station_id: string;
  name: string;
  point_count: number;
  station_source: "station_row_ranges" | "cloud";
  anchor: number[];
  anchor_kind: string;
  bbox_min: number[];
  bbox_max: number[];
  photo: StationPhotoMeta | null;
  has_photo: boolean;
  cloud_panorama: StationCloudPanoramaMeta | null;
  has_cloud_panorama: boolean;
  panorama_url: string;
  measure_supported: boolean;
}

export interface StationListResponse {
  cloud_id: string;
  count: number;
  stations: StationPanoramaSummary[];
}

export interface PanoramaPick {
  resolved: boolean;
  u: number;
  v: number;
  pixel?: number[];
  point?: number[];
  point_local?: number[];
  distance_m?: number;
  lateral_precision_m?: number;
  angular_resolution_deg?: number[];
  depth_source?: "point_cloud";
  stable?: boolean;
  stability?: "continuous_surface" | "depth_discontinuity";
  depth_spread_m?: number;
  max_depth_gap_m?: number;
  stability_tolerance_m?: number;
  reason?: string;
}

export interface PanoramaMeasureResult {
  resolved: true;
  distance_m: number;
  distance_mm: number;
  precision_mm: number;
  depth_source: "point_cloud";
  a: PanoramaPick;
  b: PanoramaPick;
  station_id: string;
  reliable?: boolean;
  warning?: string;
  unstable_endpoints?: string[];
}

export const api = {
  health: () => request<{ status: string; version: string; auth_required: boolean }>("/health"),

  listProjects: () => request<Project[]>("/projects"),
  projectJobs: (projectId: string) => request<Job[]>(`/projects/${encodeURIComponent(projectId)}/jobs`),
  createProject: (name: string, description = "") =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name, description, units: "m" }),
    }),
  deleteProject: (id: string) => request<{ deleted: string }>(`/projects/${id}`, { method: "DELETE" }),

  importPath: (projectId: string, path: string, name?: string, maxPoints?: number) =>
    request<Cloud>(`/projects/${projectId}/clouds/import-path`, {
      method: "POST",
      body: JSON.stringify({ path, name, max_points: maxPoints }),
    }),
  importRcpPath: (projectId: string, path: string, namePrefix?: string, maxPoints?: number) =>
    request<RcpImportBatch>(`/projects/${encodeURIComponent(projectId)}/rcp/import-path`, {
      method: "POST",
      body: JSON.stringify({ path, name_prefix: namePrefix, max_points: maxPoints }),
    }),
  uploadCloud: async (projectId: string, file: File, name?: string, maxPoints?: number) => {
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
    if (maxPoints !== undefined) form.append("max_points", String(maxPoints));
    const response = await fetch(`${BASE}/projects/${projectId}/clouds/upload`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => response.statusText);
      const error = new Error(JSON.stringify(detail?.detail ?? detail));
      (error as any).detail = detail;
      throw error;
    }
    return (await response.json()) as Cloud;
  },
  listClouds: (projectId: string) =>
    request<Cloud[]>(`/projects/${projectId}/clouds`),
  getCloud: (id: string) => request<Cloud>(`/clouds/${id}`),
  resumeImport: (id: string) => request<Cloud>(`/clouds/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  previewUrl: (id: string) => `${BASE}/clouds/${id}/preview`,
  listStations: (cloudId: string) =>
    request<StationListResponse>(`/clouds/${encodeURIComponent(cloudId)}/stations`),
  ensureStationPanorama: (
    cloudId: string,
    stationId: string,
    params: { width?: number; height?: number; maxRangeM?: number } = {},
  ) => {
    const query = new URLSearchParams();
    if (params.width !== undefined) query.set("width", String(params.width));
    if (params.height !== undefined) query.set("height", String(params.height));
    if (params.maxRangeM !== undefined) query.set("max_range_m", String(params.maxRangeM));
    return request<
      | { status: "ready"; panorama: StationCloudPanoramaMeta }
      | { status: "queued"; job: Job }
    >(
      `/clouds/${encodeURIComponent(cloudId)}/stations/${encodeURIComponent(stationId)}/panorama/render${
        query.size ? `?${query.toString()}` : ""
      }`,
      { method: "POST" },
    );
  },
  stationPanoramaUrl: (
    cloudId: string,
    stationId: string,
    options: { source?: "auto" | "photo" | "cloud"; version?: string } = {},
  ) => {
    const params = new URLSearchParams({ source: options.source ?? "auto" });
    if (options.version) params.set("v", options.version);
    return `${BASE}/clouds/${encodeURIComponent(cloudId)}/stations/${encodeURIComponent(stationId)}/panorama?${params.toString()}`;
  },
  uploadStationPhoto: async (cloudId: string, stationId: string, file: File, yawOffsetDeg = 0) => {
    const form = new FormData();
    form.append("file", file);
    form.append("yaw_offset_deg", String(yawOffsetDeg));
    const response = await fetch(
      `${BASE}/clouds/${encodeURIComponent(cloudId)}/stations/${encodeURIComponent(stationId)}/photo`,
      { method: "POST", body: form },
    );
    if (!response.ok) {
      const detail = await response.json().catch(() => response.statusText);
      const error = new Error(JSON.stringify(detail?.detail ?? detail));
      (error as any).detail = detail;
      throw error;
    }
    return (await response.json()) as { status: string; station_id: string; photo: StationPhotoMeta };
  },
  deleteStationPhoto: (cloudId: string, stationId: string) =>
    request<{ status: string; station_id: string }>(
      `/clouds/${encodeURIComponent(cloudId)}/stations/${encodeURIComponent(stationId)}/photo`,
      { method: "DELETE" },
    ),
  measureOnStation: (cloudId: string, stationId: string, a: { u: number; v: number }, b: { u: number; v: number }) =>
    request<PanoramaMeasureResult>(
      `/clouds/${encodeURIComponent(cloudId)}/stations/${encodeURIComponent(stationId)}/measure`,
      { method: "POST", body: JSON.stringify({ a, b }) },
    ),
  pickOnStation: (cloudId: string, stationId: string, point: { u: number; v: number }) =>
    request<PanoramaPick>(
      `/clouds/${encodeURIComponent(cloudId)}/stations/${encodeURIComponent(stationId)}/pick`,
      { method: "POST", body: JSON.stringify(point) },
    ),
  getLodManifest: (cloudId: string) =>
    request<LodManifest>(`/clouds/${encodeURIComponent(cloudId)}/lod/manifest`),
  lodBinaryUrl: (cloudId: string, level: number) =>
    `${BASE}/clouds/${encodeURIComponent(cloudId)}/lod/${level}`,
  deleteCloud: (id: string) => request<{ deleted: string }>(`/clouds/${id}`, { method: "DELETE" }),
  demo: () =>
    request<{ project: Project; cloud: Cloud; truth: Record<string, any> }>("/demo", {
      method: "POST",
    }),

  createSection: (cloudId: string, payload: Record<string, unknown>) =>
    request<Section>(`/clouds/${cloudId}/sections`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getSection: (id: string) => request<Section>(`/sections/${id}`),
  exportSection: (sectionId: string, format: "dxf" | "pdf" | "json", scale = 50) =>
    download(`/sections/${sectionId}/export?format=${format}&scale=${scale}`, "POST", `section.${format}`),

  recognize: (cloudId: string) =>
    request<Job>(`/clouds/${cloudId}/recognize`, { method: "POST" }),
  runCleanup: (cloudId: string, payload: Record<string, unknown>) =>
    request<Job>(`/clouds/${cloudId}/cleanup`, { method: "POST", body: JSON.stringify(payload) }),
  pairAlign: (
    sourceCloudId: string,
    targetCloudId: string,
    pairs: RegistrationPointPair[],
    applyIcpRefinement = false,
  ) =>
    request<PairAlignResponse>("/registration/pair-align", {
      method: "POST",
      body: JSON.stringify({
        source_cloud_id: sourceCloudId,
        target_cloud_id: targetCloudId,
        pairs,
        apply_icp_refinement: applyIcpRefinement,
      }),
    }),
  evaluateRegistrationControls: (
    sourceCloudId: string,
    targetCloudId: string,
    matrix4x4: number[][],
    controls: RegistrationPointPair[],
    independentOfFit: boolean,
    acceptanceRmseMm = 10,
  ) =>
    request<RegistrationControlEvaluationResponse>("/registration/evaluate-controls", {
      method: "POST",
      body: JSON.stringify({
        source_cloud_id: sourceCloudId,
        target_cloud_id: targetCloudId,
        matrix_4x4: matrix4x4,
        controls,
        independent_of_fit: independentOfFit,
        acceptance_rmse_mm: acceptanceRmseMm,
      }),
    }),
  listStationRegistrations: (projectId: string) =>
    request<{ project_id: string; items: StationRegistrationProposal[] }>(
      `/projects/${encodeURIComponent(projectId)}/station-registrations`,
    ),
  saveStationRegistration: (
    projectId: string,
    payload: {
      source_station_id: string;
      target_station_id: string;
      method: StationRegistrationProposal["method"];
      matrix_4x4: number[][];
      world_matrix_4x4: number[][] | null;
      fit_rmse_mm: number | null;
    },
  ) => request<{ status: "proposed"; accuracy_status: "not_measured"; message: string; item: StationRegistrationProposal }>(
    `/projects/${encodeURIComponent(projectId)}/station-registrations`,
    { method: "POST", body: JSON.stringify(payload) },
  ),
  derivedClouds: (cloudId: string) =>
    request<DerivedCloud[]>(`/clouds/${cloudId}/derived`),
  exportCloud: (cloudId: string, format: CloudExportFormat, options: { derivedId?: string | null; verify?: boolean } = {}) =>
    request<Job>(`/clouds/${encodeURIComponent(cloudId)}/export`, {
      method: "POST",
      body: JSON.stringify({
        format,
        derived_id: options.derivedId ?? null,
        verify: options.verify ?? true,
      }),
    }),
  cloudExports: (cloudId: string) =>
    request<CloudExportMeta[]>(`/clouds/${encodeURIComponent(cloudId)}/exports`),
  downloadCloudExport: (cloudId: string, exportId: string, format: CloudExportFormat) =>
    download(
      `/clouds/${encodeURIComponent(cloudId)}/exports/${encodeURIComponent(exportId)}/download`,
      "GET",
      `cloud.${format}`,
    ),
  downloadDerived: (cloudId: string, derivedId: string, format: "ply" | "xyz" | "npy") =>
    download(
      `/clouds/${cloudId}/derived/${encodeURIComponent(derivedId)}/download?format=${format}`,
      "GET",
      `cloud.${format}`,
    ),
  elements: (cloudId: string) => request<Element[]>(`/clouds/${cloudId}/elements`),
  columnTypes: (cloudId: string) => request<ColumnTypesResponse>(`/clouds/${encodeURIComponent(cloudId)}/column-types`),
  projectColumnReferenceTypes: (projectId: string) =>
    request<ProjectColumnReferenceTypes>(`/projects/${encodeURIComponent(projectId)}/column-reference-types`),
  columnAnnotations: (cloudId: string) =>
    request<ColumnAnnotationDataset>(`/clouds/${encodeURIComponent(cloudId)}/column-annotations`),
  columnAnnotationHistory: (cloudId: string) =>
    request<ColumnAnnotationArchiveResponse>(`/clouds/${encodeURIComponent(cloudId)}/column-annotations/history`),
  saveColumnAnnotation: (cloudId: string, elementId: string, payload: ColumnAnnotationDraft) =>
    request<ColumnAnnotation>(`/clouds/${encodeURIComponent(cloudId)}/column-annotations/${encodeURIComponent(elementId)}`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  exportColumnAnnotations: (cloudId: string) =>
    request<Record<string, unknown>>(`/clouds/${encodeURIComponent(cloudId)}/column-annotations/export`),
  elementAnnotations: (cloudId: string) =>
    request<ElementAnnotationDataset>(`/clouds/${encodeURIComponent(cloudId)}/element-annotations`),
  elementAnnotationHistory: (cloudId: string) =>
    request<ElementAnnotationArchiveResponse>(`/clouds/${encodeURIComponent(cloudId)}/element-annotations/history`),
  saveElementAnnotation: (cloudId: string, elementId: string, payload: ElementAnnotationDraft) =>
    request<ElementAnnotation>(`/clouds/${encodeURIComponent(cloudId)}/element-annotations/${encodeURIComponent(elementId)}`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  exportElementAnnotations: (cloudId: string) =>
    request<Record<string, unknown>>(`/clouds/${encodeURIComponent(cloudId)}/element-annotations/export`),
  evaluateRecognition: (cloudId: string, payload: RecognitionEvaluationRequest) =>
    request<RecognitionEvaluationReport>(`/clouds/${encodeURIComponent(cloudId)}/recognition-evaluation`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  fitColumnSection: (elementId: string, payload: {
    slice_z_m?: number; thickness_m: number; known_sides_m?: [number, number];
    distance_tolerance_m?: number; candidate_margin_m?: number;
  }) => request<ColumnSectionFitResponse>(`/elements/${encodeURIComponent(elementId)}/section-fit`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  fitColumnSectionBatch: (elementId: string, payload: {
    slice_z_values_m: number[]; thickness_m: number; known_sides_m?: [number, number];
    distance_tolerance_m?: number; candidate_margin_m?: number;
  }) => request<ColumnSectionBatchFitResponse>(`/elements/${encodeURIComponent(elementId)}/section-fit-batch`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  analyzeColumnSurfaceTracks: (elementId: string) =>
    request<ColumnSurfaceTrackAnalysisResponse>(`/elements/${encodeURIComponent(elementId)}/surface-track-analysis`, {
      method: "POST",
    }),
  confirmColumnType: (proposalKey: string, cloudId: string, mark: string, linearTolerance = 0.005, relativeTolerance = 0.01) =>
    request<ColumnTypeAction>(`/column-types/${encodeURIComponent(proposalKey)}/confirm`, {
      method: "POST",
      body: JSON.stringify({ cloud_id: cloudId, mark, linear_tolerance_m: linearTolerance, relative_tolerance: relativeTolerance }),
    }),
  assignColumnType: (elementId: string, typeId: string | null) =>
    request<ColumnTypeAction>(`/elements/${encodeURIComponent(elementId)}/column-type`, {
      method: "POST", body: JSON.stringify({ type_id: typeId }),
    }),
  rejectColumnType: (proposalKey: string, cloudId: string, note: string, linearTolerance = 0.005, relativeTolerance = 0.01) =>
    request<ColumnTypeAction>(`/column-types/${encodeURIComponent(proposalKey)}/reject`, {
      method: "POST",
      body: JSON.stringify({ cloud_id: cloudId, note, linear_tolerance_m: linearTolerance, relative_tolerance: relativeTolerance }),
    }),
  undoColumnTypeAction: (actionId: string) =>
    request<ColumnTypeAction>(`/column-types/actions/${encodeURIComponent(actionId)}/undo`, {
      method: "POST", body: JSON.stringify({}),
    }),
  feedback: (elementId: string, payload: Record<string, unknown>) =>
    request<any>(`/elements/${elementId}/feedback`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  elementHistory: (elementId: string) => request<any[]>(`/elements/${elementId}/history`),
  undoFeedback: (elementId: string, feedbackId: string) =>
    request<any>(`/elements/${elementId}/history/${feedbackId}/undo`, { method: "POST" }),
  elementPoints: (elementId: string, limit = 4000) =>
    request<{
      count: number;
      points: number[][];
      bbox_coordinate_frame: "cloud_local" | "source_cloud_world";
      source_point_evidence: import("./elementPointEvidence").SourcePointEvidence;
    }>(`/elements/${elementId}/points?limit=${limit}`),
  sourceEvidenceAudit: (cloudId: string) =>
    request<SourceEvidenceAudit>(`/clouds/${encodeURIComponent(cloudId)}/source-evidence-audit`),
  similar: (elementId: string, k = 5) =>
    request<any[]>(`/elements/${elementId}/similar?k=${k}`),

  exportBim: (cloudId: string, format: "json" | "ifc") =>
    download(`/clouds/${cloudId}/bim?format=${format}`, "GET", `model.${format}`),
  exportElementsDxf: (cloudId: string) =>
    download(`/clouds/${cloudId}/elements.dxf`, "GET", "elements.dxf"),
  exportStructuralPlanDxf: (cloudId: string, type: "columns" | "crane_girders", issue: "draft" | "final" = "final") =>
    download(`/clouds/${cloudId}/structural-plan.dxf?type=${type}&issue=${issue}`, "GET", `plan-${issue}-${type}.dxf`),
  exportStructuralPlanPdf: (cloudId: string, type: "columns" | "crane_girders", scale = 100, issue: "draft" | "final" = "final") =>
    download(`/clouds/${cloudId}/structural-plan.pdf?type=${type}&scale=${scale}&issue=${issue}`, "GET", `plan-${issue}-${type}.pdf`),
  exportSpdsAlbum: (cloudId: string) =>
    download(`/clouds/${encodeURIComponent(cloudId)}/spds-album.zip`, "GET", "spds-album-draft.zip"),
  exportSpdsAlbumPdf: (cloudId: string) =>
    download(`/clouds/${encodeURIComponent(cloudId)}/spds-album.pdf`, "GET", "ALBUM_RD_KR_KM_SPDS.pdf"),

  samples: (projectId: string) => request<TrainingSample[]>(`/projects/${projectId}/samples`),
  learningManifestPreview: (projectId: string) =>
    request<LearningManifestPreview>(`/projects/${encodeURIComponent(projectId)}/learning-manifest/preview`),
  exportLearningManifest: (projectId: string, manifestSha256: string) =>
    request<LearningManifestExportResult>(`/projects/${encodeURIComponent(projectId)}/learning-manifests/export`, {
      method: "POST",
      body: JSON.stringify({ confirmed: true, expected_manifest_sha256: manifestSha256 }),
    }),
  train: (projectId: string, payload: Record<string, unknown>) =>
    request<ModelInfo>(`/projects/${projectId}/train`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  models: () => request<ModelInfo[]>("/models"),
  modelStatus: (projectId: string) => request<any>(`/projects/${projectId}/model-status`),
  activateModel: (modelId: string) =>
    request<ModelInfo>(`/models/${modelId}/activate`, { method: "POST" }),
  rollback: (name = "geometric-knn") =>
    request<ModelInfo>(`/models/rollback?name=${encodeURIComponent(name)}`, { method: "POST" }),

  getJob: (id: string) => request<Job>(`/jobs/${id}`),
  cancelJob: (id: string) => request<{ job_id: string; cancel_requested: boolean; status: string }>(
    `/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" },
  ),
  formats: () => request<any>("/formats"),
  rcsGuidance: (path?: string) =>
    request<any>(`/formats/rcs${path ? `?path=${encodeURIComponent(path)}` : ""}`),

  // Desktop OS integrations
  desktopStatus: () => request<{ platform: string; autocad_available: boolean; recap_available: boolean; revit_available?: boolean }>("/desktop/status"),
  openInAutoCAD: (path: string) => request<{ status: string; app: string }>("/desktop/open-autocad", { method: "POST", body: JSON.stringify({ path }) }),
  openInReCap: (path?: string) => request<{ status: string; app: string }>("/desktop/open-recap", { method: "POST", body: JSON.stringify({ path: path || "" }) }),
  openInRevit: (path?: string) => request<{ status: string; app: string }>("/desktop/open-revit", { method: "POST", body: JSON.stringify({ path: path || "" }) }),
  openInExplorer: (path: string) => request<{ status: string; path: string }>("/desktop/open-explorer", { method: "POST", body: JSON.stringify({ path }) }),
  pickFileWindows: (title?: string) => request<{ cancelled: boolean; path?: string; filename?: string; size_bytes?: number; extension?: string }>("/desktop/pick-file", { method: "POST", body: JSON.stringify({ title: title || "Выберите файл облака точек" }) }),

  // Registration & Stitching
  matchCloudsIcp: (sourceCloudId: string, targetCloudId: string, samplePoints = 20000, maxIterations = 30) =>
    request<{
      rotation: number[][];
      translation: number[];
      matrix_4x4: number[][];
      world_matrix_4x4: number[][] | null;
      coordinate_frame: PairAlignResponse["coordinate_frame"];
      rmse_mm: number | null;
      inlier_count: number;
      source_sample_count: number;
      target_sample_count: number;
      inlier_fraction: number;
      iterations: number;
      converged: boolean;
    }>("/registration/match", {
      method: "POST",
      body: JSON.stringify({
        source_cloud_id: sourceCloudId,
        target_cloud_id: targetCloudId,
        sample_points: samplePoints,
        max_iterations: maxIterations,
      }),
    }),
  exportStitchedPly: (projectName: string, stations: any[]) =>
    request<{ status: string; output_path: string; size_bytes: number }>("/registration/export-ply", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName, stations }),
    }),
  exportRecapProject: (projectName: string, stations: any[]) =>
    request<{ status: string; output_path: string; stations_count: number }>("/registration/export-recap", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName, stations }),
    }),
  exportNativeRecapProject: (projectName: string, stations: Array<{ name: string; path: string; point_count?: number }>) =>
    request<{
      status: "created_by_autodesk_decap";
      project_verified: boolean;
      package_verified: boolean;
      rcp_path: string;
      support_dir: string;
      input_scan_count: number;
      rcp_node_count: number;
      linked_rcs_count: number;
      external_rcs_count: number;
      external_rcs_paths: string[];
      source_files_copied_for_decap: boolean;
      source_cache_path: string | null;
      rcp_size_bytes: number;
      linked_rcs_size_bytes: number;
    }>("/registration/export-rcp-project", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName, stations }),
    }),
  bundleAdjustment: (payload: {
    station_ids: string[];
    constraints: Array<{
      from_id: string;
      to_id: string;
      matrix_4x4: number[][];
      weight?: number;
      rmse_mm?: number;
    }>;
    fixed_station_id?: string;
  }) =>
    request<{
      status: string;
      success: boolean;
      iterations: number;
      initial_error: number;
      final_error: number;
      optimized_poses: Record<string, number[][]>;
    }>("/registration/bundle-adjustment", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  detectTargets: (cloudId: string, expectedRadiusM?: number, samplePoints?: number) =>
    request<{
      status: string;
      cloud_id: string;
      targets_found: number;
      targets: Array<{
        target_type: string;
        center: number[];
        radius_m: number;
        inlier_count: number;
        residual_rms_mm: number;
      }>;
    }>("/registration/detect-targets", {
      method: "POST",
      body: JSON.stringify({
        cloud_id: cloudId,
        expected_radius_m: expectedRadiusM ?? 0.0725,
        sample_points: samplePoints ?? 200000,
      }),
    }),

  // AI Workshop Construction Expert Agent
  askWorkshopExpert: (query: string, cloudContext?: any) =>
    request<{
      topic: string;
      answer: string;
      recommendations: string[];
      referenced_norms: string[];
      cad_shortcut_tips: string[];
    }>("/expert/ask", {
      method: "POST",
      body: JSON.stringify({ query, cloud_context: cloudContext }),
    }),

  getWorkshopKnowledgeSummary: () =>
    request<{
      status: string;
      knowledge_base: Record<string, {
        title: string;
        gost_norms: string[];
        description: string;
        tolerances_sp70?: Record<string, string>;
        drafting_rules: string;
      }>;
      workshop_topology: {
        confirmed_inputs: {
          longitudinal_column_pitch_m: number;
          source: string;
        };
        engineering_tolerance_mm: number | null;
        hall_length_m: number | null;
        hall_width_m: number | null;
        spans: { name: string; row_from: string; row_to: string; width_m: number }[] | null;
        rows: Record<string, number> | null;
        axes_count: number | null;
        elevations: Record<string, { z_scan: number; label: string }> | null;
        crane_capacity_tons: number | null;
        standards: string[];
      };
    }>("/expert/knowledge-summary"),
};

export async function waitForJob(
  jobId: string,
  onUpdate?: (job: Job) => void,
  timeoutMs = 15 * 60 * 1000,
): Promise<Job> {
  const start = Date.now();
  for (;;) {
    const job = await api.getJob(jobId);
    onUpdate?.(job);
    if (["succeeded", "failed", "cancelled"].includes(job.status)) return job;
    if (Date.now() - start > timeoutMs) throw new Error("job timed out");
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
}

export async function waitForCloud(
  cloudId: string,
  onUpdate?: (cloud: Cloud) => void,
  timeoutMs = 30 * 60 * 1000,
): Promise<Cloud> {
  const start = Date.now();
  for (;;) {
    const cloud = await api.getCloud(cloudId);
    onUpdate?.(cloud);
    if (["ready", "failed", "cancelled"].includes(cloud.status)) return cloud;
    if (Date.now() - start > timeoutMs) throw new Error("cloud processing timed out");
    await new Promise((resolve) => setTimeout(resolve, 900));
  }
}
