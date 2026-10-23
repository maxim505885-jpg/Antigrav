import { useEffect, useState } from "react";
import { api, type ColumnTypeProposal, type ColumnTypesResponse } from "../api";
import { measuredColumnTypeSides } from "../columnTypePresentation";
import type { Element } from "../types";

interface Props {
  cloudId: string;
  elements: Element[];
  selected: Element | null;
  busy: boolean;
  onSelect: (element: Element) => void;
  onSelectGroup: (ids: string[]) => void;
}

const mm = (metres: number) => (metres * 1000).toLocaleString("ru-RU", { maximumFractionDigits: 2 });
const MORPHOLOGY: Record<string, string> = {
  solid: "сплошное", stepped: "ступенчатое", built_up: "составное", unknown: "неизвестное", other: "прочее",
};

export default function ColumnTypesPanel({ cloudId, elements, selected, busy, onSelect, onSelectGroup }: Props) {
  const [data, setData] = useState<ColumnTypesResponse | null>(null);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [marks, setMarks] = useState<Record<string, string>>({});
  const [rejectionNotes, setRejectionNotes] = useState<Record<string, string>>({});
  const [lastAction, setLastAction] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    api.columnTypes(cloudId)
      .then((result) => { if (current) setData(result); })
      .catch((reason) => { if (current) setError(String(reason.message || reason)); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [cloudId, elements, revision]);

  async function run(operation: () => Promise<{ action_id: string | null; changed: boolean }>, undo = false) {
    setSaving(true);
    setError("");
    try {
      const result = await operation();
      if (undo) setLastAction(null);
      else if (result.changed && result.action_id) setLastAction(result.action_id);
      setRevision((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  const disabled = busy || saving || loading;
  const selectedColumn = selected?.class_name === "column" ? selected : null;

  function members(ids: string[], proposal: ColumnTypeProposal) {
    return <><button type="button" disabled={disabled} onClick={() => onSelectGroup(ids)}>Выделить группу в 3D</button>
      <ul className="column-type-members">{ids.map((id) => {
      const element = elements.find((item) => item.id === id);
      const sides = measuredColumnTypeSides(element);
      const residual = sides ? {
        long_side_m: sides.long - proposal.representative_sides_m.long,
        short_side_m: sides.short - proposal.representative_sides_m.short,
      } : proposal.residuals_m[id];
      return <li key={id}>
        <button type="button" disabled={!element || disabled} onClick={() => element && onSelect(element)}
          aria-pressed={selected?.id === id} title={id}>{id}</button>
        {sides && <span>{sides.source === "point-section" ? "Сечение по точкам" : "Размеры модели"}: {mm(sides.long)} × {mm(sides.short)} мм</span>}
        {residual && <span>Δ сторон: {mm(residual.long_side_m)} / {mm(residual.short_side_m)} мм</span>}
        {!element && <span>другое облако проекта</span>}
      </li>;
    })}</ul></>;
  }

  return <section className="editor-box column-types-panel" aria-label="Типы колонн">
    <div className="panel-title"><span>Типы колонн</span><button type="button" disabled={disabled}
      onClick={() => setRevision((value) => value + 1)}>Обновить</button></div>
    <p className="hint">Марка связывает повторяющиеся сечения. Размеры и координаты каждого экземпляра сохраняются.
      Подтверждение общего типа не заменяет проверку геометрии каждой колонны.</p>
    {error && <p role="alert" className="column-type-error">{error}</p>}
    {loading && <p role="status">Загружаю группы…</p>}
    {data && <>
      <p className="hint">Предварительный порог сравнения: {mm(data.linear_tolerance_m)} мм / {data.relative_tolerance * 100}%.
        Это настройка поиска совпадений; точность обмеров ещё не подтверждена.</p>
      {data.catalog_reuse && <>
        <h4>Память проекта · совпадения с подтверждёнными типами</h4>
        <p className="hint">Сравниваем новые колонны с каталогом этого проекта, в том числе из других облаков.
          Назначение выполняется только после вашей проверки. Неполное наблюдение и несколько совпадений остаются вопросами для проверки.</p>
        <p className="hint">Без совпадения: {data.catalog_reuse.suggestions.filter((item) => !item.matches.length).length}.
          Предварительный признак неполного покрытия: менее {Math.round(data.catalog_reuse.visibility_threshold * 100)}% или покрытие неизвестно;
          это не допуск точности.</p>
        {data.catalog_reuse.catalog_issues.map((issue) => <p key={issue.type_id} role="status" className="column-type-error">
          {issue.mark}: повторное использование приостановлено — исходные участники отсутствуют, отклонены или расходятся с прототипом.
          Проверьте состав типа и измерения.</p>)}
        {data.catalog_reuse.suggestions.filter((item) => item.matches.length > 0).map((item) => {
          const element = elements.find((candidate) => candidate.id === item.element_id);
          return <details key={item.element_id} className="column-type-card">
            <summary>{item.element_id} · {item.status === "ambiguous" ? "несколько типов подходят" :
              item.status === "insufficient_evidence" ? "недостаточно наблюдений" : "есть совпадение по размерам"}</summary>
            <button type="button" disabled={disabled || !element} onClick={() => element && onSelect(element)}>Проверить колонну в 3D</button>
            <p>Покрытие: {item.evidence_coverage == null ? "неизвестно" : `${Math.round(item.evidence_coverage * 100)}%`}.</p>
            {item.reasons.includes("recognition_conflict") && <p className="column-type-error">Кандидат пересекается с ранее проверенным элементом. Сначала проверьте, не одна ли это физическая колонна.</p>}
            {item.reasons.includes("unknown_morphology") && <p className="hint">Форма сечения неизвестна; совпадения внешних размеров недостаточно для определения профиля.</p>}
            {item.matches.map((match) => <div key={match.type_id}>
              <p>{match.mark} · прототип {mm(match.representative_sides_m.long)} × {mm(match.representative_sides_m.short)} мм.
                Δ сторон: {mm(match.residuals_m.long_side_m)} / {mm(match.residuals_m.short_side_m)} мм.</p>
              <p className="hint">Источник — облака проекта: {match.source_cloud_ids.join(", ")}.</p>
              <button type="button" disabled={disabled || !element} onClick={() => run(
                () => api.assignColumnType(item.element_id, match.type_id),
              )}>Назначить {match.mark} после проверки</button>
            </div>)}
          </details>;
        })}
      </>}
      <h4>Предложения · {data.proposals.length}</h4>
      {data.proposals.map((proposal) => <details key={proposal.proposal_key} className="column-type-card">
        <summary>Предложение · {mm(proposal.representative_sides_m.long)} × {mm(proposal.representative_sides_m.short)} мм
          · {proposal.member_element_ids.length} шт.</summary>
        <p>Сечение: {MORPHOLOGY[proposal.morphology] || proposal.morphology}.
          Эвристическая оценка: {proposal.confidence.toFixed(2)}.</p>
        <p className="hint">Покрытие сечения: {proposal.evidence_summary.coverage_min == null ? "неизвестно" :
          `${Math.round(proposal.evidence_summary.coverage_min * 100)}–${Math.round((proposal.evidence_summary.coverage_max ?? proposal.evidence_summary.coverage_min) * 100)}%`}.</p>
        {members(proposal.member_element_ids, proposal)}
        <label>Марка типа <input value={marks[proposal.proposal_key] || ""} placeholder="Автоматически: К1, К2…"
          disabled={disabled} onChange={(event) => setMarks({ ...marks, [proposal.proposal_key]: event.target.value })} /></label>
        <button type="button" disabled={disabled} onClick={() => run(() => api.confirmColumnType(
          proposal.proposal_key, cloudId, marks[proposal.proposal_key] || "", data.linear_tolerance_m, data.relative_tolerance,
        ))}>Подтвердить общий тип</button>
        <label>Причина отклонения группы <input disabled={disabled}
          value={rejectionNotes[proposal.proposal_key] || ""} placeholder="Например: разные сечения"
          onChange={(event) => setRejectionNotes({ ...rejectionNotes, [proposal.proposal_key]: event.target.value })} /></label>
        <button type="button" disabled={disabled || !rejectionNotes[proposal.proposal_key]?.trim()}
          onClick={() => run(() => api.rejectColumnType(proposal.proposal_key, cloudId,
            rejectionNotes[proposal.proposal_key].trim(), data.linear_tolerance_m, data.relative_tolerance,
          ))}>Отклонить группировку</button>
        <p className="hint">Отклоняется совпадение сечений; сами колонны остаются в проекте.</p>
      </details>)}
      {!data.proposals.length && <p className="hint">Новых предложений нет.</p>}
      <h4>Подтверждённые типы проекта · {data.confirmed_types.length}</h4>
      {data.confirmed_types.map((type) => <details key={type.id} className="column-type-card confirmed">
        <summary>✓ {type.mark} · {mm(type.prototype.representative_sides_m.long)} × {mm(type.prototype.representative_sides_m.short)} мм
          · {type.member_element_ids.length} шт.</summary>
        {members(type.member_element_ids, type.prototype)}
        <button type="button" disabled={disabled || !selectedColumn} onClick={() => selectedColumn && run(
          () => api.assignColumnType(selectedColumn.id, type.id),
        )}>Назначить выбранной колонне</button>
      </details>)}
      <h4>Отклонённые группы проекта · {data.rejected_proposals.length}</h4>
      {data.rejected_proposals.map((review) => <details key={review.action_id} className="column-type-card rejected">
        <summary>Отклонено · {mm(review.proposal.representative_sides_m.long)} × {mm(review.proposal.representative_sides_m.short)} мм
          · {review.proposal.member_element_ids.length} шт.</summary>
        <p>Причина: {review.note || "не указана"}</p>
        {members(review.proposal.member_element_ids, review.proposal)}
        <button type="button" disabled={disabled} onClick={() => run(
          () => api.undoColumnTypeAction(review.action_id), true,
        )}>Отменить отклонение</button>
      </details>)}
      <div className="column-type-actions">
        <button type="button" disabled={disabled || !selectedColumn} onClick={() => selectedColumn && run(
          () => api.assignColumnType(selectedColumn.id, null),
        )}>Снять тип с выбранной колонны</button>
        <button type="button" disabled={disabled || !lastAction} onClick={() => lastAction && run(
          () => api.undoColumnTypeAction(lastAction), true,
        )}>Отменить последнее действие с типом</button>
      </div>
    </>}
  </section>;
}
