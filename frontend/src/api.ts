import type { Cloud, Element, Job, ModelInfo, Project, Section } from "./types";

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
  z_measurements: { z_m: number; sides_m: { long: number; short: number } | null; note: string }[];
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

export const api = {
  health: () => request<{ status: string; version: string; auth_required: boolean }>("/health"),

  listProjects: () => request<Project[]>("/projects"),
  createProject: (name: string, description = "") =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name, description, units: "m" }),
    }),
  deleteProject: (id: string) => request<{ deleted: string }>(`/projects/${id}`, { method: "DELETE" }),

  importPath: (projectId: string, path: string, name?: string) =>
    request<Cloud>(`/projects/${projectId}/clouds/import-path`, {
      method: "POST",
      body: JSON.stringify({ path, name }),
    }),
  uploadCloud: async (projectId: string, file: File, name?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
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
  elements: (cloudId: string) => request<Element[]>(`/clouds/${cloudId}/elements`),
  columnTypes: (cloudId: string) => request<ColumnTypesResponse>(`/clouds/${encodeURIComponent(cloudId)}/column-types`),
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
  fitColumnSection: (elementId: string, payload: {
    slice_z_m?: number; thickness_m: number; known_sides_m?: [number, number];
    distance_tolerance_m?: number; candidate_margin_m?: number;
  }) => request<ColumnSectionFitResponse>(`/elements/${encodeURIComponent(elementId)}/section-fit`, {
    method: "POST", body: JSON.stringify(payload),
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
    request<{ count: number; points: number[][] }>(`/elements/${elementId}/points?limit=${limit}`),
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

  samples: (projectId: string) => request<any[]>(`/projects/${projectId}/samples`),
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
  desktopStatus: () => request<{ platform: string; autocad_available: boolean; recap_available: boolean }>("/desktop/status"),
  openInAutoCAD: (path: string) => request<{ status: string; app: string }>("/desktop/open-autocad", { method: "POST", body: JSON.stringify({ path }) }),
  openInReCap: (path?: string) => request<{ status: string; app: string }>("/desktop/open-recap", { method: "POST", body: JSON.stringify({ path: path || "" }) }),
  openInExplorer: (path: string) => request<{ status: string; path: string }>("/desktop/open-explorer", { method: "POST", body: JSON.stringify({ path }) }),
  pickFileWindows: (title?: string) => request<{ cancelled: boolean; path?: string; filename?: string; size_bytes?: number; extension?: string }>("/desktop/pick-file", { method: "POST", body: JSON.stringify({ title: title || "Выберите файл облака точек" }) }),

  // Registration & Stitching
  matchCloudsIcp: (sourceCloudId: string, targetCloudId: string, samplePoints = 20000, maxIterations = 30) =>
    request<{
      rotation: number[][];
      translation: number[];
      matrix_4x4: number[][];
      rmse_mm: number;
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