import type { ColumnAnnotation } from "./api";
import type { Element } from "./types";

export interface ColumnAnnotationQueueStats {
  total: number;
  reviewed: number;
  pending: number;
  labeled: number;
  unknown: number;
  excluded: number;
}

export function columnAnnotationQueueStats(
  columns: readonly Element[],
  annotations: readonly Pick<ColumnAnnotation, "element_id" | "state">[],
): ColumnAnnotationQueueStats {
  const byElement = new Map(annotations.map((item) => [item.element_id, item.state]));
  let pending = 0;
  let labeled = 0;
  let unknown = 0;
  let excluded = 0;
  for (const column of columns) {
    const state = byElement.get(column.id) ?? "pending";
    if (state === "pending") pending += 1;
    else if (state === "labeled") labeled += 1;
    else if (state === "unknown") unknown += 1;
    else if (state === "excluded") excluded += 1;
  }
  return { total: columns.length, reviewed: columns.length - pending, pending, labeled, unknown, excluded };
}

export function nextPendingColumn(
  columns: readonly Element[],
  annotations: readonly Pick<ColumnAnnotation, "element_id" | "state">[],
  currentElementId: string,
): Element | null {
  const ordered = [...columns].sort((a, b) => a.id.localeCompare(b.id));
  if (ordered.length < 2) return null;
  const byElement = new Map(annotations.map((item) => [item.element_id, item.state]));
  const currentIndex = ordered.findIndex((item) => item.id === currentElementId);
  const start = currentIndex < 0 ? -1 : currentIndex;
  for (let offset = 1; offset < ordered.length; offset += 1) {
    const candidate = ordered[(start + offset + ordered.length) % ordered.length];
    if ((byElement.get(candidate.id) ?? "pending") === "pending") return candidate;
  }
  return null;
}
