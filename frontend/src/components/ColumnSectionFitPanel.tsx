import { useEffect, useMemo, useState } from "react";
import { api, type ColumnSectionFitResponse, type ColumnSurfaceTrackAnalysisResponse } from "../api";
import { buildColumnSurfaceCoverage, type SurfaceCoverageRow, type ColumnSurfaceSide } from "../columnSurfaceCoverage";
import type { Element } from "../types";

interface Props {
  element: Element;
  candidateConflicts: Element[];
  priorDecisions: { id: string; action: string; engineer?: string; note?: string; created_at?: string; after?: { review_status?: string } | null }[];
  busy: boolean;
  onApplyHypothesis: (hypothesis: ColumnSectionFitResponse["hypotheses"][number]) => void;
  onSurfaceAnalysis: (analysis: ColumnSurfaceTrackAnalysisResponse | null) => void;
}

const mm = (metres: number) => (metres * 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 });

const STATUS: Record<ColumnSectionFitResponse["status"], string> = {
  proposed: "Есть предложение контура",
  ambiguous: "Несколько вариантов — нужна проверка",
  open_section: "Наблюдается только открытый угол",
  unknown: "Контур не определён",
  insufficient_points: "Недостаточно точек",
};

const TRACK_STATUS: Record<string, string> = {
  candidate_track: "кандидат грани",
  weak_candidate_track: "слабое наблюдение грани",
  unassigned_surface_track: "грань не назначена",
};

const SECTION_STATUS: Record<string, string> = {
  proposed: "есть гипотеза контура",
  ambiguous: "несколько вариантов",
  open_section: "открытый контур",
  unknown: "контур не определён",
};

