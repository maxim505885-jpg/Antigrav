export interface EvidenceBadge {
  text: string;
  title: string;
  cls: "inferred";
}

type EvidenceMetadata = Record<string, unknown>;

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
