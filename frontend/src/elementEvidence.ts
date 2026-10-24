import type { Element } from "./types";

export interface EvidenceBadge {
  text: string;
  title: string;
  cls: "inferred";
}

type EvidenceMetadata = Record<string, unknown>;

/** Makes proposed structural classes visibly provisional in the element table. */
export function structuralRoleStatusBadge(roleLabel: unknown, roleStatus: unknown): EvidenceBadge[] {
  if (roleStatus !== "proposed" || typeof roleLabel !== "string" || !roleLabel.trim()) return [];
  return [{
    text: "роль — гипотеза",
    title: `Распознаватель предложил роль «${roleLabel.trim()}» по геометрии. Инженерная проверка не выполнена; не использовать её как подтверждённую классификацию.`,
    cls: "inferred",
  }];
}

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

/** Labels nominal-grid data as a hypothesis and downgrades legacy compliance claims. */
export function nominalGridHypothesisBadges(dimensions: EvidenceMetadata | null | undefined): EvidenceBadge[] {
  if (!dimensions || typeof dimensions !== "object") return [];
  const hypothesis = dimensions.nominal_grid_hypothesis;
  if (hypothesis && typeof hypothesis === "object") {
    const grid = (hypothesis as Record<string, unknown>).grid_hypothesis;
    if (grid && typeof grid === "object") {
      const value = grid as Record<string, unknown>;
      if (value.status === "grid_control_not_provided") {
        const step = typeof value.nominal_step_m === "number" ? value.nominal_step_m : null;
        return [{
          text: `оси не заданы${step == null ? "" : ` · шаг ${step} м`}`,
          title: "Известен только номинальный продольный шаг. Начало координат, поворот и поперечные оси не заданы; номера осей и отклонения не рассчитаны.",
          cls: "inferred",
        }];
      }
      const outside = value.status === "outside_nominal_grid_search_window";
      const row = typeof value.row === "string" ? value.row : "—";
      const axis = typeof value.axis === "number" ? value.axis : "—";
      const deltaU = typeof value.delta_u_mm === "number" ? value.delta_u_mm : null;
      const deltaV = typeof value.delta_v_mm === "number" ? value.delta_v_mm : null;
      return [{
        text: outside ? "вне номинальной сетки · проверить" : `ряд ${row} · ось ${axis} — гипотеза`,
        title: `Предварительное сравнение с номинальной сеткой, не подтверждение марки или допуска. Смещение: ΔU=${deltaU ?? "—"} мм, ΔV=${deltaV ?? "—"} мм. Нужны контрольные оси и ручная проверка.`,
        cls: "inferred",
      }];
    }
  }

  if (dimensions.structural_status === "confirmed_grid_column" || dimensions.tolerance_badge) {
    return [{
      text: "старое подтверждение по сетке · проверить",
      title: "Этот статус сформирован прежней версией регуляризации без контрольной сетки или согласованного допуска; он не подтверждает конструктивную роль.",
      cls: "inferred",
    }];
  }
  return [];
}

