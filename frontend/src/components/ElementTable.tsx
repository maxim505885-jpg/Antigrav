import { useMemo, useState } from "react";
import { CLASSES, classLabel, REVIEW_LABELS, type Element } from "../types";
import { filterReferenceElements, filterReviewElements, type ReferenceFilter, type ReviewFilter } from "../reviewQueue";
import { columnCandidateStatusBadges, elementEvidenceBadges, nominalGridHypothesisBadges } from "../elementEvidence";
import { columnSectionObservationSummary } from "../columnSectionPresentation";
import { trussCompletenessBadge, trussDimensionSummary } from "../trussPresentation";

interface Props {
  elements: Element[];
  busy: boolean;
  onFeedback: (id: string, payload: Record<string, unknown>) => Promise<void>;
  onSelect: (element: Element | null) => void;
  selected: Element | null;
  referenceStates: Record<string, string>;
}

const ROLE_LABELS: Record<string, string> = {
  crane_girder: "подкрановая",
  purlin: "прогон",
  floor_beam: "перекрытие",
};

function dimensionSummary(element: Element): string {
  const dims = element.dimensions || {};
  const storeys =
    dims.storey_count > 1 ? ` · ${dims.storey_count} этажа` : dims.storey_count === 1 ? " · 1 этаж" : "";
  const oldGridOnly = element.source === "structural_grid"
    || (dims.structural_status === "confirmed_grid_column" && !["confirmed", "corrected"].includes(element.review_status));
  const gridHypothesis = dims.nominal_grid_hypothesis?.grid_hypothesis;
  if (oldGridOnly) return "гипотеза по номинальной сетке · требуется проверка";
  if (gridHypothesis) {
    if (gridHypothesis.status === "grid_control_not_provided") {
      const step = typeof gridHypothesis.nominal_step_m === "number"
        ? ` · известный шаг ${gridHypothesis.nominal_step_m} м`
        : "";
      return `оси не заданы${step} · отклонения не рассчитаны`;
    }
    const rowAxis = `ряд ${gridHypothesis.row ?? "—"} · ось ${gridHypothesis.axis ?? "—"}`;
    const residual = `ΔU=${gridHypothesis.delta_u_mm ?? "—"} мм · ΔV=${gridHypothesis.delta_v_mm ?? "—"} мм`;
    return `${rowAxis} — гипотеза · ${residual}`;
  }
  if (element.class_name === "truss" && dims.span_m) {
    return `${trussDimensionSummary(dims)}${storeys}`;
  }
  if (element.class_name === "column") {
    if (dims.mark) {
      const dev = (dims.dx_mm != null && dims.dy_mm != null) ? ` · откл: ΔX=${dims.dx_mm} мм, ΔY=${dims.dy_mm} мм` : "";
      const sec = (dims.length_m && dims.thickness_m) ? ` · ${Math.round(dims.length_m * 1000)}×${Math.round(dims.thickness_m * 1000)} мм` : "";
      const h = dims.height_m ? ` · h=${dims.height_m} м` : "";
      const rowAxis = (dims.row && dims.axis) ? ` (Ряд ${dims.row}, Ось ${dims.axis})` : "";
      return `${dims.mark}${rowAxis}${sec}${h}${dev}`;
    }
    const incomplete = columnSectionObservationSummary(dims);
    if (incomplete) return `${incomplete}${storeys}`;
    const measured = Array.isArray(dims.measured_section_m)
      ? `${Math.round(dims.measured_section_m[0] * 1000)}×${Math.round(dims.measured_section_m[1] * 1000)}`
      : null;
    if (dims.section_type_label) {
      const type = `${dims.section_type ?? ""} ${dims.section_type_label}`.trim();
      const residual = dims.section_residual_mm ? ` · откл. ${dims.section_residual_mm} мм` : "";
      return `сечение ${type}${measured ? ` (измерено ${measured})` : ""}${residual}${storeys}`;
    }
    if (measured) {
      return `сечение ${measured} мм — тип не подтверждён${storeys}`;
    }
  }
  if (element.class_name === "stair" && dims.rise_m) {
    const slope = dims.slope_deg != null ? ` · ${dims.slope_deg}°` : "";
    const steps = dims.steps_est ? ` · ~${dims.steps_est} ступ.` : "";
    return `марш ${dims.run_m ?? "—"} × ${dims.width_m ?? "—"} м · подъём ${dims.rise_m} м${slope}${steps}`;
  }
  if (element.class_name === "opening") {
    const kind = dims.opening_kind === "window" ? "окно" : "дверь";
    const sill = dims.opening_kind === "window" && dims.sill_m != null ? ` · подоконник ${dims.sill_m} м` : "";
    return `${kind} ${dims.width_m ?? "—"} × ${dims.height_m ?? "—"} м${sill}`;
  }
  if (dims.length_m && dims.role_label) {
    return `${dims.length_m} м · ${dims.role_label}${dims.orientation ? ` (${dims.orientation === "vertical" ? "верт." : "гориз."})` : ""}`;
  }
  if (dims.length_m) {
    return `${dims.length_m} × ${dims.thickness_m} × ${dims.height_m} м${storeys}`;
  }
  if (dims.area_m2) {
    const level = dims.level_index != null ? ` · уровень ${dims.level_index + 1}` : "";
    return `${dims.area_m2} м² в плане${level}`;
  }
  return "—";
}

