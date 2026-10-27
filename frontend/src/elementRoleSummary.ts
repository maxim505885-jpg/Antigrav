import type { Element } from "./types";

export interface ElementRoleSummary {
  role: string;
  status: string;
  columnSupport: string | null;
}

/** Turns recognition role and support evidence into a short, uncertainty-aware inspector summary. */
export function elementRoleSummary(element: Element | null | undefined): ElementRoleSummary | null {
  if (!element) return null;
  const dimensions = element.dimensions || {};
  const rawLabel = typeof dimensions.role_label === "string" ? dimensions.role_label.trim() : "";
  const rawRole = typeof dimensions.role === "string" ? dimensions.role : "";
  const roleNames: Record<string, string> = {
    crane_girder: "Подкрановая балка",
    floor_beam: "Балка перекрытия",
    roof_beam: "Балка покрытия",
    purlin: "Прогон",
    rail: "Крановый рельс",
    crane_column: "Подкрановая колонна",
    column: "Колонна",
  };
  const role = rawLabel || roleNames[rawRole]
    || (element.class_name === "column" ? "Колонна"
      : element.class_name === "beam" ? "Балка · роль не определена"
        : element.class_name);
  const status = dimensions.role_status === "proposed"
    ? "гипотеза распознавателя"
    : ["confirmed", "corrected"].includes(element.review_status)
      ? "проверено человеком"
      : rawLabel || rawRole ? "требует проверки" : "не определена";

  let columnSupport: string | null = null;
  if (element.class_name === "beam") {
    const metadata = element.metadata || {};
    const context = metadata.column_support_context;
    if (!context || typeof context !== "object") {
      columnSupport = "Связь с колоннами не проверена.";
    } else {
      const evidence = context as Record<string, unknown>;
      const supports = Array.isArray(evidence.supports) ? evidence.supports : [];
      const ends = evidence.end_supports && typeof evidence.end_supports === "object"
        ? evidence.end_supports as Record<string, unknown>
        : {};
      const start = ends.start && typeof ends.start === "object" ? ends.start as Record<string, unknown> : null;
      const end = ends.end && typeof ends.end === "object" ? ends.end as Record<string, unknown> : null;
      const distinctColumnEnds = typeof start?.column_index === "number"
        && Number.isFinite(start.column_index)
        && typeof end?.column_index === "number"
        && Number.isFinite(end.column_index)
        && start.column_index !== end.column_index;
      if (evidence.status === "supported_hypothesis" && distinctColumnEnds) {
        columnSupport = "Колонны найдены у обоих концов; физическое опирание и крановый рельс не подтверждены.";
      } else if (supports.length > 0) {
        columnSupport = `Найдены колонны рядом: ${supports.length}; пара опор у обоих концов не подтверждена.`;
      } else {
        columnSupport = "Связь с колоннами не установлена; проверьте опоры вручную.";
      }
    }
  }

  return { role, status, columnSupport };
}
