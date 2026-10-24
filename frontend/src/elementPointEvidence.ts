export interface SourcePointEvidence {
  status: "consistent" | "mismatch" | "unverifiable";
  row_ids_count: number;
  row_ids_checked_count?: number;
  row_ids_valid_count: number;
  row_ids_within_bbox_count: number;
  row_ids_within_geometry_count?: number;
  geometry_check?: "bbox" | "member_axis" | "unavailable";
  row_ids_sampled: boolean;
  snapshot_matches?: boolean;
  reason?: string;
}

export function elementPointEvidenceMessage(
  pointCount: number,
  sectionCounts: readonly number[],
  evidence?: SourcePointEvidence,
): string {
  const sections = sectionCounts.join(" / ");
  if (evidence?.status === "mismatch") {
    if (evidence.snapshot_matches === false) {
      return "Исходный файл облака изменился после распознавания. Индексы больше не относятся к текущему набору точек; запустить распознавание повторно и проверить кандидата.";
    }
    const checked = evidence.row_ids_checked_count ?? evidence.row_ids_count;
    const axisCheck = evidence.geometry_check === "member_axis";
    const matched = evidence.row_ids_within_geometry_count ?? evidence.row_ids_within_bbox_count;
    const label = axisCheck ? "source ID у измеренной оси" : "source ID в bbox";
    const geometry = axisCheck ? "измеренной осью" : "bbox";
    return `Точек в области элемента: ${pointCount.toLocaleString("ru-RU")} · ${label}: ${matched}/${checked}. Индексы не совпадают с текущим облаком или ${geometry}; кандидат требует повторной проверки.`;
  }
  if (evidence?.status === "unverifiable") {
    const reason = evidence.reason === "missing_source_cloud_snapshot"
      ? "SHA-снимок облака не сохранён; повторите распознавание для безопасной привязки кандидата"
      : evidence.reason === "missing_source_point_ids"
        ? "индексы исходных строк не сохранены"
        : "привязка исходных индексов не подтверждена";
    if (pointCount === 0) {
      return `В bbox точки не найдены; ${reason}. Кандидат остаётся непроверенной гипотезой.`;
    }
    return `Исходные точки: ${pointCount.toLocaleString("ru-RU")} · сечения X/Y/Z: ${sections} · ${reason}. Кандидат остаётся непроверенной гипотезой.`;
  }
  if (pointCount === 0) {
    return "В bbox выбранного элемента точки не найдены. Геометрия не подтверждена исходными точками.";
  }
  if (evidence?.geometry_check === "member_axis") {
    const checked = evidence.row_ids_checked_count ?? evidence.row_ids_count;
    const matched = evidence.row_ids_within_geometry_count ?? 0;
    return `Исходные точки рядом с осью: ${pointCount.toLocaleString("ru-RU")} · source ID у измеренной оси: ${matched}/${checked} · сечения X/Y/Z: ${sections}`;
  }
  return `Исходные точки: ${pointCount.toLocaleString("ru-RU")} · сечения X/Y/Z: ${sections}`;
}
