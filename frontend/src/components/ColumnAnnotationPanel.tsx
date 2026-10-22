import { useEffect, useMemo, useState } from "react";
import { api, type ColumnAnnotation, type ColumnAnnotationArchiveResponse, type ColumnAnnotationDataset, type ColumnAnnotationDraft } from "../api";
import { restoreAnnotationAsDraft } from "../annotationRecovery";
import type { Element } from "../types";

interface Props { cloudId: string; element: Element; busy: boolean; onAnnotationSaved: (annotation: ColumnAnnotation) => void }

type State = ColumnAnnotationDraft["state"];
type Face = "u+" | "u-" | "v+" | "v-";
type HeightDraft = { z: string; long: string; short: string; note: string };
const FACES: { id: Face; label: string }[] = [
  { id: "u+", label: "U+" }, { id: "u-", label: "U−" },
  { id: "v+", label: "V+" }, { id: "v-", label: "V−" },
];
const SHAPES: [NonNullable<ColumnAnnotationDraft["shape_label"]>, string][] = [
  ["rectangular_solid", "Сплошное прямоугольное"], ["built_up", "Составное / двутавровое"],
  ["stepped", "Ступенчатое"], ["circular", "Круглое"], ["other", "Другое"], ["unknown", "Не определено"],
];

function initial(annotation?: ColumnAnnotation): Omit<ColumnAnnotationDraft, "source_snapshot_sha256"> {
  return {
    annotator: annotation?.annotator || "", state: annotation?.state === "pending" ? "labeled" : annotation?.state || "labeled",
    physical_instance_id: annotation?.physical_instance_id || "", type_label: annotation?.type_label || "",
    shape_label: annotation?.shape_label || null, structural_role: annotation?.structural_role || null,
    sides_m: annotation?.sides_m || null, measurement_source: annotation?.measurement_source || null,
    z_measurements: annotation?.z_measurements || [], visible_faces: annotation?.visible_faces || [],
    hidden_faces: annotation?.hidden_faces || [], confidence: annotation?.confidence ?? null,
    reason_unknown: annotation?.reason_unknown || "", note: annotation?.note || "",
  };
}

const mm = (value: number) => (value * 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 });

