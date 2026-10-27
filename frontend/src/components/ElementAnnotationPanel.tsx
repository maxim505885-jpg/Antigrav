import { useEffect, useMemo, useState } from "react";
import { api, type ElementAnnotation, type ElementAnnotationDataset, type ElementAnnotationDraft, type RecognitionEvaluationReport, type SourceEvidenceAudit } from "../api";
import { annotationCandidateEvidence } from "../annotationCandidateEvidence";
import { elementPointEvidenceMessage, type SourcePointEvidence } from "../elementPointEvidence";
import { annotationReviewerFor, rememberAnnotationReviewer } from "../annotationReviewer";
import { buildRecognitionEvaluationRequest, emptyPhysicalReferenceDraft, roleMatchesClass, roleOptionsForClass, type PhysicalReferenceDraft, type RecognitionEvaluationMetadataDraft } from "../recognitionReferences";
import { classLabel, type Element } from "../types";

interface Props {
  cloudId: string;
  element: Element;
  busy: boolean;
  onAnnotationSaved: (annotation: ElementAnnotation) => void;
}

const CLASS_OPTIONS = [
  ["wall", "Стена"], ["column", "Колонна"], ["beam", "Балка"], ["girder", "Ригель / балка"],
  ["slab", "Плита"], ["roof", "Покрытие"], ["truss", "Ферма"], ["brace", "Связь"],
  ["stair", "Лестница"], ["opening", "Проём"], ["pipe", "Трубопровод"], ["duct", "Воздуховод"],
  ["equipment", "Оборудование"], ["other", "Другое"],
] as const;
const ROLE_OPTIONS = [
  ["column", "Колонна"], ["crane_column", "Подкрановая колонна"], ["beam", "Балка"],
  ["crane_girder", "Подкрановая балка"], ["roof_beam", "Балка покрытия"], ["rail", "Крановый рельс"],
  ["truss_member", "Элемент фермы"], ["brace", "Связь"], ["pipe", "Трубопровод"],
  ["floor_beam", "Балка перекрытия"], ["purlin", "Прогон"], ["truss_top_chord", "Верхний пояс фермы"],
  ["truss_bottom_chord", "Нижний пояс фермы"], ["truss_post", "Стойка фермы"], ["truss_web", "Раскос фермы"],
  ["duct", "Воздуховод"], ["cable_tray", "Кабельный лоток"], ["other", "Другое"], ["unknown", "Неизвестно"],
] as const;
const metric = (value: number | null) => value === null ? "пока нет данных" : `${(value * 100).toFixed(1)}%`;

type DraftFields = Omit<ElementAnnotationDraft, "source_snapshot_sha256">;

function initial(annotation: ElementAnnotation | undefined, cloudId: string): DraftFields {
  return {
    annotator: annotationReviewerFor(cloudId, annotation?.annotator),
    state: annotation?.state === "pending" ? "labeled" : annotation?.state || "labeled",
    physical_instance_id: annotation?.physical_instance_id || "",
    class_label: annotation?.class_label || "",
    role_label: annotation?.role_label || "",
    type_label: annotation?.type_label || "",
    reason: annotation?.reason || "",
    note: annotation?.note || "",
  };
}

