import { useMemo, useState } from "react";
import { CLASSES, classLabel, REVIEW_LABELS, type Element } from "../types";
import { filterReferenceElements, filterReviewElements, type ReferenceFilter, type ReviewFilter } from "../reviewQueue";

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
  if (element.class_name === "truss" && dims.span_m) {
    return `пролёт ${dims.span_m} × выс ${dims.height_m} м · панелей: ${dims.panels ?? "—"}${storeys}`;
  }
  if (element.class_name === "column") {
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
  if (dims.structural_status === "verified_structural_column") {
    badges.push({
      text: "несущая колонна каркаса (проверено агентом)",
      title: "Элемент верифицирован конструктивным агентом: проходит по габаритам сечения, непрерывной высоте от пола и привязке к сетке цеха",
      cls: "measured",
    });
  }
  if (dims.structural_status === "rejected_non_structural" || dims.rejection_reason) {
    badges.push({
      text: "не конструктив (отсеяно агентом)",
      title: dims.rejection_reason || "Отсеяно конструктивным агентом: труба, венткороб, стойка оборудования или подвес",
      cls: "inferred",
    });
  }
  if (dims.demoted_from) {
    badges.push({
      text: `была ${classLabel(dims.demoted_from)}`,
      title: "Класс понижен: объект виден только на одном этаже многоэтажного здания — это не несущая колонна",
      cls: "inferred",
    });
  }
  if (dims.section_status === "completed_from_2_sides" || dims.section_status === "completed_square_1_side") {
    badges.push({
      text:
        dims.section_status === "completed_from_2_sides"
          ? "достроено по 2 сторонам"
          : "достроено по 1 стороне",
      title:
        dims.section_status === "completed_from_2_sides"
          ? "Скан видел две стороны колонны — прямоугольник достроен по ним"
          : "Скан видел одну сторону — вторую сторону приняли равной первой (квадрат) и уточнили по типоразмеру",
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
  if (element.class_name === "truss") {
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
  const visibleElements = useMemo(
    () => filterReferenceElements(filterReviewElements(elements, reviewFilter), referenceFilter, referenceStates),
    [elements, reviewFilter, referenceFilter, referenceStates],
  );
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
        Распознанных элементов пока нет. Запустите распознавание — оно выделит
        геометрический базис: стены, колонны, контуры плит. Балки, фермы, лестницы и
        инженерные сети требуют ML-этапа.
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
