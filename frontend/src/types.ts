export interface Project {
  id: string;
  name: string;
  description: string;
  units: string;
  created_at: string;
  updated_at: string;
  cloud_count?: number;
  element_count?: number;
}

export interface Cloud {
  id: string;
  project_id: string;
  name: string;
  source_path: string;
  source_format: string;
  size_bytes: number;
  point_count: number;
  ingested_count: number;
  decimated: boolean;
  origin: [number, number, number] | null;
  bbox_min: [number, number, number] | null;
  bbox_max: [number, number, number] | null;
  has_color: boolean;
  has_intensity: boolean;
  status: "processing" | "ready" | "failed" | string;
  error?: string | null;
  preview_count: number;
  created_at: string;
  updated_at: string;
  metadata: Record<string, any>;
  warning?: string | null;
}

export interface Frame {
  kind: "horizontal" | "vertical";
  axis: "x" | "y" | null;
  plane: string;
  u_axis: string;
  v_axis: string;
  w_axis: string;
  position_world: number;
  thickness: number;
  world_offset: [number, number];
  u_label: string;
  v_label: string;
}

export interface Polygon {
  points: [number, number][];
  area: number;
  perimeter: number;
  bbox: [number, number, number, number];
  component: number;
  is_hole: boolean;
}

export interface SectionResult {
  frame: Frame;
  polygons: Polygon[];
  preview_points: [number, number][];
  point_count: number;
  slab_point_count: number;
  density_pts_per_m2?: number;
  grid_res: number;
  total_area_m2: number;
  warnings: string[];
  regularization?: { enabled: boolean; angle_deg: number; concentration: number } | null;
  measured?: boolean;
  note?: string;
}

export interface Section {
  id: string;
  cloud_id: string;
  kind: string;
  axis: string | null;
  position: number;
  thickness: number;
  grid_res: number;
  point_count: number;
  created_at: string;
  result: SectionResult;
}

export interface Element {
  id: string;
  project_id: string;
  cloud_id: string;
  parent_id?: string | null;
  class_name: string;
  geometry: any;
  bbox: { min: number[]; max: number[] };
  confidence: number;
  confidence_kind: string;
  measured: boolean;
  inferred: boolean;
  source: string;
  review_status: string;
  dimensions: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  project_id: string | null;
  cloud_id: string | null;
  type: string;
  status: "queued" | "running" | "succeeded" | "failed" | string;
  progress: number;
  message: string;
  result: Record<string, any>;
  error?: string | null;
}

export interface ModelInfo {
  id: string;
  name: string;
  version: number;
  kind: string;
  path: string;
  metrics: Record<string, any>;
  status: string;
  notes: string;
  created_at: string;
  activated_at?: string | null;
}

export interface RecognitionSummary {
  levels: { z: number; point_count: number; confidence: number }[];
  stats: Record<string, any>;
  warnings: string[];
  recognised_at: string;
}

/** Русские подписи для кодов классов. Код класса в API остаётся латиницей. */
export const CLASS_LABELS: Record<string, string> = {
  wall: "стена",
  column: "колонна",
  beam: "балка",
  girder: "ригель",
  slab: "плита перекрытия",
  roof: "покрытие",
  truss: "ферма",
  brace: "связь",
  stair: "лестница",
  opening: "проём",
  pipe: "труба",
  duct: "воздуховод",
  equipment: "оборудование",
  other: "другое",
  unknown: "неизвестно",
};

export function classLabel(name: string): string {
  return CLASS_LABELS[name] || name;
}

export const REVIEW_LABELS: Record<string, string> = {
  unreviewed: "не проверено",
  confirmed: "подтверждено",
  corrected: "исправлено",
  rejected: "отклонено",
};

export const STATUS_LABELS: Record<string, string> = {
  queued: "в очереди",
  running: "выполняется",
  succeeded: "готово",
  failed: "ошибка",
  processing: "обработка",
  ready: "готово",
  candidate: "кандидат",
  active: "активна",
  archived: "в архиве",
};

export function statusLabel(name: string): string {
  return STATUS_LABELS[name] || name;
}

export const CLASSES = [
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
];
