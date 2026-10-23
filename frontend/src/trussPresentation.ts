export interface TrussDimensions {
  completeness?: string;
  span_m?: number;
  height_m?: number;
  panels?: number;
  observed_panels?: number;
  diagonals?: number;
  missing_evidence?: string[];
}

export function trussCompletenessBadge(dimensions: TrussDimensions): { text: string; title: string } | null {
  if (dimensions.completeness !== "partial") return null;
  const missing = Array.isArray(dimensions.missing_evidence) && dimensions.missing_evidence.length > 0
    ? dimensions.missing_evidence.join(", ")
    : "недостаточно стержней для полной гипотезы";
  return {
    text: "неполная ферма",
    title: `Показаны только найденные стержни; недостающие не достраиваются. Не хватает evidence: ${missing}.`,
  };
}

export function trussDimensionSummary(dimensions: TrussDimensions): string {
  const span = dimensions.span_m ?? "—";
  const height = dimensions.height_m ?? "—";
  const panels = dimensions.observed_panels ?? dimensions.panels ?? "—";
  const coverage = dimensions.completeness === "partial"
    ? " · неполный кандидат, размеры только наблюдаемой части"
    : "";
  return `пролёт ${span} × выс ${height} м · наблюдаемых стоек: ${panels}${coverage}`;
}
