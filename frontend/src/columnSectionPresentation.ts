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