export default function ColumnSectionFitPanel({ element, candidateConflicts, priorDecisions, busy, onApplyHypothesis, onSurfaceAnalysis }: Props) {
  const center = element.geometry?.center || [0, 0, 0];
  const [z, setZ] = useState(String(center[2]));
  const [thicknessMm, setThicknessMm] = useState("200");
  const [sideA, setSideA] = useState("");
  const [sideB, setSideB] = useState("");
  const [result, setResult] = useState<ColumnSectionFitResponse | null>(null);
  const [surfaceAnalysis, setSurfaceAnalysis] = useState<ColumnSurfaceTrackAnalysisResponse | null>(null);
  const [hypothesisIndex, setHypothesisIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [coverageRows, setCoverageRows] = useState<SurfaceCoverageRow[]>([]);
  const [coverageLoading, setCoverageLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setResult(null);
    setSurfaceAnalysis(null);
    onSurfaceAnalysis(null);
    setCoverageRows([]);
    setZ(String(center[2]));
    setHypothesisIndex(0);
    setError("");
  }, [element.id, center[2], onSurfaceAnalysis]);

  const hypothesis = result?.hypotheses[hypothesisIndex] || null;
  const display = useMemo(() => {
    if (!result) return null;
    const toLocal = (point: [number, number]): [number, number] => [point[0] - center[0], point[1] - center[1]];
    const points = result.preview_points_xy_local_m;
    const faces = result.observed_faces.map((face) => [toLocal(face.start_world_m), toLocal(face.end_world_m)] as const);
    const corners = hypothesis?.corners_world_m.map(toLocal) || [];
    const all = [...points, ...faces.flatMap((face) => [...face]), ...corners];
    if (!all.length) return { points, faces, corners, viewBox: "-1 -1 2 2" };
    const minX = Math.min(...all.map((point) => point[0]));
    const maxX = Math.max(...all.map((point) => point[0]));
    const minY = Math.min(...all.map((point) => point[1]));
    const maxY = Math.max(...all.map((point) => point[1]));
    const pad = Math.max(.08, (Math.max(maxX - minX, maxY - minY) || 1) * .12);
    const width = Math.max(.1, maxX - minX + pad * 2);
    const height = Math.max(.1, maxY - minY + pad * 2);
    return { points, faces, corners, viewBox: `${minX - pad} ${-(maxY + pad)} ${width} ${height}` };
  }, [center, hypothesis, result]);

  async function measure() {
    setLoading(true);
    setCoverageRows([]);
    setError("");
    try {
      const a = sideA.trim() ? Number(sideA) : null;
      const b = sideB.trim() ? Number(sideB) : null;
      if ((a == null) !== (b == null)) throw new Error("Укажи обе стороны или оставь оба поля пустыми.");
      if ((a != null && (!Number.isFinite(a) || a <= 0)) || (b != null && (!Number.isFinite(b) || b <= 0))) {
        throw new Error("Размеры сторон должны быть положительными числами в миллиметрах.");
      }
      const parsedZ = Number(z);
      const parsedThickness = Number(thicknessMm);
      if (!Number.isFinite(parsedZ) || !Number.isFinite(parsedThickness) || parsedThickness <= 0) {
        throw new Error("Проверь отметку Z и толщину среза.");
      }
      const fitted = await api.fitColumnSection(element.id, {
        slice_z_m: parsedZ,
        thickness_m: parsedThickness / 1000,
        known_sides_m: a != null && b != null ? [a / 1000, b / 1000] : undefined,
      });
      setResult(fitted);
      setHypothesisIndex(0);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }

  async function measureCoverage() {
    const geometry = element.geometry;
    if (geometry?.kind !== "oriented_box") {
      setError("Для карты граней нужна ориентированная коробка колонны.");
      return;
    }
    setCoverageLoading(true);
    setError("");
    setCoverageRows([]);
    setSurfaceAnalysis(null);
    try {
      const analysis = await api.analyzeColumnSurfaceTracks(element.id);
      if (analysis.candidate_id !== element.id || analysis.schema !== "scan.column-surface-track-analysis/1") {
        throw new Error("Сервер вернул результат для другого кандидата или неизвестного формата.");
      }
      const coverageFits = analysis.section_series.section_slices.map((section) => ({
        slice_z_m: section.z_m,
        hypotheses: section.hypotheses,
      }));
      setCoverageRows(buildColumnSurfaceCoverage(coverageFits, geometry));
      setResult(null);
      setSurfaceAnalysis(analysis);
      onSurfaceAnalysis(analysis);
      setHypothesisIndex(0);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setCoverageLoading(false);
    }
  }

  const surfaceLabel: Record<SurfaceCoverageRow["sides"][ColumnSurfaceSide]["status"], string> = {
    observed: "Наблюдается",
    partial: "Частично",
    no_points: "Точки не найдены",
    ambiguous: "Неоднозначно",
    unknown: "Неизвестно",
  };

  return <section className="editor-box column-section-fit" aria-label="Измерение сечения колонны">
    <div className="panel-title"><span>Измерить сечение</span></div>
    <p className="hint">Выбери отметку и, если они известны, введи две стороны. Достроенные грани будут отмечены как предположение.</p>
    <div className="column-fit-fields">
      <label><span className="field-label">Отметка Z, м</span><input type="number" step="0.01" value={z} onChange={(event) => setZ(event.target.value)} /></label>
      <label><span className="field-label">Толщина среза, мм</span><input type="number" min="10" max="1000" step="10" value={thicknessMm} onChange={(event) => setThicknessMm(event.target.value)} /></label>
      <label><span className="field-label">Известная сторона A, мм</span><input type="number" min="1" step="1" value={sideA} onChange={(event) => setSideA(event.target.value)} placeholder="необязательно" /></label>
      <label><span className="field-label">Известная сторона B, мм</span><input type="number" min="1" step="1" value={sideB} onChange={(event) => setSideB(event.target.value)} placeholder="необязательно" /></label>
    </div>
    <button type="button" onClick={measure} disabled={busy || loading}>{loading ? "Измеряю…" : "Построить предложение"}</button>
    <button type="button" className="column-coverage-button" onClick={measureCoverage} disabled={busy || loading || coverageLoading}>
      {coverageLoading ? "Ищу грани и проверяю высоту…" : "Найти грани и измерить по высоте"}
    </button>
    {error && <p role="alert" className="column-type-error">{error}</p>}
    {surfaceAnalysis && <div className="column-fit-evidence" role="status">
      <p><strong>Результат анализа граней:</strong> плоскостей {surfaceAnalysis.surface_result.surfaces.length}, кандидатов граней {surfaceAnalysis.surface_association.candidate_edge_count} из 4, дорожек {surfaceAnalysis.tracks.length}. В анализ вошло {surfaceAnalysis.input_points.count.toLocaleString("ru-RU")} точек.</p>
      <p className="hint">Состояние профиля: {surfaceAnalysis.section_series.profile_variation_status}. Это геометрические гипотезы, не подтверждение колонны или её постоянного типа. В оценку вошли только дорожки с поддержанной гранью; неподдержанные дорожки и высоты остаются видимыми как неизвестные.</p>
      <details>
        <summary>Дорожки граней и исходные строки</summary>
        {surfaceAnalysis.tracks.map((track) => <p className="hint" key={track.track_id}>
          {track.track_id} · {track.candidate_edge_id || "грань не назначена"} · {TRACK_STATUS[track.track_status] || track.track_status} · {track.source_point_row_id_count.toLocaleString("ru-RU")} строк
          {track.source_point_row_id_sample.length > 0 && <> · примеры: <code>{track.source_point_row_id_sample.slice(0, 8).join(", ")}</code></>}
        </p>)}
        {surfaceAnalysis.tracks.length === 0 && <p className="hint">Кандидатные дорожки не найдены; отсутствие точек не доказывает отсутствие грани.</p>}
      </details>
      <details>
        <summary>Сечения по высоте и происхождение</summary>
        {surfaceAnalysis.section_series.section_slices.map((slice) => {
          const dimensions = surfaceAnalysis.section_series.dimensions_by_height_m.find((item) => item.z_m === slice.z_m)?.side_lengths_m;
          return <p className="hint" key={slice.z_m}>
            Z {slice.z_m.toLocaleString("ru-RU", { maximumFractionDigits: 3 })} м · {SECTION_STATUS[slice.status] || slice.status} · {slice.source_point_row_id_count.toLocaleString("ru-RU")} строк
            {dimensions && <> · контур {dimensions.map((value) => `${mm(value)} мм`).join(" × ")}</>}
            {slice.track_ids.length > 0 && <> · дорожки {slice.track_ids.join(", ")}</>}
            {slice.source_point_row_id_sample.length > 0 && <> · строки <code>{slice.source_point_row_id_sample.slice(0, 6).join(", ")}</code></>}
          </p>;
        })}
      </details>
    </div>}
    {coverageRows.length > 0 && <div className="column-surface-coverage" aria-label="Наблюдаемость четырёх граней на пяти высотах">
      <p className="hint">Срезы через равные интервалы по высоте. Зелёный — весь пролёт стороны поддержан найденными точками; охра — частичная опора. «Точки не найдены» не означает, что грань отсутствует: причина может быть в затенении или неполном сканировании.</p>
      <div className="coverage-table-wrap"><table>
        <thead><tr><th scope="col">Z, м</th>{(["u+", "u-", "v+", "v-"] as ColumnSurfaceSide[]).map((side) => <th scope="col" key={side}>{side.toUpperCase()}</th>)}</tr></thead>
        <tbody>{coverageRows.map((row) => <tr key={row.slice_z_m}>
          <th scope="row">{row.slice_z_m.toLocaleString("ru-RU", { maximumFractionDigits: 3 })}</th>
          {(["u+", "u-", "v+", "v-"] as ColumnSurfaceSide[]).map((side) => {
            const cell = row.sides[side];
            return <td key={side} className={`coverage-${cell.status}`} title={cell.coverage_fraction == null ? surfaceLabel[cell.status] : `${surfaceLabel[cell.status]} · ${(cell.coverage_fraction * 100).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}% пролёта`}>
              <span>{surfaceLabel[cell.status]}</span>{cell.coverage_fraction != null && <small>{(cell.coverage_fraction * 100).toLocaleString("ru-RU", { maximumFractionDigits: 0 })}%</small>}
            </td>;
          })}
        </tr>)}</tbody>
      </table></div>
      <p className="hint">U± — противоположные стороны по длине коробки; V± — по толщине. Это карта опоры точками вдоль граней, не оценка площади покрытия и не доказательство видимости поверхности.</p>
    </div>}
    {result && <div className="column-fit-result">
      <p className={result.status === "proposed" ? "column-fit-status" : "column-type-error"} role="status">
        {STATUS[result.status]} · {result.point_count.toLocaleString("ru-RU")} точек
      </p>
      <details className="column-fit-evidence">
        <summary>Основание расчёта и исходные строки</summary>
        <p>Алгоритм {result.algorithm.name} v{result.algorithm.version}. Срез Z={mm(result.parameters.slice_z_m)} мм, толщина {mm(result.parameters.thickness_m)} мм, допуск подгонки {mm(result.parameters.distance_tolerance_m)} мм, запас области {mm(result.parameters.candidate_margin_m)} мм.</p>
        <p>{result.source_rows.count.toLocaleString("ru-RU")} строк производной выборки. {result.source_rows.description}</p>
        <p>Опора граней: {result.point_support.unique_observed_face_point_count.toLocaleString("ru-RU")} из {result.point_support.selected_point_count.toLocaleString("ru-RU")} точек среза ({result.point_support.observed_face_point_fraction == null ? "нет данных" : `${(result.point_support.observed_face_point_fraction * 100).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`}); без назначенной грани {result.point_support.unassigned_point_count.toLocaleString("ru-RU")}.</p>
        <p className="hint">{result.point_support.scope}</p>
      </details>
      <details className="column-fit-evidence">
        <summary>Другие неразмеченные элементы с пересечением габаритов: {candidateConflicts.length}</summary>
        <p className="hint">Это пересечение ограничивающих коробок для контекста проверки, не вывод о том, что элементы являются дублями или одной колонной.</p>
        {candidateConflicts.map((item) => <p className="hint" key={item.id}><code>{item.id}</code> · {item.review_status}</p>)}
        {candidateConflicts.length === 0 && <p className="hint">Пересекающиеся коробки не найдены.</p>}
      </details>
      <details className="column-fit-evidence">
        <summary>Предыдущие решения: {priorDecisions.length}</summary>
        {priorDecisions.length > 0 ? priorDecisions.slice(0, 5).map((decision) => <p className="hint" key={decision.id}>
          {decision.action}{decision.after?.review_status ? ` · ${decision.after.review_status}` : ""}{decision.engineer ? ` · ${decision.engineer}` : ""}{decision.note ? ` — ${decision.note}` : ""}{decision.created_at ? ` · ${new Date(decision.created_at).toLocaleString("ru-RU")}` : ""}
        </p>) : <p className="hint">Для этого элемента решений ещё нет.</p>}
      </details>
      <svg className="column-fit-preview" viewBox={display?.viewBox} role="img" aria-label="Точки, наблюдаемые грани и предлагаемый контур">
        {display?.points.map(([x, y], index) => <circle key={`p${index}`} cx={x} cy={-y} r="0.004" className="column-fit-point" />)}
        {display?.faces.map(([a, b], index) => <line key={`f${index}`} x1={a[0]} y1={-a[1]} x2={b[0]} y2={-b[1]} className="column-fit-face" />)}
        {display?.corners.length === 4 && <>
          {display.corners.map((point, index) => {
            const next = display.corners[(index + 1) % 4];
            const evidence = hypothesis?.edge_evidence[index] || "observed";
            return <line key={`h${index}`} x1={point[0]} y1={-point[1]} x2={next[0]} y2={-next[1]}
              className={evidence === "inferred" ? "column-fit-inferred" : "column-fit-observed"} />;
          })}
        </>}
      </svg>
      {result.hypotheses.length > 1 && <label className="column-fit-choice">Вариант
        <select value={hypothesisIndex} onChange={(event) => setHypothesisIndex(Number(event.target.value))}>
          {result.hypotheses.map((item, index) => <option key={index} value={index}>{index + 1} · {item.side_lengths_m.map(mm).join(" × ")} мм</option>)}
        </select>
      </label>}
      {hypothesis && <>
        <p>Стороны: {hypothesis.side_lengths_m.map(mm).join(" × ")} мм · наблюдаемых граней: {hypothesis.observed_edge_count} · достроено: {hypothesis.inferred_edge_count}.</p>
        <details className="column-fit-evidence">
          <summary>Наблюдаемый пролёт граней</summary>
          <p className="hint">Доля от длины стороны, на которой найден сегмент наблюдаемой грани. Это не гарантия непрерывной видимости поверхности.</p>
          {hypothesis.edge_observation_coverage.map((edge) => <p className="hint" key={edge.edge_index}>
            Грань {edge.edge_index + 1}: {(edge.coverage_fraction * 100).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}% наблюдаемого пролёта ({mm(edge.observed_span_m)} из {mm(edge.length_m)} мм); не наблюдается {mm(edge.unobserved_m)} мм; источник: {edge.source_face_ids.join(", ") || "отсутствует"}.
          </p>)}
        </details>
        <button type="button" disabled={busy} onClick={() => onApplyHypothesis(hypothesis)}>Перенести контур в поля границ</button>
      </>}
      {result.observed_faces.map((face) => <div key={face.face_id} className="hint">
        {face.face_id}: {face.span_kind === "observed_span_lower_bound" ? "нижняя граница наблюдаемого пролёта" : "наблюдаемый пролёт"} {mm(face.observed_span_m)} мм, точек {face.support_count}, остаток RMS {mm(face.rmse_m)} мм, P95 {mm(face.p95_residual_m)} мм; строк источника {face.ingested_point_row_id_count.toLocaleString("ru-RU")}.
        <details><summary>Показать до {result.source_rows.sample_limit_per_face} номеров строк</summary><code>{face.ingested_point_row_id_sample.join(", ") || "Нет строк"}</code></details>
      </div>)}
      {result.open_corners.length > 0 && <details><summary>Открытые углы: {result.open_corners.length}</summary>
        {result.open_corners.map((corner, index) => <p key={index} className="hint">Угол: грани {corner.face_ids.join(", ") || "не определены"}; наблюдаемые пролёты: {corner.observed_spans_m.map(mm).join(" × ")} мм.</p>)}
      </details>}
      {result.dimension_conflicts.length > 0 && <details><summary>Конфликты размеров: {result.dimension_conflicts.length}</summary>
        <pre>{JSON.stringify(result.dimension_conflicts, null, 2)}</pre>
      </details>}
      <p className="hint">Предложение не сохранено: геометрия и тип не менялись. Инженерная точность не оценена.</p>
    </div>}
  </section>;
}
