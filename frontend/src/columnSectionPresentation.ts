type ColumnDimensions = Record<string, unknown>;

function measuredSide(value: unknown, label: string): string | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return null;
  return `${label} ${Math.round(value * 1000)} мм`;
}

/** Summarize incomplete section evidence without exposing coarse box sizes as measurements. */
export function columnSectionObservationSummary(dimensions: ColumnDimensions): string | null {
  if (dimensions.section_status === "partial_one_axis") {
    const axes = dimensions.measured_section_axes_m;
    const evidence = axes && typeof axes === "object" ? axes as Record<string, unknown> : {};
    const observed = [
      measuredSide(evidence.length, "длина"),
      measuredSide(evidence.thickness, "толщина"),
    ].filter((value): value is string => value !== null);
    return `сечение частичное: ${observed.join(", ") || "размерность не определена"}`;
  }
  if (dimensions.section_status === "coarse_grid_only" || dimensions.section_status === "unconfirmed") {
    return "сечение не измерено";
  }
  return null;
}

type ObservedFace = { start_world_m: [number, number]; end_world_m: [number, number] };

/** Warn when fitted planes are parallel traces rather than a rectangular section contour. */
export function parallelFaceObservationSummary(faces: ObservedFace[]): string | null {
  if (faces.length < 2) return null;
  const orientations = faces.map(({ start_world_m: start, end_world_m: end }) => {
    const angle = Math.atan2(end[1] - start[1], end[0] - start[0]);
    return ((angle % Math.PI) + Math.PI) % Math.PI;
  });
  const maxDifference = orientations.reduce((maximum, angle, index) => {
    const difference = orientations.slice(index + 1).reduce((innerMaximum, other) => {
      const direct = Math.abs(angle - other);
      return Math.max(innerMaximum, Math.min(direct, Math.PI - direct));
    }, 0);
    return Math.max(maximum, difference);
  }, 0);
  if (maxDifference > 12 * Math.PI / 180) return null;
  return `Обнаружено параллельных поверхностей: ${faces.length}. Они не подтверждают замкнутый прямоугольный контур колонны.`;
}
