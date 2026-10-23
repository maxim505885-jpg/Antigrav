type ColumnGeometry = Record<string, unknown>;
type ColumnDimensions = Record<string, unknown>;

export interface ColumnTypeSides {
  long: number;
  short: number;
  source: "point-section" | "model-dimensions";
}

const POINT_MEASURED_STATUSES = new Set([
  "measured_2_axes", "measured_3_sides", "measured_4_sides", "unique_section",
]);
const INCOMPLETE_STATUSES = new Set(["partial_one_axis", "coarse_grid_only", "unconfirmed"]);

function finitePositive(value: unknown): number | null {
  if (typeof value === "boolean" || value == null) return null;
  const number = typeof value === "number" || typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(number) && number > 0 ? number : null;
}

function measuredSide(
  geometry: ColumnGeometry,
  dimensions: ColumnDimensions,
  geometryKey: string,
  dimensionKey: string,
): number | null {
  const sizes = geometry.sizes && typeof geometry.sizes === "object"
    ? geometry.sizes as Record<string, unknown>
    : {};
  if (Object.hasOwn(sizes, geometryKey)) return finitePositive(sizes[geometryKey]);
  if (Object.hasOwn(dimensions, dimensionKey)) return finitePositive(dimensions[dimensionKey]);
  return null;
}

/** Use the same point-section-first dimension source as backend column typing. */
export function measuredColumnTypeSides(
  element: { geometry?: unknown; dimensions?: unknown } | null | undefined,
): ColumnTypeSides | null {
  if (!element) return null;
  const geometry = element.geometry && typeof element.geometry === "object"
    ? element.geometry as ColumnGeometry
    : {};
  const dimensions = element.dimensions && typeof element.dimensions === "object"
    ? element.dimensions as ColumnDimensions
    : {};
  const sectionStatus = dimensions.section_status;

  if (POINT_MEASURED_STATUSES.has(String(sectionStatus))) {
    const section = dimensions.measured_section_m;
    if (!Array.isArray(section) || section.length !== 2) return null;
    const first = finitePositive(section[0]);
    const second = finitePositive(section[1]);
    if (first == null || second == null) return null;
    return { long: Math.max(first, second), short: Math.min(first, second), source: "point-section" };
  }
  if (INCOMPLETE_STATUSES.has(String(sectionStatus))) return null;

  const length = measuredSide(geometry, dimensions, "length", "length_m");
  const thickness = measuredSide(geometry, dimensions, "thickness", "thickness_m");
  if (length == null || thickness == null) return null;
  return { long: Math.max(length, thickness), short: Math.min(length, thickness), source: "model-dimensions" };
}