export default function ElementAnnotationPanel({ cloudId, element, busy, onAnnotationSaved }: Props) {
  const [dataset, setDataset] = useState<ElementAnnotationDataset | null>(null);
  const [draft, setDraft] = useState<DraftFields>(() => initial(undefined, cloudId));
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [referenceMetadata, setReferenceMetadata] = useState<RecognitionEvaluationMetadataDraft>({
    reference_set_id: `${cloudId}-field-reference`, reference_kind: "field_measurement", annotator: "",
  });
  const [referenceDrafts, setReferenceDrafts] = useState<PhysicalReferenceDraft[]>([]);
  const [evaluation, setEvaluation] = useState<RecognitionEvaluationReport | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [pointQuery, setPointQuery] = useState<{ count: number; evidence: SourcePointEvidence } | null>(null);
  const [pointQueryLoading, setPointQueryLoading] = useState(false);
  const [pointQueryError, setPointQueryError] = useState(false);
  const [sourceAudit, setSourceAudit] = useState<SourceEvidenceAudit | null>(null);
  const [sourceAuditLoading, setSourceAuditLoading] = useState(false);
  const [sourceAuditError, setSourceAuditError] = useState("");
  const current = dataset?.annotations.find((item) => item.element_id === element.id);
  const candidateEvidence = annotationCandidateEvidence(element, classLabel);
  const history = useMemo(() => dataset?.history.filter((item) => item.element_id === element.id) || [], [dataset, element.id]);

  useEffect(() => {
    let active = true;
    setPointQuery(null);
    setPointQueryError(false);
    setPointQueryLoading(true);
    api.elementPoints(element.id)
      .then((result) => {
        if (active) setPointQuery({ count: result.count, evidence: result.source_point_evidence });
      })
      .catch(() => {
        if (active) setPointQueryError(true);
      })
      .finally(() => { if (active) setPointQueryLoading(false); });
    return () => { active = false; };
  }, [element.id, element.updated_at]);

  useEffect(() => {
    let active = true;
    setDataset(null); setLoading(true); setError(""); setEvaluation(null); setReferenceFile(null); setReferenceDrafts([]);
    setSourceAudit(null); setSourceAuditError("");
    setReferenceMetadata({ reference_set_id: `${cloudId}-field-reference`, reference_kind: "field_measurement", annotator: "" });
    Promise.all([api.elementAnnotations(cloudId), api.elementAnnotationHistory(cloudId)])
      .then(([value, archive]) => {
        if (active) setDataset({ ...value, history: archive.history.filter((item) => item.source_snapshot_sha256 === value.source_snapshot_sha256) });
      })
      .catch((reason) => { if (active) setError(String(reason?.message || reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [cloudId]);

  useEffect(() => {
    if (!dataset) return;
    setDraft(initial(current, cloudId)); setNotice(""); setError("");
  // current is derived from the loaded immutable dataset and selected element.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset?.source_snapshot_sha256, element.id]);

  async function save() {
    if (!dataset) return;
    setSaving(true); setError(""); setNotice("");
    const labeled = draft.state === "labeled";
    const payload: ElementAnnotationDraft = {
      source_snapshot_sha256: dataset.source_snapshot_sha256,
      ...draft,
      physical_instance_id: labeled ? (draft.physical_instance_id || "").trim() || null : null,
      class_label: labeled ? draft.class_label || null : null,
      role_label: labeled ? draft.role_label || null : null,
      type_label: labeled ? (draft.type_label || "").trim() || null : null,
    };
    try {
      const saved = await api.saveElementAnnotation(cloudId, element.id, payload);
      onAnnotationSaved(saved);
      setDataset(await api.elementAnnotations(cloudId));
      rememberAnnotationReviewer(cloudId, saved.annotator);
      setDraft(initial(saved, cloudId));
      setNotice(`Сохранена независимая разметка, ревизия ${saved.revision}. Исходный кандидат не изменён.`);
    } catch (reason) {
      setError(String(reason instanceof Error ? reason.message : reason));
    } finally { setSaving(false); }
  }

  async function auditSourceEvidence() {
    setSourceAuditLoading(true); setSourceAuditError("");
    try {
      setSourceAudit(await api.sourceEvidenceAudit(cloudId));
    } catch (reason) {
      setSourceAuditError(String(reason instanceof Error ? reason.message : reason));
    } finally { setSourceAuditLoading(false); }
  }

  async function exportReferences() {
    setError("");
    try {
      const reference = await api.exportElementAnnotations(cloudId);
      const url = URL.createObjectURL(new Blob([JSON.stringify(reference, null, 2)], { type: "application/json" }));
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `${dataset?.dataset_id.replaceAll(":", "-") || "element-reference"}.json`;
      anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (reason) { setError(String(reason instanceof Error ? reason.message : reason)); }
  }

  function downloadEvaluationTemplate() {
    if (!dataset) return;
    const template = {
      source_snapshot_sha256: dataset.source_snapshot_sha256,
      reference_set_id: `${cloudId}-manual-reference`,
      reference_origin: "independent_manual",
      reference_kind: "field_measurement",
      annotator: "",
      iou_threshold: 0.5,
      reference_elements: [],
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(template, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${cloudId.replace(/[^a-z0-9_-]/gi, "_")}-recognition-reference.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  async function evaluateIndependentReferences() {
    if (!dataset || (!referenceFile && referenceDrafts.length === 0)) return;
    setEvaluating(true); setError(""); setEvaluation(null);
    try {
      if (referenceDrafts.length > 0) {
        const request = buildRecognitionEvaluationRequest(dataset, referenceMetadata, referenceDrafts);
        setEvaluation(await api.evaluateRecognition(cloudId, request));
        return;
      }
      const selectedFile = referenceFile;
      if (!selectedFile) throw new Error("Добавь физические эталоны или выбери JSON-файл.");
      const payload = JSON.parse(await selectedFile.text());
      if (payload.source_snapshot_sha256 !== dataset.source_snapshot_sha256) {
        throw new Error("Эталон создан для другого снимка кандидатов. Скачай новый шаблон и перенеси физические эталоны.");
      }
      if (!Array.isArray(payload.reference_elements) || payload.reference_elements.length === 0) {
        throw new Error("Добавь в JSON независимые физические эталоны с bbox, включая элементы, которых нет в списке кандидатов.");
      }
      setEvaluation(await api.evaluateRecognition(cloudId, payload));
    } catch (reason) {
      setError(String(reason instanceof Error ? reason.message : reason));
    } finally { setEvaluating(false); }
  }

  return <section className="editor-box column-annotation-panel" aria-label="Независимая разметка конструктивной роли">
    <div className="panel-title"><span>Эталонная классификация элемента</span><small>{current?.revision ? `ревизия ${current.revision}` : "ещё не размечено"}</small></div>
    <p className="hint">Укажи физический объект и его класс по облаку точек или проверенному обмеру. Предложенный распознавателем класс не заполнен автоматически. Разметка хранится отдельно от модели и привязана к контрольной сумме набора кандидатов.</p>
    <div className="annotation-suggestion" aria-label="Подсказка распознавателя, не эталон">
      <p><strong>Как это видит распознаватель — проверь по облаку</strong></p>
      <p>Класс: {candidateEvidence.classLabel} · роль: {candidateEvidence.roleLabel} ({candidateEvidence.roleStatus})</p>
      <p>Габариты по bbox: {candidateEvidence.bboxLabel} · источник: {candidateEvidence.sourceLabel} · оценка и основание: {candidateEvidence.confidenceLabel}</p>
      {candidateEvidence.sectionProfileCoverageLabel && <p className="hint">{candidateEvidence.sectionProfileCoverageLabel}</p>}
      {candidateEvidence.sectionProfileWarning && <p className="warn-box" role="note">{candidateEvidence.sectionProfileWarning}</p>}
    </div>
    <p className={pointQuery?.evidence.status === "mismatch" ? "column-type-error" : "hint"} role="status">
      {pointQueryLoading
        ? "Проверяю связь точек с выбранной геометрией…"
        : pointQueryError
          ? "Не удалось проверить точки элемента; причина не установлена."
        : pointQuery
          ? elementPointEvidenceMessage(pointQuery.count, [], pointQuery.evidence)
          : "Проверка точек недоступна."}
    </p>
    <div className="annotation-actions">
      <button type="button" disabled={sourceAuditLoading || busy} onClick={auditSourceEvidence}>
        {sourceAuditLoading ? "Проверяю всё облако…" : "Проверить источники точек во всём облаке"}
      </button>
    </div>
    {sourceAuditError && <p role="alert" className="column-type-error">Не удалось проверить источники: {sourceAuditError}</p>}
    {sourceAudit && <div className="annotation-suggestion" aria-label="Итог проверки источников точек облака">
      <p><strong>Связь индексов с геометрией:</strong> {sourceAudit.status_counts.consistent} подтверждены · {sourceAudit.status_counts.mismatch} не совпадают · {sourceAudit.status_counts.unverifiable} не проверяются</p>
      <p><strong>Снимок исходного облака:</strong> {sourceAudit.source_snapshot_counts.current} актуальны · {sourceAudit.source_snapshot_counts.missing} отсутствуют · {sourceAudit.source_snapshot_counts.stale} устарели · {sourceAudit.source_snapshot_counts.unchecked} не проверены</p>
      <p>Всего кандидатов: {sourceAudit.candidate_count}; требуют внимания: {sourceAudit.attention_count}. Точность распознавания по физическим эталонам: не измерена.</p>
      <ul>{Object.entries(sourceAudit.status_counts_by_class).map(([name, counts]) => <li key={name}>{classLabel(name)}: совпадают {counts.consistent} · ошибка {counts.mismatch} · нет данных {counts.unverifiable}</li>)}</ul>
      {sourceAudit.candidates.length > 0 && <details>
        <summary>Показать первые проблемные записи</summary>
        <ul>{sourceAudit.candidates.slice(0, 8).map((candidate) => <li key={candidate.id}>{classLabel(candidate.class_name)} · {candidate.evidence.status} · {candidate.id}</li>)}</ul>
      </details>}
    </div>}
    {loading && <p role="status">Загружаю эталонную разметку…</p>}
    {error && <p role="alert" className="column-type-error">{error}</p>}
    {notice && <p role="status" className="column-fit-status">{notice}</p>}
    {dataset && <div className="annotation-suggestion" aria-label="Оценка распознавания по проверенным кандидатам">
      <p><strong>Размечено:</strong> {dataset.classification_evaluation.reviewed_counts.labeled} · <strong>неизвестно:</strong> {dataset.classification_evaluation.reviewed_counts.unknown} · <strong>исключено:</strong> {dataset.classification_evaluation.reviewed_counts.excluded} · <strong>ожидает:</strong> {dataset.classification_evaluation.reviewed_counts.pending}</p>
      <p><strong>Класс среди размеченных кандидатов:</strong> {metric(dataset.classification_evaluation.class_metrics.accuracy)} · <strong>роль:</strong> {metric(dataset.classification_evaluation.role_metrics.accuracy)}</p>
      <p className="hint">Это сверка уже найденных кандидатов; пропущенные физические элементы не учтены. Отложенная контрольная выборка не задана, поэтому показатель не подтверждает точность для всего цеха.</p>
    </div>}
    {dataset && <div className="annotation-suggestion" aria-label="Оценка по физическим эталонам">
      <p><strong>Полнота по независимым физическим эталонам</strong></p>
      <p className="hint">Включи сюда все проверенные физические элементы, в том числе пропущенные распознавателем. bbox указывай в метрах в координатах облака. Файл не сохраняется в тренировочную выборку; независимость и holdout требуют отдельной проверки.</p>
      <div className="annotation-actions">
        <button type="button" disabled={loading || evaluating} onClick={downloadEvaluationTemplate}>Скачать JSON-шаблон</button>
        <label className="annotation-reference-upload">Загрузить набор JSON
          <input type="file" accept=".json,application/json" aria-label="JSON с физическими эталонами" onChange={(event) => { setReferenceFile(event.target.files?.[0] || null); setReferenceDrafts([]); setEvaluation(null); }} />
        </label>
      </div>
      <p className="hint">Или внеси физические эталоны здесь. Эти поля принимают только независимые измерения; данные подсказки распознавателя сюда не копируются.</p>
      <div className="column-fit-fields">
        <label><span className="field-label">Набор эталонов</span><input aria-label="Набор физических эталонов" value={referenceMetadata.reference_set_id} onChange={(event) => setReferenceMetadata({ ...referenceMetadata, reference_set_id: event.target.value })} /></label>
        <label><span className="field-label">Разметчик</span><input aria-label="Разметчик физических эталонов" value={referenceMetadata.annotator} onChange={(event) => setReferenceMetadata({ ...referenceMetadata, annotator: event.target.value })} /></label>
        <label><span className="field-label">Источник эталонов</span><select aria-label="Источник физических эталонов" value={referenceMetadata.reference_kind} onChange={(event) => setReferenceMetadata({ ...referenceMetadata, reference_kind: event.target.value as RecognitionEvaluationMetadataDraft["reference_kind"] })}>
          <option value="field_measurement">Полевой обмер</option><option value="manual_cloud">Ручной обмер по облаку</option><option value="mixed">Смешанный</option>
        </select></label>
      </div>
      {referenceDrafts.map((reference, index) => <fieldset className="column-type-card physical-reference-card" key={index}>
        <legend>Измеренный объект {index + 1}</legend>
        <div className="column-fit-fields">
          <label><span className="field-label">Физический ID</span><input aria-label={`Физический ID эталона ${index + 1}`} value={reference.physical_instance_id} onChange={(event) => setReferenceDrafts(referenceDrafts.map((item, row) => row === index ? { ...item, physical_instance_id: event.target.value } : item))} placeholder="например, К-17" /></label>
          <label><span className="field-label">Класс по обмеру</span><select aria-label={`Класс эталона ${index + 1}`} value={reference.class_name} onChange={(event) => setReferenceDrafts(referenceDrafts.map((item, row) => {
            if (row !== index) return item;
            const className = event.target.value;
            return { ...item, class_name: className, role_label: !item.role_label || roleMatchesClass(className, item.role_label) ? item.role_label : "" };
          }))}>
            <option value="">выбери независимо</option>{CLASS_OPTIONS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select></label>
          <label><span className="field-label">Конструктивная роль (если известна)</span><select aria-label={`Роль эталона ${index + 1}`} value={reference.role_label} onChange={(event) => setReferenceDrafts(referenceDrafts.map((item, row) => row === index ? { ...item, role_label: event.target.value } : item))}>
            <option value="">не размечена</option>{roleOptionsForClass(reference.class_name, ROLE_OPTIONS).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select></label>
        </div>
        <div className="physical-reference-coordinates" aria-label={`Габарит эталона ${index + 1}, координаты в метрах`}>
          {(["x", "y", "z"] as const).map((axis) => <div key={axis}>
            <span>{axis.toUpperCase()} (м)</span>
            <input type="text" inputMode="decimal" aria-label={`${axis.toUpperCase()} min, м, эталон ${index + 1}`} placeholder="min" value={reference[`min_${axis}`]} onChange={(event) => setReferenceDrafts(referenceDrafts.map((item, row) => row === index ? { ...item, [`min_${axis}`]: event.target.value } : item))} />
            <input type="text" inputMode="decimal" aria-label={`${axis.toUpperCase()} max, м, эталон ${index + 1}`} placeholder="max" value={reference[`max_${axis}`]} onChange={(event) => setReferenceDrafts(referenceDrafts.map((item, row) => row === index ? { ...item, [`max_${axis}`]: event.target.value } : item))} />
          </div>)}
        </div>
        <button type="button" onClick={() => setReferenceDrafts(referenceDrafts.filter((_, row) => row !== index))}>Удалить эталон</button>
      </fieldset>)}
      <div className="annotation-actions">
        <button type="button" disabled={loading || evaluating} onClick={() => { setReferenceFile(null); setReferenceDrafts([...referenceDrafts, emptyPhysicalReferenceDraft()]); setEvaluation(null); }}>Добавить физический эталон</button>
        <button type="button" disabled={(!referenceFile && referenceDrafts.length === 0) || loading || evaluating} onClick={evaluateIndependentReferences}>{evaluating ? "Сверяю…" : "Рассчитать precision / recall"}</button>
      </div>
      {evaluation && <div role="status">
        <p><strong>Precision:</strong> {metric(evaluation.overall_precision)} · <strong>Recall:</strong> {metric(evaluation.overall_recall)} · <strong>F1:</strong> {metric(evaluation.overall_f1)}</p>
        <p>Эталонов: {evaluation.reference_element_count} · кандидатов: {evaluation.total_detected_candidates} · bbox без объёма: {evaluation.unscorable_detection_geometry_count} · совпадений по осевой метрике: {evaluation.centerline_extent_match_count} ({metric(evaluation.mean_matched_centerline_extent_iou)})</p>
        <p><strong>Конструктивная роль:</strong> precision {metric(evaluation.role_metrics.precision)} · recall {metric(evaluation.role_metrics.recall)} · правильно {evaluation.role_metrics.correct_count}/{evaluation.role_metrics.evaluated_reference_count} · без предложенной роли: {evaluation.role_metrics.unassigned_detection_count}</p>
        <p className="hint">Holdout не подтверждён: сначала нужно проверить, что эталоны не использовались при настройке или обучении. Отчёт не сохранён и не добавлен к обучению.</p>
        {Object.entries(evaluation.per_class).map(([className, scores]) => <p key={className}>{classLabel(className)} · precision {metric(scores.precision)} · recall {metric(scores.recall)} · {scores.true_positives} TP ({scores.centerline_extent_match_count} по осевой метрике) / {scores.false_positives} FP / {scores.false_negatives} FN</p>)}
        {Object.entries(evaluation.role_metrics.per_role).map(([role, scores]) => <p key={`role-${role}`}>Роль {ROLE_OPTIONS.find(([id]) => id === role)?.[1] || role} · precision {metric(scores.precision)} · recall {metric(scores.recall)} · {scores.true_positives} TP / {scores.false_positives} FP / {scores.false_negatives} FN</p>)}
      </div>}
    </div>}
    {dataset && <>
      <div className="column-fit-fields">
        <label><span className="field-label">Разметчик</span><input value={draft.annotator} onChange={(e) => { rememberAnnotationReviewer(cloudId, e.target.value); setDraft({ ...draft, annotator: e.target.value }); }} /></label>
        <label><span className="field-label">Решение</span><select value={draft.state} onChange={(e) => setDraft({ ...draft, state: e.target.value as DraftFields["state"] })}>
          <option value="labeled">Размечено</option><option value="unknown">Неизвестно</option><option value="excluded">Ложный кандидат / исключить</option>
        </select></label>
        {draft.state === "labeled" && <>
          <label><span className="field-label">Физический ID</span><input value={draft.physical_instance_id || ""} onChange={(e) => setDraft({ ...draft, physical_instance_id: e.target.value })} placeholder="например, Б-17" /></label>
          <label><span className="field-label">Эталонный класс</span><select value={draft.class_label || ""} onChange={(e) => {
            const className = e.target.value;
            setDraft({ ...draft, class_label: className, role_label: !draft.role_label || roleMatchesClass(className, draft.role_label) ? draft.role_label : "" });
          }}>
            <option value="">выбери независимо</option>{CLASS_OPTIONS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select></label>
          <label><span className="field-label">Конструктивная роль</span><select value={draft.role_label || ""} onChange={(e) => setDraft({ ...draft, role_label: e.target.value || null })}>
            <option value="">не определена</option>{roleOptionsForClass(draft.class_label || "", ROLE_OPTIONS).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select></label>
          <label><span className="field-label">Марка / тип (если известны)</span><input value={draft.type_label || ""} onChange={(e) => setDraft({ ...draft, type_label: e.target.value })} placeholder="по независимому сравнению" /></label>
        </>}
        {draft.state !== "labeled" && <label><span className="field-label">Причина</span><input value={draft.reason} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} placeholder="например, закрыт оборудованием" /></label>}
      </div>
      <label className="annotation-wide-field"><span className="field-label">Примечание разметчика</span><textarea value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} rows={2} /></label>
      <div className="annotation-actions">
        <button type="button" disabled={busy || saving || loading || !dataset} onClick={save}>{saving ? "Сохраняю…" : "Сохранить независимую разметку"}</button>
        <button type="button" disabled={loading} onClick={exportReferences}>Скачать эталон JSON</button>
      </div>
      {history.length > 0 && <details className="column-type-card"><summary>История разметки · {history.length}</summary>
        {history.map((item) => <p key={`${item.element_id}:${item.revision}`} className="hint">
          v{item.revision} · {item.annotator} · {item.state}{item.class_label ? ` · ${item.class_label}` : ""}{item.role_label ? ` / ${item.role_label}` : ""}{item.type_label ? ` · ${item.type_label}` : ""} · {item.created_at}
        </p>)}
      </details>}
    </>}
  </section>;
}
