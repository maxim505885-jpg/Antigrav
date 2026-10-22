export interface EvidenceBadge {
  text: string;
  title: string;
  cls: "inferred";
}

type EvidenceMetadata = Record<string, unknown>;

/** Keeps geometric filtering outcomes visibly provisional in the review table. */
export function columnCandidateStatusBadges(dimensions: EvidenceMetadata | null | undefined): EvidenceBadge[] {
  if (!dimensions || typeof dimensions !== "object") return [];
  const badges: EvidenceBadge[] = [];
  const status = dimensions.structural_status;
  if (status === "structural_candidate" || status === "verified_structural_column") {
    badges.push({
      text: "кандидат колонны · нужна проверка",
      title: "Кандидат проходит геометрические фильтры, но облако точек не подтверждает конструктивную роль, физический ID или сечение",
      cls: "inferred",
    });
  }
  if (status === "failed_structural_heuristic" || status === "rejected_non_structural" || dimensions.rejection_reason) {
    badges.push({
      text: "кандидат не прошёл фильтр · проверить",
      title: typeof dimensions.rejection_reason === "string"
        ? dimensions.rejection_reason
        : "Геометрическая эвристика не выбрала этот объект как колонну; это не подтверждённое заключение о физической конструкции",
      cls: "inferred",
    });
  }
  if (status === "single_storey_coverage_candidate") {
    badges.push({
      text: "видна на одном уровне · проверить",
      title: "Неполное сканирование или закрытие поверхности может объяснить отсутствие точек на других уровнях; кандидат сохранён для ручной проверки",
      cls: "inferred",
    });
  }
  return badges;
}

/** Converts persisted recognition diagnostics into short, uncertainty-aware review badges. */
export function elementEvidenceBadges(metadata: EvidenceMetadata | null | undefined): EvidenceBadge[] {
  if (!metadata || typeof metadata !== "object") return [];
  const badges: EvidenceBadge[] = [];
  const vertical = metadata.vertical_profile_evidence;
  if (vertical && typeof vertical === "object"
      && (vertical as Record<string, unknown>).interpretation === "ambiguous_vertical_profile") {
    badges.push({
      text: "несколько высотных слоёв",
      title: "Профиль точек содержит несколько разнесённых по высоте слоёв. Их роль не определена; рельс и балка автоматически не разделялись.",
      cls: "inferred",
    });
  }
  const terminal = metadata.terminal_evidence;
  if (terminal && typeof terminal === "object"
      && (terminal as Record<string, unknown>).interpretation === "possible_end_plate_or_connection_detail") {
    badges.push({
      text: "проверить торцевую деталь",
      title: "У конца оси есть поперечно расширенная группа точек — возможны торцевая пластина, соединение или помеха. Физическая опора не подтверждена; измеренная ось не смещалась.",
      cls: "inferred",
    });
  }
  return badges;
}
