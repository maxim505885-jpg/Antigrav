import type { Cloud, Element, Job, ModelInfo, Project, Section } from "./types";

const BASE = "/api/v1";

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
  feedback: (elementId: string, payload: Record<string, unknown>) =>
    request<any>(`/elements/${elementId}/feedback`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  elementPoints: (elementId: string, limit = 4000) =>
    request<{ count: number; points: number[][] }>(`/elements/${elementId}/points?limit=${limit}`),
  similar: (elementId: string, k = 5) =>
    request<any[]>(`/elements/${elementId}/similar?k=${k}`),

  exportBim: (cloudId: string, format: "json" | "ifc") =>
    download(`/clouds/${cloudId}/bim?format=${format}`, "GET", `model.${format}`),
  exportElementsDxf: (cloudId: string) =>
    download(`/clouds/${cloudId}/elements.dxf`, "GET", "elements.dxf"),

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
  formats: () => request<any>("/formats"),
  rcsGuidance: (path?: string) =>
    request<any>(`/formats/rcs${path ? `?path=${encodeURIComponent(path)}` : ""}`),
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
    if (job.status === "succeeded" || job.status === "failed") return job;
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
    if (cloud.status === "ready" || cloud.status === "failed") return cloud;
    if (Date.now() - start > timeoutMs) throw new Error("cloud processing timed out");
    await new Promise((resolve) => setTimeout(resolve, 900));
  }
}