function extraBadges(element: Element) {
  const dims = element.dimensions || {};
  const badges: { text: string; title: string; cls: string }[] = [];
  badges.push(...elementEvidenceBadges(element.metadata));
  badges.push(...columnCandidateStatusBadges(dims));
  badges.push(...nominalGridHypothesisBadges(dims));
  if (Array.isArray(dims.review_conflict_with) && dims.review_conflict_with.length > 0) {
    badges.push({
      text: "проверить повторный кандидат",
      title: `Новый кандидат пересекается с элементом, который уже проверен: ${dims.review_conflict_with.join(", ")}`,
      cls: "inferred",
    });
  }
  if (dims.merged_from > 1) {
    badges.push({
      text: `сращено из ${dims.merged_from}`,
      title: `Несколько фрагментов объединены в одну конструкцию (максимальный разрыв ${dims.merged_gap_m ?? "—"} м)`,
      cls: "measured",
    });
  }
  if (dims.demoted_from) {
    badges.push({
      text: `кандидат понижен: ${classLabel(dims.demoted_from)}`,
      title: "Кандидат не прошёл текущую эвристику покрытия этажей; частичное сканирование или закрытие поверхности требуют ручной проверки",
      cls: "inferred",
    });
  }
  if (["measured_2_axes", "measured_3_sides", "measured_4_sides"].includes(dims.section_status)) {
    badges.push({
      text: dims.section_status === "measured_2_axes" ? "измерено по 2 осям" : "измерены видимые грани",
      title: "Обе размерности сечения опираются на точки облака; повторяющийся тип остаётся предложением до проверки",
      cls: "measured",
    });
  }
  if (dims.section_status === "partial_one_axis") {
    badges.push({
      text: "одна размерность сечения неизвестна",
      title: "Точки подтверждают только одну размерность; вторая не достраивается автоматически",
      cls: "inferred",
    });
  }
  if (dims.section_status === "coarse_grid_only") {
    badges.push({
      text: "размеры по грубой сетке не подтверждены",
      title: "10 см сетка помогает найти видимые грани, но не подтверждает размеры сечения",
      cls: "inferred",
    });
  }
  if (["completed_from_2_sides", "completed_square_1_side"].includes(dims.section_status)) {
    badges.push({
      text: "старое предположение сечения требует проверки",
      title: "Этот элемент создан прежней версией авто-достройки; проверьте его размеры по точкам",
      cls: "inferred",
    });
  }
  if (dims.embedded_in_wall) {
    badges.push({
      text: "в стене",
      title: "След колонны внутри стены (угол, пилон или колонна в плоскости стены) — проверьте в редакторе",
      cls: "inferred",
    });
  }
  if (dims.role && ROLE_LABELS[dims.role]) {
    badges.push({
      text: ROLE_LABELS[dims.role],
      title: dims.role_note || `Роль элемента: ${dims.role}. Класс — геометрическая гипотеза, проверьте в редакторе.`,
      cls: "measured",
    });
  }
  if (dims.column_type_label) {
    badges.push({
      text: dims.column_type_label,
      title: `Тип сечения по профилю площади: основание ${dims.base_area_m2 ?? "—"} м², верх ${dims.top_area_m2 ?? "—"} м², заполнение ${dims.section_fill ?? "—"}`,
      cls: "measured",
    });
  }
  if (element.class_name === "stair") {
    badges.push({
      text: "марш — гипотеза",
      title: "Наклонная плоскость между двумя уровнями. Пандус или наклонный участок кровли выглядит так же; ступени и ограждения не распознаны.",
      cls: "inferred",
    });
  }
  if (element.class_name === "opening") {
    badges.push({
      text: dims.opening_kind === "window" ? "окно — гипотеза" : "проём — гипотеза",
      title: "Разрыв в просканированной стене с перемычкой сверху. Дыра в скане выглядит так же — проверьте в натуре.",
      cls: "inferred",
    });
  }
  if (dims.below_resolution) {
    badges.push({
      text: "тоньше шага сетки",
      title: "Наименьшая сторона меньше двух ячеек сетки: размер не разрешается, элемент оставлен как кандидат.",
      cls: "inferred",
    });
  }
  if (element.class_name === "truss") {
    const completeness = trussCompletenessBadge(dims);
    if (completeness) {
      badges.push({ ...completeness, cls: "inferred" });
    }
    badges.push({
      text: `диагр. ${dims.diagonals ?? 0}`,
      title: `Ферма: пояса измерены, стоек (панелей): ${dims.panels ?? "—"}, раскосов: ${dims.diagonals ?? 0}. Нижний пояс может сливаться с уровнем кровли.`,
      cls: "measured",
    });
  }
  return badges;
}