/** Converts persisted recognition diagnostics into short, uncertainty-aware review badges. */
export function elementEvidenceBadges(metadata: EvidenceMetadata | null | undefined): EvidenceBadge[] {
  if (!metadata || typeof metadata !== "object") return [];
  const badges: EvidenceBadge[] = [];
  const vertical = metadata.vertical_profile_evidence;
  const context = metadata.column_support_context;
  if (context && typeof context === "object") {
    const value = context as Record<string, unknown>;
    const endpointValue = value.end_supports && typeof value.end_supports === "object"
      ? value.end_supports as Record<string, unknown>
      : null;
    const startEndpoint = endpointValue?.start && typeof endpointValue.start === "object"
      ? endpointValue.start as Record<string, unknown>
      : null;
    const endEndpoint = endpointValue?.end && typeof endpointValue.end === "object"
      ? endpointValue.end as Record<string, unknown>
      : null;
    const startGap = typeof startEndpoint?.gap_m === "number" ? startEndpoint.gap_m : null;
    const endGap = typeof endEndpoint?.gap_m === "number" ? endEndpoint.gap_m : null;
    const distinctEndpointSupports = startEndpoint && endEndpoint
      && typeof startEndpoint.column_index === "number"
      && Number.isFinite(startEndpoint.column_index)
      && typeof endEndpoint.column_index === "number"
      && Number.isFinite(endEndpoint.column_index)
      && startEndpoint.column_index !== endEndpoint.column_index
      && startGap !== null
      && Number.isFinite(startGap)
      && endGap !== null
      && Number.isFinite(endGap);
    if (value.status === "supported_hypothesis") {
      const spacing = value.support_spacing_m;
      const supports = Array.isArray(value.supports) ? value.supports : [];
      const offsets = supports
        .map((item) => item && typeof item === "object"
          ? (item as Record<string, unknown>).axis_offset_m
          : undefined)
        .filter((item): item is number => typeof item === "number" && Number.isFinite(item));
      const offsetText = offsets.length
        ? ` Макс. смещение оси балки от найденных колонн: ${Math.max(...offsets).toFixed(2)} м.`
        : "";
      if (distinctEndpointSupports) {
        const margin = typeof value.endpoint_search_margin_m === "number"
          && Number.isFinite(value.endpoint_search_margin_m)
          ? value.endpoint_search_margin_m.toFixed(2)
          : "не задан";
        badges.push({
          text: "колонны у обоих концов · проверить опирание",
          title: `У концов оси балки найдены разные колонны: начало: ${startGap?.toFixed(2)} м, конец: ${endGap?.toFixed(2)} м до пятна колонны; предел поиска ${margin} м — геометрическая эвристика.${typeof spacing === "number" && Number.isFinite(spacing) && spacing > 0 ? ` Крайние найденные колонны разнесены на ${spacing} м.` : ""}${offsetText} Физическое опирание, консоли и крановый путь не подтверждены; возможна балка перекрытия.`,
          cls: "inferred",
        });
      } else {
        badges.push({
          text: "рядом колонны · роль балки проверить",
          title: `Найдены ${supports.length || "разнесённые"} колонны подходящей высоты.${typeof spacing === "number" && Number.isFinite(spacing) && spacing > 0 ? ` Крайние найденные колонны разнесены на ${spacing} м.` : ""}${offsetText} Опирание, консоли и крановый путь не подтверждены; возможна балка перекрытия.`,
          cls: "inferred",
        });
      }
    } else if (value.status === "insufficient_context") {
      if (endpointValue && Array.isArray(value.supports) && value.supports.length > 0) {
        const endpointGapText = (name: string, endpoint: Record<string, unknown> | null, gap: number | null) =>
          endpoint && gap !== null && Number.isFinite(gap)
            ? `${name} (${gap.toFixed(2)} м)`
            : `${name} не подтверждено`;
        const found = [
          endpointGapText("начало", startEndpoint, startGap),
          endpointGapText("конец", endEndpoint, endGap),
        ].join(", ");
        badges.push({
          text: "опоры у обоих концов не найдены",
          title: `В полосе балки найдено колонн: ${value.supports.length}; по концам оси: ${found}. Для статуса гипотезы нужны разные колонны у обоих концов. Отсутствие точек не доказывает отсутствие физической опоры; проверьте вручную.`,
          cls: "inferred",
        });
      } else {
        badges.push({text: "связь с колоннами не установлена",
          title: "Недостаточно геометрических данных о двух колоннах. Это не доказывает отсутствие опор; назначение балки требует проверки.", cls: "inferred"});
      }
    }
  }
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

/** Combines every recognition warning that applies to one row in the active candidate table. */
export function elementTableEvidenceBadges(element: Element): EvidenceBadge[] {
  const dimensions = element.dimensions || {};
  return [
    ...elementEvidenceBadges(element.metadata),
    ...structuralRoleStatusBadge(dimensions.role_label, dimensions.role_status),
    ...columnCandidateStatusBadges(dimensions),
    ...nominalGridHypothesisBadges(dimensions),
  ];
}
