type AnnotationCandidate = {
  class_name: string;
  source: string;
  confidence: number;
  confidence_kind: string;
  geometry?: { kind?: string; axis_status?: string; p0?: number[]; p1?: number[] };
  bbox: { min: number[]; max: number[] };
  dimensions: Record<string, unknown>;
};

const ROLE_LABELS: Record<string, string> = {
  column: "колонна",
  crane_column: "подкрановая колонна",
  beam: "балка",
  crane_girder: "подкрановая балка",
  roof_beam: "балка покрытия",
  rail: "крановый рельс",
  truss_member: "элемент фермы",
  brace: "связь",
  pipe: "трубопровод",
  floor_beam: "балка перекрытия",
  purlin: "прогон",
  truss_top_chord: "верхний пояс фермы",
  truss_bottom_chord: "нижний пояс фермы",
  truss_post: "стойка фермы",
  truss_web: "раскос фермы",
  duct: "воздуховод",
  cable_tray: "кабельный лоток",
  other: "другое",
  unknown: "неизвестно",
};

const SOURCE_LABELS: Record<string, string> = {
  geometric: "геометрия",
  structural_grid: "номинальная сетка",
  engineer: "инженер",
};

const CONFIDENCE_LABELS: Record<string, string> = {
  heuristic: "эвристический балл, не вероятность",
  model: "модель",
  geometric: "геометрический балл, не вероятность",
  measured_grid_consensus: "согласование с номинальной сеткой, не контрольная съёмка",
  ground_truth_survey: "контрольная съёмка",
  not_calibrated: "не калибрована",
  "heuristic (not calibrated probabilities)": "эвристический балл, не вероятность",
};

function bboxLabel(element: AnnotationCandidate): string {
  if (element.geometry?.kind === "member" && element.geometry.axis_status === "window_derived_candidate") {
    const { p0, p1 } = element.geometry;
    if (Array.isArray(p0) && Array.isArray(p1) && p0.length >= 3 && p1.length >= 3) {
      const delta = [0, 1, 2].map((axis) => p1[axis] - p0[axis]);
      if (delta.every(Number.isFinite)) {
        const length = Math.round(Math.hypot(...delta) * 1000);
        return `ось · наблюдаемая длина ${length} мм · сечение не измерено`;
      }
    }
    return "ось-кандидат · сечение не измерено";
  }
  const { min, max } = element.bbox || {};
  if (!Array.isArray(min) || !Array.isArray(max) || min.length < 3 || max.length < 3) {
    return "габарит не рассчитан";
  }
  const spans = [0, 1, 2].map((axis) => {
    const low = min[axis];
    const high = max[axis];
    if (typeof low !== "number" || typeof high !== "number" || !Number.isFinite(low) || !Number.isFinite(high) || high < low) {
      return null;
    }
    return Math.round((high - low) * 1000);
  });
  return spans.some((span) => span === null)
    ? "габарит не рассчитан"
    : `${spans.join(" × ")} мм`;
}

export function annotationCandidateEvidence(element: AnnotationCandidate, localizeClass: (className: string) => string = (className) => className) {
  const dimensions = element.dimensions || {};
  const role = typeof dimensions.role === "string" ? dimensions.role : "";
  const roleStatus = typeof dimensions.role_status === "string" ? dimensions.role_status : "";
  const confidence = element.confidence;
  const confidenceKind = element.confidence_kind;
  const confidenceLabel = confidenceKind === "not_calibrated"
    ? "не калибрована"
    : Number.isFinite(confidence) && confidence >= 0 && confidence <= 1 && confidenceKind
    ? `${Math.round(confidence * 100)}% · ${CONFIDENCE_LABELS[confidenceKind] || confidenceKind}`
    : "не задана или не калибрована";

  return {
    classLabel: localizeClass(element.class_name),
    roleLabel: role ? ROLE_LABELS[role] || role : "роль не предложена",
    roleStatus: roleStatus === "proposed" ? "гипотеза" : roleStatus === "confirmed" ? "подтверждена" : roleStatus || "статус не задан",
    sourceLabel: SOURCE_LABELS[element.source] || element.source || "не указан",
    bboxLabel: bboxLabel(element),
    confidenceLabel,
  };
}