export default function ElementTable({ elements, busy, onFeedback, onSelect, selected, referenceStates }: Props) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("pending");
  const [referenceFilter, setReferenceFilter] = useState<ReferenceFilter>("all");
  const [classFilter, setClassFilter] = useState<string>("all");

  const exportCsv = () => {
    const header = [
      "ID",
      "Марка_СПДС",
      "Класс",
      "Ряд",
      "Ось_Пролет",
      "Тип_сечения",
      "Длина_м",
      "Толщина_м",
      "Высота_м",
      "Отклонение_dU_мм",
      "Отклонение_dV_мм",
      "Суммарное_dR_мм",
      "Гипотеза_номинальной_сетки",
      "Описание_конструкции",
      "Статус_проверки",
    ];
    const rows = visibleElements.map((el) => {
      const d = el.dimensions || {};
      const oldGridOnly = el.source === "structural_grid"
        || (d.structural_status === "confirmed_grid_column" && !["confirmed", "corrected"].includes(el.review_status));
      const hypothesis = d.nominal_grid_hypothesis?.grid_hypothesis;
      const gridSummary = hypothesis
        ? hypothesis.status === "grid_control_not_provided"
          ? `сетка осей не задана; известный шаг ${hypothesis.nominal_step_m ?? "—"} м; отклонения не рассчитаны`
          : `не подтверждено: ряд ${hypothesis.row ?? "—"}, ось ${hypothesis.axis ?? "—"}, ΔU=${hypothesis.delta_u_mm ?? "—"} мм, ΔV=${hypothesis.delta_v_mm ?? "—"} мм`
        : oldGridOnly ? "старое предположение · проверить" : "—";
      return [
        el.id,
        oldGridOnly ? "—" : d.mark || "—",
        classLabel(el.class_name),
        oldGridOnly ? "—" : d.row || "—",
        oldGridOnly ? "—" : d.axis ?? "—",
        oldGridOnly ? "—" : d.type || d.section_type || "—",
        oldGridOnly ? "—" : d.length_m ?? "—",
        oldGridOnly ? "—" : d.thickness_m ?? "—",
        oldGridOnly ? "—" : d.height_m ?? "—",
        oldGridOnly ? "—" : d.dx_mm ?? "—",
        oldGridOnly ? "—" : d.dy_mm ?? "—",
        oldGridOnly ? "—" : d.dr_mm ?? "—",
        gridSummary,
        oldGridOnly ? "Геометрическая гипотеза; размеры и роль не подтверждены" : d.description || "—",
        el.review_status || "unreviewed",
      ].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(";");
    });
    const csvContent = "\uFEFF" + [header.join(";"), ...rows].join("\r\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `specifikaciya_elementov_SPDS_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const classCounts = useMemo(() => {
    const res: Record<string, number> = { all: elements.length };
    for (const el of elements) {
      res[el.class_name] = (res[el.class_name] || 0) + 1;
    }
    return res;
  }, [elements]);
  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    elements.forEach((element) => {
      map[element.class_name] = (map[element.class_name] || 0) + 1;
    });
    return map;
  }, [elements]);
  const reviewCounts = useMemo(() => ({
    pending: elements.filter((element) => element.review_status === "unreviewed").length,
    conflicts: filterReviewElements(elements, "conflicts").length,
    checked: filterReviewElements(elements, "checked").length,
    rejected: filterReviewElements(elements, "rejected").length,
    all: elements.length,
  }), [elements]);
  const visibleElements = useMemo(() => {
    let list = filterReferenceElements(filterReviewElements(elements, reviewFilter), referenceFilter, referenceStates);
    if (classFilter === "columns_beams") {
      list = list.filter((el) => el.class_name === "column" || el.class_name === "beam");
    } else if (classFilter === "trusses_braces") {
      list = list.filter((el) => el.class_name === "truss" || el.class_name === "brace");
    } else if (classFilter !== "all") {
      list = list.filter((el) => el.class_name === classFilter);
    }
    return list;
  }, [elements, reviewFilter, referenceFilter, referenceStates, classFilter]);
  const reviewFilters: { id: ReviewFilter; label: string }[] = [
    { id: "pending", label: "К проверке" },
    { id: "conflicts", label: "Конфликты" },
    { id: "checked", label: "Проверенные" },
    { id: "rejected", label: "Отклонённые" },
    { id: "all", label: "Все" },
  ];
  const referenceFilters: { id: ReferenceFilter; label: string }[] = [
    { id: "all", label: "Все элементы" }, { id: "needs_reference", label: "Без эталона" },
    { id: "labeled", label: "Размечены" }, { id: "unknown", label: "Неизвестно" }, { id: "excluded", label: "Исключены" },
  ];
  const referenceCounts = useMemo(() => Object.fromEntries(referenceFilters.map(({ id }) => [
    id, id === "all" ? elements.length : filterReferenceElements(elements, id, referenceStates).length,
  ])) as Record<ReferenceFilter, number>, [elements, referenceStates]);

  if (!elements.length) {
    return (
      <div className="empty-note">
        Распознанных элементов пока нет. Запустите геометрическое распознавание: оно
        ищет стены, колонны, балки, подкрановые балки, фермы, связи, лестничные марши
        и проёмы в стенах там, где хватает точечного evidence. Все результаты поступают
        как кандидаты для ручной проверки; невидимые детали не достраиваются.
      </div>
    );
  }

  return (
    <div className="element-list">
      <div className="segmented review-filters" aria-label="Очередь ручной проверки">
        {reviewFilters.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            className={reviewFilter === id ? "active" : ""}
            aria-pressed={reviewFilter === id}
            onClick={() => setReviewFilter(id)}
          >
            {label} <span className="review-count">{reviewCounts[id]}</span>
          </button>
        ))}
      </div>
      <div className="segmented review-filters reference-filters" aria-label="Фильтр независимой эталонной разметки колонн">
        {referenceFilters.map(({ id, label }) => <button key={id} type="button"
          className={referenceFilter === id ? "active" : ""} aria-pressed={referenceFilter === id}
          onClick={() => setReferenceFilter(id)}>
          {label} <span className="review-count">{referenceCounts[id]}</span>
        </button>)}
      </div>
      <div className="segmented class-filters" style={{ margin: "6px 0", display: "flex", flexWrap: "wrap", gap: "4px" }} aria-label="Фильтр по типу конструкций">
        {[
          { id: "all", label: "Все", count: elements.length },
          { id: "columns_beams", label: "🏢+🏗️ Колонны и балки", count: (classCounts["column"] || 0) + (classCounts["beam"] || 0) },
          { id: "wall", label: "🧱 Только стены", count: classCounts["wall"] || 0 },
          { id: "column", label: "🏢 Колонны", count: classCounts["column"] || 0 },
          { id: "beam", label: "🏗️ Балки", count: classCounts["beam"] || 0 },
          { id: "trusses_braces", label: "📐+⚡ Фермы и связи", count: (classCounts["truss"] || 0) + (classCounts["brace"] || 0) },
          { id: "brace", label: "⚡ Связи", count: classCounts["brace"] || 0 },
          { id: "truss", label: "📐 Фермы", count: classCounts["truss"] || 0 },
          { id: "slab", label: "Плиты", count: classCounts["slab"] || 0 },
          { id: "stair", label: "🪜 Лестницы", count: classCounts["stair"] || 0 },
          { id: "opening", label: "🚪 Проёмы", count: classCounts["opening"] || 0 },
        ].filter((f) => f.count > 0).map(({ id, label, count }) => (
          <button
            key={id}
            type="button"
            className={classFilter === id ? "active" : ""}
            style={classFilter === id ? { background: "#2563eb", color: "#fff", fontWeight: 600 } : {}}
            onClick={() => setClassFilter(id)}
          >
            {label} <span className="review-count">{count}</span>
          </button>
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "8px 0" }}>
        <button
          type="button"
          className="hud-chip"
          style={{
            cursor: "pointer",
            background: "#059669",
            color: "#fff",
            border: "1px solid #059669",
            borderRadius: "4px",
            padding: "4px 12px",
            fontWeight: 600,
            fontSize: "13px",
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
          }}
          onClick={exportCsv}
          title="Выгрузить спецификацию в формате CSV для Microsoft Excel / LibreOffice"
        >
          📊 Экспорт спецификации в Excel (CSV)
        </button>
        <span style={{ fontSize: "12px", color: "#64748b" }}>
          Отображается: <b>{visibleElements.length}</b> из <b>{elements.length}</b> элементов
        </span>
      </div>
      <div className="counts">
        {Object.entries(counts).map(([name, value]) => (
          <span key={name} className="count-chip">
            {classLabel(name)} <b>{value}</b>
          </span>
        ))}
      </div>
      {visibleElements.length === 0 ? (
        <div className="empty-note">В этой очереди пока нет элементов.</div>
      ) : <table className="element-table">
        <thead>
          <tr>
            <th>класс</th>
            <th>уверенность</th>
            <th>размеры</th>
            <th>признаки</th>
            <th>проверка</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {visibleElements.map((element) => {
            const draft = drafts[element.id] ?? element.class_name;
            return (
              <tr
                key={element.id}
                className={selected?.id === element.id ? "selected" : ""}
                onClick={() => onSelect(element)}
              >
                <td>
                  <select
                    value={draft}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => setDrafts({ ...drafts, [element.id]: event.target.value })}
                  >
                    {CLASSES.map((name) => (
                      <option key={name} value={name}>
                        {classLabel(name)}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <div className="conf">
                    <div className="conf-bar" style={{ width: `${Math.round(element.confidence * 100)}%` }} />
                    <span>{(element.confidence * 100).toFixed(0)}%</span>
                  </div>
                </td>
                <td>{dimensionSummary(element)}</td>
                <td className="flags">
                  {element.class_name === "column" && <span className={`badge ${referenceStates[element.id] === "labeled" ? "measured" : "inferred"}`}>
                    {referenceStates[element.id] === "labeled" ? "эталон размечен"
                      : referenceStates[element.id] === "unknown" ? "эталон: неизвестно"
                      : referenceStates[element.id] === "excluded" ? "эталон: исключён" : "нет эталона"}
                  </span>}
                  {element.measured && <span className="badge measured">измерено</span>}
                  {element.inferred && <span className="badge inferred">восстановлено</span>}
                  {extraBadges(element).map((badge) => (
                    <span key={badge.text} className={`badge ${badge.cls}`} title={badge.title}>
                      {badge.text}
                    </span>
                  ))}
                </td>
                <td>
                  <span className={`status ${element.review_status}`}>
                    {REVIEW_LABELS[element.review_status] || element.review_status}
                  </span>
                </td>
                <td className="actions" onClick={(event) => event.stopPropagation()}>
                  {draft !== element.class_name && (
                    <button
                      disabled={busy}
                      onClick={() =>
                        onFeedback(element.id, {
                          action: "reclassify",
                          class_name: draft,
                          note: "класс исправлен инженером",
                        })
                      }
                    >
                      Применить класс
                    </button>
                  )}
                  {element.review_status !== "confirmed" && (
                    <button
                      disabled={busy}
                      className="primary"
                      onClick={() => onFeedback(element.id, { action: "confirm", note: "подтверждено инженером" })}
                    >
                      Подтвердить
                    </button>
                  )}
                  {element.review_status !== "rejected" && (
                    <button
                      disabled={busy}
                      className="danger"
                      onClick={() => onFeedback(element.id, { action: "reject", note: "отклонено инженером" })}
                    >
                      Отклонить
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>}
      <p className="hint">
        Подтверждённые и исправленные элементы становятся размеченными примерами вместе с
        исходными точками. Уверенность — эвристическая оценка, а не откалиброванная вероятность.
      </p>
    </div>
  );
}
