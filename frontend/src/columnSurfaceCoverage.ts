import type { ColumnSectionFitResponse } from "./api";

export type ColumnSurfaceSide = "u+" | "u-" | "v+" | "v-";
export type SurfaceCellStatus = "observed" | "partial" | "no_points" | "ambiguous" | "unknown";

export interface SurfaceCell {
  status: SurfaceCellStatus;
  coverage_fraction: number | null;
  observed_span_m: number | null;
  edge_length_m: number | null;
}

export interface SurfaceCoverageRow {
  slice_z_m: number;
  sides: Record<ColumnSurfaceSide, SurfaceCell>;
}

interface OrientedBox {
  center: [number, number, number];
  rotation_z: number;
  sizes: { length: number; thickness: number; height: number };
}

type Fit = Pick<ColumnSectionFitResponse, "slice_z_m" | "hypotheses">;

const SIDES: ColumnSurfaceSide[] = ["u+", "u-", "v+", "v-"];
const emptyCell = (status: SurfaceCellStatus): SurfaceCell => ({ status, coverage_fraction: null, observed_span_m: null, edge_length_m: null });
const emptySides = (status: SurfaceCellStatus): Record<ColumnSurfaceSide, SurfaceCell> => Object.fromEntries(
  SIDES.map((side) => [side, emptyCell(status)]),
) as Record<ColumnSurfaceSide, SurfaceCell>;

export function createSectionSampleHeights(box: OrientedBox, count: number, thicknessM: number): number[] {
  const height = box.sizes?.height;
  const centerZ = box.center?.[2];
  if (!Number.isInteger(count) || count < 3 || count > 9 || count % 2 === 0) {
    throw new Error("Количество уровней должно быть нечётным целым числом от 3 до 9.");
  }
  if (!Number.isFinite(height) || height <= 0 || !Number.isFinite(centerZ) ||
      !Number.isFinite(thicknessM) || thicknessM <= 0 || thicknessM >= height) {
    throw new Error("Высота колонны должна быть больше толщины среза.");
  }
  const margin = thicknessM / 2;
  const low = centerZ - height / 2 + margin;
  const high = centerZ + height / 2 - margin;
  return Array.from({ length: count }, (_, index) => Number((low + (high - low) * index / (count - 1)).toPrecision(12)));
}

function edgeSide(start: [number, number], end: [number, number], box: OrientedBox): ColumnSurfaceSide | null {
  const [cx, cy] = box.center;
  const angle = box.rotation_z || 0;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const x = (start[0] + end[0]) / 2 - cx;
  const y = (start[1] + end[1]) / 2 - cy;
  const u = x * cos + y * sin;
  const v = -x * sin + y * cos;
  const halfU = box.sizes.length / 2;
  const halfV = box.sizes.thickness / 2;
  const uError = Math.abs(Math.abs(u) - halfU) / Math.max(halfU, 1e-9);
  const vError = Math.abs(Math.abs(v) - halfV) / Math.max(halfV, 1e-9);
  if (Math.min(uError, vError) > 0.35 || Math.abs(uError - vError) < 0.1) return null;
  if (uError < vError) return u >= 0 ? "u+" : "u-";
  return v >= 0 ? "v+" : "v-";
}

export function buildColumnSurfaceCoverage(fits: Fit[], box: OrientedBox): SurfaceCoverageRow[] {
  return [...fits].sort((a, b) => a.slice_z_m - b.slice_z_m).map((fit) => {
    if (!fit.hypotheses.length) return { slice_z_m: fit.slice_z_m, sides: emptySides("unknown") };
    if (fit.hypotheses.length !== 1) return { slice_z_m: fit.slice_z_m, sides: emptySides("ambiguous") };

    const hypothesis = fit.hypotheses[0];
    const sides = emptySides("unknown");
    const assigned = new Set<ColumnSurfaceSide>();
    hypothesis.edge_observation_coverage.forEach((edge) => {
      const start = hypothesis.corners_world_m[edge.edge_index];
      const end = hypothesis.corners_world_m[(edge.edge_index + 1) % hypothesis.corners_world_m.length];
      if (!start || !end) return;
      const side = edgeSide(start, end, box);
      if (!side || assigned.has(side)) {
        if (side) sides[side] = emptyCell("ambiguous");
        return;
      }
      assigned.add(side);
      const fraction = edge.coverage_fraction;
      if (!Number.isFinite(fraction) || fraction < 0 || fraction > 1 || !Number.isFinite(edge.length_m) || !Number.isFinite(edge.observed_span_m)) return;
      sides[side] = {
        status: fraction === 0 ? "no_points" : fraction >= 0.999 ? "observed" : "partial",
        coverage_fraction: fraction,
        observed_span_m: edge.observed_span_m,
        edge_length_m: edge.length_m,
      };
    });
    return { slice_z_m: fit.slice_z_m, sides };
  });
}