export default function ColumnAnnotationPanel({ cloudId, element, busy, onAnnotationSaved }: Props) {
  const [dataset, setDataset] = useState<ColumnAnnotationDataset | null>(null);
  const [archivedHistory, setArchivedHistory] = useState<ColumnAnnotationArchiveResponse["history"]>([]);
  const [draft, setDraft] = useState(initial());
  const [longMm, setLongMm] = useState("");
  const [shortMm, setShortMm] = useState("");
  const [heights, setHeights] = useState<HeightDraft[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const current = dataset?.annotations.find((item) => item.element_id === element.id);

  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setDataset(null); setArchivedHistory([]);
    Promise.all([api.columnAnnotations(cloudId), api.columnAnnotationHistory(cloudId)]).then(([value, archive]) => {
      if (active) { setDataset(value); setArchivedHistory(archive.history); }
    }).catch((reason) => {
      if (active) setError(String(reason.message || reason));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [cloudId]);

  useEffect(() => {
    if (!dataset) return;
    setDraft(initial(current));
    setLongMm(current?.sides_m ? String(current.sides_m.long * 1000) : "");
    setShortMm(current?.sides_m ? String(current.sides_m.short * 1000) : "");
    setHeights((current?.z_measurements || []).map((item) => ({
      z: String(item.z_m), long: item.sides_m ? String(item.sides_m.long * 1000) : "",
      short: item.sides_m ? String(item.sides_m.short * 1000) : "", note: item.note || "",
    })));
    setNotice(""); setError("");
  // current is selected from the loaded dataset and must reset only when the selected element changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset?.source_snapshot_sha256, element.id]);

  const history = useMemo(() => dataset?.history.filter((item) => item.element_id === element.id) || [], [dataset, element.id]);

  const parseSides = (long: string, short: string, label: string) => {
    if (!long.trim() && !short.trim()) return null;
    const a = Number(long), b = Number(short);
    if (!Number.isFinite(a) || !Number.isFinite(b) || a <= 0 || b <= 0 || a < b) {
      throw new Error(`${label}: введи обе стороны в мм, где длинная не меньше короткой.`);
    }
    return { long: a / 1000, short: b / 1000 };
  };

  async function save() {
    if (!dataset) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const sides = parseSides(longMm, shortMm, "Сечение");
      const zMeasurements = heights.map((row, index) => {
        const z = Number(row.z);
        if (!row.z.trim() || !Number.isFinite(z)) throw new Error(`Строка отметки ${index + 1}: проверь Z.`);
        return { z_m: z, sides_m: parseSides(row.long, row.short, `Отметка ${row.z} м`), note: row.note };
      });
      const hasMeasuredSides = sides !== null || zMeasurements.some((item) => item.sides_m !== null);
      const payload: ColumnAnnotationDraft = {
        source_snapshot_sha256: dataset.source_snapshot_sha256,
        ...draft,
        physical_instance_id: draft.physical_instance_id?.trim() || null,
        type_label: draft.type_label?.trim() || null,
        sides_m: sides,
        measurement_source: hasMeasuredSides ? (draft.measurement_source || "manual_cloud") : null,
        z_measurements: zMeasurements,
      };
      const saved = await api.saveColumnAnnotation(cloudId, element.id, payload);
      onAnnotationSaved(saved);
      setDataset((previous) => previous ? {
        ...previous,
        annotations: previous.annotations.map((item) => item.element_id === element.id ? saved : item),
        history: [...previous.history, saved],
      } : previous);
      setNotice(`Сохранена ревизия ${saved.revision}; распознанная геометрия не менялась.`);
    } catch (reason) {
      setError(String(reason instanceof Error ? reason.message : reason));
    } finally { setSaving(false); }
  }

  async function downloadReference() {
    setError("");
    try {
      const reference = await api.exportColumnAnnotations(cloudId);
      const blob = new Blob([JSON.stringify(reference, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `${dataset?.dataset_id.replaceAll(":", "-") || "column-reference"}.json`;
      anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (reason) { setError(String(reason instanceof Error ? reason.message : reason)); }
  }

  function downloadArchivedHistory() {
    const blob = new Blob([JSON.stringify({ schema: "scan.column-annotation-history/1", history: archivedHistory }, null, 2)],
      { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `${cloudId}-column-annotation-history.json`;
    anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  function restoreArchived(item: ColumnAnnotationArchiveResponse["history"][number]) {
    if (!dataset) return;
    try {
      const restored = restoreAnnotationAsDraft(item, dataset.source_snapshot_sha256);
      const { source_snapshot_sha256: _snapshot, ...draftValues } = restored;
      setDraft(draftValues);
      setLongMm(restored.sides_m ? String(restored.sides_m.long * 1000) : "");
      setShortMm(restored.sides_m ? String(restored.sides_m.short * 1000) : "");
      setHeights(restored.z_measurements.map((measurement) => ({
        z: String(measurement.z_m),
        long: measurement.sides_m ? String(measurement.sides_m.long * 1000) : "",
        short: measurement.sides_m ? String(measurement.sides_m.short * 1000) : "",
        note: measurement.note || "",
      })));
      setError("");
      setNotice(`Ревизия ${item.revision} из снимка ${item.source_snapshot_sha256.slice(0, 12)} загружена как черновик. Проверь соответствие текущей геометрии; изменения ещё не сохранены.`);
    } catch (reason) {
      setError(String(reason instanceof Error ? reason.message : reason));
    }
  }

  const toggleFace = (field: "visible_faces" | "hidden_faces", face: Face) => {
    setDraft((value) => ({ ...value, [field]: value[field].includes(face)
      ? value[field].filter((item) => item !== face) : [...value[field], face] }));
  };

  return <section className="editor-box column-annotation-panel" aria-label="Независимая разметка колонны">
    <div className="panel-title"><span>Эталонная разметка</span><small>{current?.revision ? `ревизия ${current.revision}` : "ещё не размечено"}</small></div>
    <p className="hint">Заполняй по выбранным исходным точкам/сечениям или полевому обмеру. Поля пустые, распознанные размеры не копируются. Снимок: {dataset?.source_snapshot_sha256.slice(0, 12) || "…"}.</p>
    {loading && <p role="status">Загружаю набор эталонов…</p>}
    {error && <p role="alert" className="column-type-error">{error}</p>}
    {notice && <p role="status" className="column-fit-status">{notice}</p>}
    {dataset && <>
      <div className="column-fit-fields">
        <label><span className="field-label">Разметчик</span><input value={draft.annotator} onChange={(e) => setDraft({ ...draft, annotator: e.target.value })} /></label>
        <label><span className="field-label">Решение</span><select value={draft.state} onChange={(e) => setDraft({ ...draft, state: e.target.value as State })}>
          <option value="labeled">Размечено</option><option value="unknown">Неизвестно</option><option value="excluded">Ложный кандидат / исключить</option>
        </select></label>
        <label><span className="field-label">Физический ID</span><input value={draft.physical_instance_id || ""} onChange={(e) => setDraft({ ...draft, physical_instance_id: e.target.value })} placeholder="например, К-17" /></label>
        <label><span className="field-label">Марка эталонного типа</span><input value={draft.type_label || ""} onChange={(e) => setDraft({ ...draft, type_label: e.target.value })} placeholder="по независимому сравнению" /></label>
        <label><span className="field-label">Форма</span><select value={draft.shape_label || ""} onChange={(e) => setDraft({ ...draft, shape_label: (e.target.value || null) as ColumnAnnotationDraft["shape_label"] })}>
          <option value="">не указана</option>{SHAPES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select></label>
        <label><span className="field-label">Конструктивная роль</span><select value={draft.structural_role || ""} onChange={(e) => setDraft({ ...draft, structural_role: (e.target.value || null) as ColumnAnnotationDraft["structural_role"] })}>
          <option value="">не указана</option><option value="column">Колонна</option><option value="crane_column">Подкрановая колонна</option><option value="other">Другая</option><option value="unknown">Неизвестно</option>
        </select></label>
        <label><span className="field-label">Длинная сторона, мм</span><input type="number" min="0" step="any" value={longMm} onChange={(e) => setLongMm(e.target.value)} /></label>
        <label><span className="field-label">Короткая сторона, мм</span><input type="number" min="0" step="any" value={shortMm} onChange={(e) => setShortMm(e.target.value)} /></label>
        {(longMm || shortMm || heights.some((item) => item.long || item.short)) && <label><span className="field-label">Источник размеров</span><select value={draft.measurement_source || "manual_cloud"} onChange={(e) => setDraft({ ...draft, measurement_source: e.target.value as ColumnAnnotationDraft["measurement_source"] })}>
          <option value="manual_cloud">Ручной замер по облаку</option><option value="field_measurement">Полевой контрольный замер</option>
        </select></label>}
        <label><span className="field-label">Уверенность разметки, 0–1</span><input type="number" min="0" max="1" step="0.05" value={draft.confidence ?? ""} onChange={(e) => setDraft({ ...draft, confidence: e.target.value === "" ? null : Number(e.target.value) })} /></label>
      </div>
      <div className="annotation-face-grid">{(["visible_faces", "hidden_faces"] as const).map((field) => <fieldset key={field}>
        <legend>{field === "visible_faces" ? "Видимые грани" : "Закрытые / невидимые грани"}</legend>
        {FACES.map((face) => <label key={face.id}><input type="checkbox" checked={draft[field].includes(face.id)} onChange={() => toggleFace(field, face.id)} />{face.label}</label>)}
      </fieldset>)}</div>
      <div className="annotation-heights">
        <div className="panel-title"><span>Измерения по высоте, м / мм</span><button type="button" onClick={() => setHeights((items) => [...items, { z: "", long: "", short: "", note: "" }])}>Добавить отметку</button></div>
        {heights.map((row, index) => <div className="annotation-height-row" key={index}>
          <input aria-label="Отметка Z, м" type="number" step="any" placeholder="Z, м" value={row.z} onChange={(e) => setHeights((items) => items.map((item, i) => i === index ? { ...item, z: e.target.value } : item))} />
          <input aria-label="Длинная сторона на отметке, мм" type="number" step="any" placeholder="длинная, мм" value={row.long} onChange={(e) => setHeights((items) => items.map((item, i) => i === index ? { ...item, long: e.target.value } : item))} />
          <input aria-label="Короткая сторона на отметке, мм" type="number" step="any" placeholder="короткая, мм" value={row.short} onChange={(e) => setHeights((items) => items.map((item, i) => i === index ? { ...item, short: e.target.value } : item))} />
          <input aria-label="Примечание к отметке" placeholder="примечание" value={row.note} onChange={(e) => setHeights((items) => items.map((item, i) => i === index ? { ...item, note: e.target.value } : item))} />
          <button type="button" aria-label="Удалить отметку" onClick={() => setHeights((items) => items.filter((_, i) => i !== index))}>×</button>
        </div>)}
      </div>
      {(draft.state === "unknown" || draft.state === "excluded") && <label className="annotation-wide-field"><span className="field-label">Почему неизвестно / исключено</span><textarea value={draft.reason_unknown} onChange={(e) => setDraft({ ...draft, reason_unknown: e.target.value })} rows={2} /></label>}
      <label className="annotation-wide-field"><span className="field-label">Примечание разметчика</span><textarea value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} rows={2} /></label>
      <div className="annotation-actions"><button type="button" disabled={busy || saving || loading} onClick={save}>{saving ? "Сохраняю ревизию…" : "Сохранить независимую разметку"}</button>
        <button type="button" disabled={loading || history.length === 0} onClick={downloadReference}>Скачать эталон JSON</button></div>
      {history.length > 0 && <details className="column-type-card"><summary>История разметки · {history.length}</summary>
        {history.map((item) => <p key={`${item.element_id}:${item.revision}`} className="hint">v{item.revision} · {item.annotator} · {item.state}{item.type_label ? ` · ${item.type_label}` : ""}{item.sides_m ? ` · ${mm(item.sides_m.long)} × ${mm(item.sides_m.short)} мм` : ""} · {item.created_at}</p>)}
      </details>}
      {archivedHistory.length > 0 && <details className="column-type-card"><summary>Разметка прежних снимков · {archivedHistory.length}</summary>
        <p className="hint">Эти решения привязаны к другим хешам исходного облака или геометрии и не переносятся на текущий кандидат автоматически.</p>
        {archivedHistory.filter((item) => item.element_id === element.id).map((item) => <article key={`${item.source_snapshot_sha256}:${item.revision}`} className="column-type-card">
          <p className="hint">{item.dataset_id} · v{item.revision} · {item.state}{item.type_label ? ` · ${item.type_label}` : ""} · {item.created_at}</p>
          <button type="button" disabled={busy || saving || loading} onClick={() => restoreArchived(item)}>Восстановить в черновик</button>
        </article>)}
        <button type="button" onClick={downloadArchivedHistory}>Скачать историю старых снимков</button>
      </details>}
    </>}
  </section>;
}
