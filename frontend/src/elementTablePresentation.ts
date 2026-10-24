import type { Element } from "./types.ts";

function isFinitePoint(value: unknown): value is [number, number, number] {
  return Array.isArray(value)
    && value.length >= 3
    && value.slice(0, 3).every((coordinate) => typeof coordinate === "number" && Number.isFinite(coordinate));
}

export function elementPlanDimensionSummary(element: Element): string {
  const min = element.bbox?.min;
  const max = element.bbox?.max;
  if (!isFinitePoint(min) || !isFinitePoint(max)) return "габарит не определён";

  const widthMm = Math.round(Math.abs(max[0] - min[0]) * 1000);
  const depthMm = Math.round(Math.abs(max[1] - min[1]) * 1000);
  if (widthMm > 0 && depthMm > 0) return `${widthMm} × ${depthMm} мм (bbox)`;

  const geometry = element.geometry as { kind?: unknown; p0?: unknown; p1?: unknown } | undefined;
  if (geometry?.kind === "member" && isFinitePoint(geometry.p0) && isFinitePoint(geometry.p1)) {
    return "ось кандидата · сечение не измерено";
  }
  return "габарит не измерен (bbox вырожден)";
}
