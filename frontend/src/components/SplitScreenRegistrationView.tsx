import React, { useEffect, useMemo, useState } from "react";
import Viewer3D from "./Viewer3D";
import { RegistrationOverlayPreview } from "./RegistrationOverlayPreview";
import { type Cloud } from "../types";
import { api, type StationRegistrationProposal } from "../api";
import { registrationOutcome } from "../registrationOutcome";
import { defaultRegistrationCloudIds } from "../registrationCloudSelection";
import { parseRegistrationControlsCsv } from "../registrationControlCsv";
import { filterRegistrationStations } from "../stationFilter";
import "./SplitScreenRegistrationView.css";

type CoordinateInput = [string, string, string];
type SurveyControlInput = { label: string; source: CoordinateInput; target: CoordinateInput };

const emptySurveyControl = (index: number): SurveyControlInput => ({
  label: `Контроль ${index + 1}`,
  source: ["", "", ""],
  target: ["", "", ""],
});

interface SplitScreenRegistrationViewProps {
  clouds: Cloud[];
  initialSourceCloudId?: string;
  onClose: () => void;
}

export const SplitScreenRegistrationView: React.FC<SplitScreenRegistrationViewProps> = ({
  clouds,
  initialSourceCloudId,
  onClose,
}) => {
  const readyClouds = useMemo(() => clouds.filter((cloud) => cloud.status === "ready"), [clouds]);
  const initialCloudPair = defaultRegistrationCloudIds(readyClouds, initialSourceCloudId);
  const [sourceCloudId, setSourceCloudId] = useState(initialCloudPair.sourceId);
  const [targetCloudId, setTargetCloudId] = useState(initialCloudPair.targetId);
  const [stationQuery, setStationQuery] = useState("");
  const [detectedTargets, setDetectedTargets] = useState(0);
  const [targetDiameterMm, setTargetDiameterMm] = useState("");
  const [isDetecting, setIsDetecting] = useState(false);
  const [isMatching, setIsMatching] = useState(false);
  const [maxCorrespondenceDistanceM, setMaxCorrespondenceDistanceM] = useState(0.15);
  const [alignStatus, setAlignStatus] = useState<string | null>(null);
  const [registrationResult, setRegistrationResult] = useState<
    Awaited<ReturnType<typeof api.matchCloudsIcp>> | Awaited<ReturnType<typeof api.matchCloudsGlobalFgrIcp>> | null
  >(null);
  const [manualPairs, setManualPairs] = useState<Array<{ source_point: [number, number, number]; target_point: [number, number, number]; label: string }>>([]);
  const [pendingSourcePoint, setPendingSourcePoint] = useState<[number, number, number] | null>(null);
  const [pickSide, setPickSide] = useState<"source" | "target" | null>(null);
  const [manualResult, setManualResult] = useState<Awaited<ReturnType<typeof api.pairAlign>> | null>(null);
  const [isManualAligning, setIsManualAligning] = useState(false);
  const [surveyControls, setSurveyControls] = useState<SurveyControlInput[]>([
    emptySurveyControl(0), emptySurveyControl(1), emptySurveyControl(2),
  ]);
  const [controlsIndependent, setControlsIndependent] = useState(false);
  const [isEvaluatingControls, setIsEvaluatingControls] = useState(false);
  const [controlEvaluation, setControlEvaluation] = useState<Awaited<ReturnType<typeof api.evaluateRegistrationControls>> | null>(null);
  const [showCombinedPreview, setShowCombinedPreview] = useState(false);
  const [savedStationPairs, setSavedStationPairs] = useState<StationRegistrationProposal[]>([]);
  const [isSavingStationPair, setIsSavingStationPair] = useState(false);
  const [isExportingStationPair, setIsExportingStationPair] = useState(false);
  const [stationRcpExport, setStationRcpExport] = useState<{
    rcpPath: string;
    sourceName: string;
    targetName: string;
    rcpNodeCount: number;
    linkedRcsCount: number;
    externalRcsCount: number;
    packageVerified: boolean;
    sourceFilesCopiedForDecap: boolean;
    sourceCachePath: string | null;
  } | null>(null);
  const sourceCloud = readyClouds.find((cloud) => cloud.id === sourceCloudId) || null;
  const targetCloud = readyClouds.find((cloud) => cloud.id === targetCloudId) || null;
  const readyStationIndices = useMemo(() => new Map(readyClouds.map((station, index) => [station.id, index])), [readyClouds]);
  const filteredStations = useMemo(() => filterRegistrationStations(readyClouds, stationQuery)
    .map((station) => ({ station, index: readyStationIndices.get(station.id) ?? 0 })), [readyClouds, readyStationIndices, stationQuery]);
  const previewTransform = manualResult?.matrix_4x4 || registrationResult?.matrix_4x4 || null;
  const currentPairState = controlEvaluation
    ? controlEvaluation.criterion_passed ? "provisional" : "review"
    : registrationResult || manualResult
      ? "review"
      : "pending";
  const activeStationPair = sourceCloud && targetCloud
    ? { source: sourceCloud, target: targetCloud }
    : null;
  const filledSurveyControlCount = surveyControls.filter((control) =>
    [...control.source, ...control.target].every((value) => value.trim() !== "" && Number.isFinite(Number(value))),
  ).length;
  const totalReadyPoints = readyClouds.reduce((total, cloud) => total + (cloud.point_count || 0), 0);
  const projectId = sourceCloud?.project_id || targetCloud?.project_id || null;

  useEffect(() => {
    let cancelled = false;
    setSavedStationPairs([]);
    if (!projectId) return;
    void api.listStationRegistrations(projectId).then((result) => {
      if (!cancelled) setSavedStationPairs(result.items);
    }).catch((error: any) => {
      if (!cancelled) setAlignStatus(`Не удалось загрузить сохранённые пары станций: ${error.message || String(error)}`);
    });
    return () => { cancelled = true; };
  }, [projectId]);

  const handleSaveStationPair = async () => {
    if (!projectId || !sourceCloud || !targetCloud || sourceCloud.project_id !== targetCloud.project_id) {
      setAlignStatus("Выберите две готовые станции одного проекта.");
      return;
    }
    const result = manualResult || registrationResult;
    if (!result) return;
    setIsSavingStationPair(true);
    try {
      const method = manualResult
        ? manualResult.refined_with_icp ? "manual_kabsch_icp" : "manual_kabsch"
        : registrationResult?.method === "open3d_fgr_point_to_plane_icp"
          ? "open3d_fgr_point_to_plane_icp"
          : "rigid_icp";
      const saved = await api.saveStationRegistration(projectId, {
        source_station_id: sourceCloud.id,
        target_station_id: targetCloud.id,
        method,
        matrix_4x4: result.matrix_4x4,
        world_matrix_4x4: result.world_matrix_4x4,
        fit_rmse_mm: result.rmse_mm,
      });
      setSavedStationPairs((current) => [saved.item, ...current.filter((item) => item.id !== saved.item.id)]);
      setAlignStatus("Черновик пары станций сохранён. Независимая точность не подтверждена; преобразование не применено, RCP не изменён.");
    } catch (error: any) {
      setAlignStatus(`Не удалось сохранить черновик пары станций: ${error.message || String(error)}`);
    } finally {
      setIsSavingStationPair(false);
    }
  };

  const handleExportStationPairToRecap = async () => {
    if (!projectId || !sourceCloud || !targetCloud || sourceCloud.project_id !== targetCloud.project_id) {
      setAlignStatus("Выберите две готовые станции одного проекта.");
      return;
    }
    if (sourceCloud.id === targetCloud.id) {
      setAlignStatus("Для проекта ReCap выберите две разные станции.");
      return;
    }
    if (!sourceCloud.source_path || !targetCloud.source_path) {
      setAlignStatus("У одной из выбранных станций не найден исходный файл.");
      return;
    }
    if (sourceCloud.source_path.trim().replaceAll("\\", "/").toLocaleLowerCase("en-US") === targetCloud.source_path.trim().replaceAll("\\", "/").toLocaleLowerCase("en-US")) {
      setAlignStatus("У выбранных станций один и тот же исходный файл. Выберите две разные станции.");
      return;
    }

    const projectName = `SCAN_${projectId.slice(0, 8)}_${Date.now()}`;
    setIsExportingStationPair(true);
    setAlignStatus(null);
    try {
      const result = await api.exportNativeRecapProject(projectName, [
        { name: sourceCloud.name, path: sourceCloud.source_path, point_count: sourceCloud.point_count },
        { name: targetCloud.name, path: targetCloud.source_path, point_count: targetCloud.point_count },
      ]);
      setStationRcpExport({
        rcpPath: result.rcp_path,
        sourceName: sourceCloud.name,
        targetName: targetCloud.name,
        rcpNodeCount: result.rcp_node_count,
        linkedRcsCount: result.linked_rcs_count,
        externalRcsCount: result.external_rcs_count,
        packageVerified: result.package_verified,
        sourceFilesCopiedForDecap: result.source_files_copied_for_decap,
        sourceCachePath: result.source_cache_path,
      });
      setAlignStatus(result.package_verified
        ? "RCP создан и проверен вместе с файлами станций. Регистрацию завершите в ReCap."
        : result.source_files_copied_for_decap
          ? "RCP создан, но часть ссылок выходит за Support. Копии станций включены в комплект; перед переносом проверьте перечисленные внешние RCS. Регистрацию завершите в ReCap."
          : result.external_rcs_count
            ? "RCP создан и проверен. Станции остаются отдельными и ссылаются на исходные RCS; перед переносом проекта проверьте доступность этих файлов. Регистрацию завершите в ReCap."
            : "RCP создан и проверен. Регистрация станций не выполнена — завершите её в ReCap.");
    } catch (error: any) {
      setAlignStatus(`Не удалось создать проект ReCap: ${error.message || String(error)}`);
    } finally {
      setIsExportingStationPair(false);
    }
  };

  const resetManualPairs = () => {
    setManualPairs([]);
    setPendingSourcePoint(null);
    setManualResult(null);
    setPickSide(null);
    setControlEvaluation(null);
    setShowCombinedPreview(false);
  };

  const resetSurveyControls = () => {
    setSurveyControls([emptySurveyControl(0), emptySurveyControl(1), emptySurveyControl(2)]);
    setControlsIndependent(false);
    setControlEvaluation(null);
  };

  const handleSourcePointPicked = (point: [number, number, number]) => {
    setShowCombinedPreview(false);
    setPendingSourcePoint(point);
    setPickSide("target");
    setManualResult(null);
    setControlEvaluation(null);
    setRegistrationResult(null);
    setAlignStatus(`Точка A выбрана (${point.map((value) => value.toFixed(3)).join(", ")} м). Теперь щёлкните ту же физическую точку на станции B.`);
  };

  const handlePointPickMiss = (side: "A" | "B") => {
    setAlignStatus(`Точка ${side} не попала в отображаемые точки. Приблизьте вид и щёлкните по поверхности облака; пустое место не записано.`);
  };

  const handleTargetPointPicked = (point: [number, number, number]) => {
    setShowCombinedPreview(false);
    if (!pendingSourcePoint) {
      setPickSide("source");
      setAlignStatus("Сначала выберите физическую точку на подвижной станции A.");
      return;
    }
    const next = [...manualPairs, {
      source_point: pendingSourcePoint,
      target_point: point,
      label: `Репер ${manualPairs.length + 1}`,
    }];
    setManualPairs(next);
    setPendingSourcePoint(null);
    setPickSide("source");
    setManualResult(null);
    setControlEvaluation(null);
    setRegistrationResult(null);
    setAlignStatus(`Добавлена пара ${next.length}. ${next.length < 3 ? "Нужно не менее трёх разнесённых пар; выберите следующую точку в A." : "Можно рассчитать предварительное преобразование."}`);
  };

  const handleEvaluateSurveyControls = async () => {
    if (!sourceCloud || !targetCloud) return;
    const matrix = manualResult?.matrix_4x4 || registrationResult?.matrix_4x4;
    if (!matrix) {
      setAlignStatus("Сначала рассчитайте преобразование по парам или ICP.");
      return;
    }
    if (!controlsIndependent) {
      setAlignStatus("Подтвердите, что эти полевые контроли не участвовали в подгонке или ICP.");
      return;
    }
    const parsed = surveyControls.map((control) => {
      const coordinates = [...control.source, ...control.target];
      if (coordinates.some((value) => value.trim() === "" || !Number.isFinite(Number(value)))) return null;
      return {
        source_point: control.source.map(Number) as [number, number, number],
        target_point: control.target.map(Number) as [number, number, number],
        label: control.label.trim() || undefined,
      };
    });
    if (parsed.some((control) => control === null)) {
      setAlignStatus("Заполните все шесть координат для каждой контрольной точки.");
      return;
    }
    setIsEvaluatingControls(true);
    setControlEvaluation(null);
    try {
      const result = await api.evaluateRegistrationControls(
        sourceCloud.id,
        targetCloud.id,
        matrix,
        parsed as NonNullable<(typeof parsed)[number]>[],
        true,
        10,
      );
      setControlEvaluation(result);
      setAlignStatus(`Независимые контроли: RMSE ${result.rmse_mm.toFixed(2)} мм из ${result.independent_control_count}; максимум ${result.max_error_mm.toFixed(2)} мм. Допуск 10 мм: ${result.criterion_passed ? "выполнен" : "не выполнен"}. Контрольные точки не сохранены, преобразование не применено.`);
    } catch (error: any) {
      setControlEvaluation(null);
      setAlignStatus(`Ошибка проверки контролей: ${error.message || String(error)}`);
    } finally {
      setIsEvaluatingControls(false);
    }
  };

  const handleImportSurveyControls = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    try {
      const imported = parseRegistrationControlsCsv(await file.text());
      setSurveyControls(imported);
      setControlsIndependent(false);
      setControlEvaluation(null);
      setAlignStatus(`Импортировано ${imported.length} контрольных точек из CSV. Проверьте локальные системы координат и заново подтвердите независимость контролей.`);
    } catch (error: any) {
      setAlignStatus(`CSV контролей не загружен: ${error.message || String(error)}`);
    }
  };

  const handleManualAlign = async () => {
    if (!sourceCloud || !targetCloud || manualPairs.length < 3) return;
    setShowCombinedPreview(false);
    setIsManualAligning(true);
    setManualResult(null);
    setRegistrationResult(null);
    setControlEvaluation(null);
    try {
      const result = await api.pairAlign(sourceCloud.id, targetCloud.id, manualPairs, false);
      setManualResult(result);
      setAlignStatus(`Ручной Kabsch рассчитан по ${result.pairs_count} парам: RMSE ${result.rmse_mm.toFixed(2)} мм, максимум ${result.max_error_mm.toFixed(2)} мм. Это невязка выбранных точек, независимая точность не подтверждена; преобразование не применено.`);
    } catch (error: any) {
      setAlignStatus(`Ошибка ручного расчёта: ${error.message || String(error)}`);
    } finally {
      setIsManualAligning(false);
    }
  };

  const handleAutoMatchICP = async () => {
    if (!sourceCloud || !targetCloud || sourceCloud.id === targetCloud.id) return;
    setShowCombinedPreview(false);
    setIsMatching(true);
    setRegistrationResult(null);
    setManualResult(null);
    setControlEvaluation(null);
    setAlignStatus("Предварительная оценка Rigid ICP по выборке точек…");
    try {
      const res = await api.matchCloudsIcp(sourceCloud.id, targetCloud.id);
      setRegistrationResult(res);
      const outcome = registrationOutcome(res);
      const rmseStr = res.rmse_mm != null ? `${res.rmse_mm.toFixed(2)} мм` : "не вычислена";
      const support = `${res.inlier_count}/${res.source_sample_count} (${(res.inlier_fraction * 100).toFixed(1)}%)`;
      setAlignStatus(`${outcome.label}. RMSE выборки: ${rmseStr}; итераций: ${res.iterations}; точек с парами в радиусе 0,5 м: ${support}. ${outcome.detail}`);
    } catch (e: any) {
      setRegistrationResult(null);
      setAlignStatus(`Ошибка автосшивки: ${e.message || String(e)}`);
    } finally {
      setIsMatching(false);
    }
  };
  const handleGlobalFgrMatch = async () => {
    if (!sourceCloud || !targetCloud || sourceCloud.id === targetCloud.id) return;
    setShowCombinedPreview(false);
    setIsMatching(true);
    setRegistrationResult(null);
    setManualResult(null);
    setControlEvaluation(null);
    setAlignStatus("Глобальный подбор FGR и уточнение ICP; результат будет предварительным…");
    try {
      const res = await api.matchCloudsGlobalFgrIcp(sourceCloud.id, targetCloud.id, 100000, 42, maxCorrespondenceDistanceM);
      setRegistrationResult(res);
      const fit = res.rmse_mm != null ? `${res.rmse_mm.toFixed(1)} мм` : "не вычислена";
      const holdout = res.holdout.status === "evaluated"
        ? `Отложенная выборка (не участвовала в подгонке): RMSE ${res.holdout.rmse_mm != null ? `${res.holdout.rmse_mm.toFixed(1)} мм` : "не вычислена"}, соответствия ${res.holdout.inlier_count}/${res.holdout.source_sample_count} (${((res.holdout.inlier_fraction ?? 0) * 100).toFixed(1)}%).`
        : "Отложенная выборка недоступна: в облаках недостаточно точек для разделения fit/оценки.";
      setAlignStatus(`Предварительный кандидат FGR → ICP: fit RMSE ${fit}; доля fit-пар в радиусе ${(res.max_correspondence_distance_m * 1000).toFixed(0)} мм — ${(res.inlier_fraction * 100).toFixed(1)}%. ${holdout} Это оценка на других строках тех же сканов, не геодезический контроль. Open3D не сообщает факт сходимости; точность не подтверждена, матрица не применена.`);
    } catch (error: any) {
      setRegistrationResult(null);
      setAlignStatus(`Глобальный подбор не выполнен: ${error.message || String(error)}`);
    } finally {
      setIsMatching(false);
    }
  };

  const emptySections: [Float32Array, Float32Array, Float32Array] = [
    new Float32Array(0),
    new Float32Array(0),
    new Float32Array(0),
  ];

  const handleDetectTargets = async (cloudId: string) => {
    const diameterMm = Number(targetDiameterMm.replace(",", "."));
    if (!Number.isFinite(diameterMm) || diameterMm <= 0) {
      setAlignStatus("Введите фактический диаметр установленной сферы в миллиметрах.");
      return;
    }
    setIsDetecting(true);
    try {
      const resp = await fetch("/api/v1/registration/detect-targets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cloud_id: cloudId, expected_radius_m: diameterMm / 2000, sample_points: 50000 }),
      });
      const data = await resp.json();
      if (data.status === "ok" && data.targets) {
        setDetectedTargets(data.targets_found || data.targets.length);
        setAlignStatus(`Найдено кандидатов-сфер: ${data.targets_found || data.targets.length}. Это не подтверждает общие цели или регистрацию станций.`);
      } else {
        throw new Error(data.detail || data.message || `HTTP ${resp.status}`);
      }
    } catch (e: any) {
      setAlignStatus(`Поиск целей не выполнен: ${e.message || String(e)}`);
    } finally {
      setIsDetecting(false);
    }
  };

  return (
    <div className="registration-screen">
      {/* Top Split-Screen Control Bar */}
      <div className="registration-toolbar">
        <div className="registration-toolbar-title">
          <span style={{ color: "#FF812E", fontWeight: 700, fontSize: 13, textTransform: "uppercase" }}>
            Сшивка станций
          </span>
          <span className="registration-pair-summary">
            <span><b>A</b> {sourceCloud?.name || "не выбрана"}</span>
            <span aria-hidden="true">↔</span>
            <span><b>B</b> {targetCloud?.name || "не выбрана"}</span>
          </span>
        </div>

        <div className="registration-toolbar-controls">
          <span className="registration-selection-hint">{sourceCloud && targetCloud ? "Пара станций выбрана" : "Выберите A и B в списке станций"}</span>
          <button type="button" onClick={onClose} aria-label="Вернуться к обработке" className="registration-back-button">К обработке</button>
        </div>
      </div>

      <div className="registration-layout">
        <aside className="registration-stations" aria-label="Станции проекта">
          <div className="registration-panel-heading"><strong>Станции проекта</strong><span>{readyClouds.length} доступны</span></div>
          <p className="registration-panel-hint">Выберите две отдельные станции. A — подвижная, B — опорная.</p>
          <label className="registration-station-search">
            <input
              type="search"
              value={stationQuery}
              onChange={(event) => setStationQuery(event.target.value)}
              placeholder="Найти станцию…"
              aria-label="Фильтр станций по имени, ID или формату"
              autoComplete="off"
            />
            {stationQuery && <button type="button" onClick={() => setStationQuery("")} aria-label="Очистить фильтр станций">×</button>}
          </label>
          <div className="registration-station-filter-count" role="status" aria-live="polite">
            {stationQuery.trim() ? `Показано ${filteredStations.length} из ${readyClouds.length}` : `Показаны все ${readyClouds.length}`}
            {stationQuery.trim() && (sourceCloud || targetCloud) && <span> · роли A/B сохранены</span>}
          </div>
          <div className="registration-station-list">
            {filteredStations.map(({ station, index }) => {
              const isSource = station.id === sourceCloudId;
              const isTarget = station.id === targetCloudId;
              return <div key={station.id} className={`registration-station${isSource || isTarget ? " is-active" : ""}`}>
                <span className="registration-station-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="registration-station-name-wrap">
                  <span className="registration-station-name" title={station.name}>{station.name}</span>
                  <span className="registration-station-meta">{station.point_count.toLocaleString("ru-RU")} точек · {station.source_format.toUpperCase()}</span>
                </span>
                <button type="button" aria-label={`Назначить ${station.name} подвижной станцией`} aria-pressed={isSource} onClick={() => {
                  setSourceCloudId(station.id);
                  if (station.id === targetCloudId) setTargetCloudId(readyClouds.find((candidate) => candidate.id !== station.id)?.id || "");
                  resetManualPairs(); resetSurveyControls(); setRegistrationResult(null); setAlignStatus(null);
                }} className={`registration-role-button${isSource ? " is-source" : ""}`}>A</button>
                <button type="button" aria-label={`Назначить ${station.name} базовой станцией`} aria-pressed={isTarget} disabled={station.id === sourceCloudId} onClick={() => {
                  setTargetCloudId(station.id);
                  resetManualPairs(); resetSurveyControls(); setRegistrationResult(null); setAlignStatus(null);
                }} className={`registration-role-button${isTarget ? " is-target" : ""}`}>B</button>
              </div>;
            })}
            {!readyClouds.length && <p className="registration-panel-hint">Нет готовых станций. Импортируйте данные и дождитесь завершения обработки.</p>}
            {!!readyClouds.length && !filteredStations.length && <p className="registration-panel-hint" role="status">По запросу «{stationQuery}» станции не найдены.</p>}
          </div>
          <div className="registration-station-legend"><span><i className="legend-a" /> A · подвижная</span><span><i className="legend-b" /> B · опорная</span></div>
        </aside>

        <main className="registration-main" aria-label="Совмещение и проверка точности">

      {alignStatus && (
        <div className={`registration-status-message${alignStatus.startsWith("Ошибка") || alignStatus.includes("Не сошлось") || alignStatus.includes("выше 10 мм") || alignStatus.includes("не вычислена") ? " is-alert" : ""}`} role="status">
          <span>{alignStatus}</span>
          {detectedTargets > 0 && <span>Кандидатов-сфер: {detectedTargets} · регистрации не выполнена</span>}
        </div>
      )}
      <details className="registration-tools-drawer">
        <summary>Точная настройка · реперы {manualPairs.length}/3 · полевые контроли заполнены {filledSurveyControlCount}</summary>
        <div className="registration-tools-content">
      {registrationResult && (
        <details className="registration-matrix-details">
          <summary style={{ cursor: "pointer" }}>Матрица оценки · {registrationResult.method === "open3d_fgr_point_to_plane_icp" ? "лимит " + registrationResult.iteration_limit + " итераций; фактическое число неизвестно" : registrationResult.iterations + " итераций"} · сошлось: {registrationResult.converged ? "да" : registrationResult.method === "open3d_fgr_point_to_plane_icp" ? "не сообщает" : "нет"} · поддержка: {registrationResult.inlier_count}/{registrationResult.source_sample_count} ({(registrationResult.inlier_fraction * 100).toFixed(1)}%) · точность не подтверждена</summary>
          <p className="hint">Матрица локальных координат двух станций.</p>
          <pre style={{ overflow: "auto", margin: "8px 0 2px", color: "#E2E8F0" }}>{JSON.stringify(registrationResult.matrix_4x4, null, 2)}</pre>
          {registrationResult.world_matrix_4x4 && <>
            <p className="hint">Мировые координаты подвижной станции → опорная станция (учтены смещения координат обеих станций).</p>
            <pre style={{ overflow: "auto", margin: "8px 0 2px", color: "#E2E8F0" }}>{JSON.stringify(registrationResult.world_matrix_4x4, null, 2)}</pre>
          </>}
          {!registrationResult.world_matrix_4x4 && <p className="warn-box" role="note">Мировая матрица недоступна: origin отсутствует или исходное преобразование RCP ещё не подтверждено.</p>}
        </details>
      )}

      <section className="registration-manual-tools" aria-label="Ручное совмещение по контрольным точкам">
        <strong style={{ color: "#F2F4F6" }}>Пары для подгонки: {manualPairs.length}/3 минимум · полевые контроли для проверки: {filledSurveyControlCount}/3 минимум</strong>
        <button type="button" onClick={() => setShowCombinedPreview((current) => !current)} disabled={!previewTransform || !sourceCloud || !targetCloud} aria-pressed={showCombinedPreview} style={{ background: showCombinedPreview ? "#fb923c" : "#252D35", color: showCombinedPreview ? "#171717" : "#E2E8F0", border: "1px solid #6b442d", borderRadius: 5, padding: "5px 9px", cursor: previewTransform ? "pointer" : "not-allowed", opacity: previewTransform ? 1 : 0.5 }}>{showCombinedPreview ? "Раздельный вид" : "Общая сцена"}</button>
        <button type="button" onClick={() => { setPickSide("source"); setPendingSourcePoint(null); setAlignStatus("Щёлкните по физическому реперу на подвижной станции A."); }} disabled={!sourceCloud || !targetCloud} aria-pressed={pickSide === "source"} style={{ background: pickSide === "source" ? "#FF812E" : "#252D35", color: pickSide === "source" ? "#10151B" : "#E2E8F0", border: "1px solid #475569", borderRadius: 5, padding: "5px 9px", cursor: "pointer" }}>Выбрать точку A</button>
        <button type="button" onClick={() => { setPickSide("target"); setAlignStatus(pendingSourcePoint ? "Щёлкните по тому же физическому реперу на опорной станции B." : "Сначала выберите точку A."); }} disabled={!pendingSourcePoint} aria-pressed={pickSide === "target"} style={{ background: pickSide === "target" ? "#FF812E" : "#252D35", color: pickSide === "target" ? "#10151B" : "#E2E8F0", border: "1px solid #475569", borderRadius: 5, padding: "5px 9px", cursor: pendingSourcePoint ? "pointer" : "not-allowed" }}>Выбрать точку B</button>
        <button type="button" onClick={resetManualPairs} disabled={manualPairs.length === 0 && !pendingSourcePoint && !manualResult} style={{ background: "#252D35", color: "#E2E8F0", border: "1px solid #475569", borderRadius: 5, padding: "5px 9px", cursor: "pointer" }}>Сбросить пары</button>
        <button type="button" onClick={() => void handleManualAlign()} disabled={isManualAligning || manualPairs.length < 3 || !sourceCloud || !targetCloud} style={{ background: "#FF812E", color: "#10151B", fontWeight: 700, border: 0, borderRadius: 5, padding: "5px 10px", cursor: "pointer", opacity: manualPairs.length < 3 || isManualAligning ? 0.55 : 1 }}>{isManualAligning ? "Расчёт…" : "Рассчитать по парам"}</button>
          <span style={{ color: "#97A3AE" }}>Выбирайте две отдельные станции с общей видимой зоной; точки должны соответствовать одному физическому реперу. Координаты локальные для каждой станции, м.</span>
        {manualPairs.map((pair, index) => <span key={index} style={{ background: "#20262D", borderRadius: 4, padding: "4px 6px" }}>{pair.label}: A ({pair.source_point.map((value) => value.toFixed(2)).join(", ")}) ↔ B ({pair.target_point.map((value) => value.toFixed(2)).join(", ")})</span>)}
        {manualResult && <details style={{ flexBasis: "100%" }}><summary style={{ cursor: "pointer" }}>Преобразования контрольных точек · не применены</summary><p className="hint">Локальные координаты подвижной и опорной станций.</p><pre style={{ overflow: "auto", margin: "6px 0", color: "#E2E8F0" }}>{JSON.stringify(manualResult.matrix_4x4, null, 2)}</pre>{manualResult.world_matrix_4x4 ? <><p className="hint">Мировые координаты подвижной станции → опорная станция (учтены смещения обеих станций).</p><pre style={{ overflow: "auto", margin: "6px 0", color: "#E2E8F0" }}>{JSON.stringify(manualResult.world_matrix_4x4, null, 2)}</pre></> : <p className="warn-box" role="note">Мировая матрица недоступна: начало координат одной из станций или исходное преобразование RCP ещё не подтверждено.</p>}</details>}
      </section>

      <details className="registration-controls-details">
        <summary style={{ cursor: "pointer", color: "#F2F4F6", fontWeight: 600 }}>
          Независимая проверка точности по полевым контролям{controlEvaluation ? ` · RMSE ${controlEvaluation.rmse_mm.toFixed(2)} мм` : ""}
        </summary>
        <p style={{ color: "#97A3AE", margin: "6px 0" }}>
          Введите не менее трёх физических точек в локальных координатах обеих станций (метры). Используйте отдельные геодезические контроли, которых нет среди пар подгонки. Оценка не меняет облака и не сохраняет введённые координаты.
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, margin: "8px 0" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            Импорт CSV
            <input type="file" accept=".csv,text/csv" aria-label="Импорт CSV контрольных точек" onChange={(event) => void handleImportSurveyControls(event)} />
          </label>
          <a href="/templates/registration-controls-template.csv" download style={{ color: "#FF9A58" }}>Скачать шаблон</a>
          <span style={{ color: "#97A3AE" }}>source = станция A, target = станция B; координаты в метрах.</span>
        </div>
        <label style={{ display: "flex", alignItems: "flex-start", gap: 7, margin: "7px 0" }}>
          <input type="checkbox" checked={controlsIndependent} onChange={(event) => { setControlsIndependent(event.target.checked); setControlEvaluation(null); }} />
          Я подтверждаю, что контрольные точки измерены независимо и не использовались для расчёта или уточнения этого преобразования.
        </label>
        <div style={{ display: "grid", gap: 6 }}>
          {surveyControls.map((control, controlIndex) => (
            <div key={controlIndex} style={{ display: "grid", gridTemplateColumns: "minmax(110px, 0.7fr) repeat(6, minmax(58px, 1fr)) auto", gap: 5, alignItems: "center" }}>
              <input aria-label={`Название контроля ${controlIndex + 1}`} value={control.label} onChange={(event) => { setControlEvaluation(null); setSurveyControls((current) => current.map((item, index) => index === controlIndex ? { ...item, label: event.target.value } : item)); }} placeholder={`Контроль ${controlIndex + 1}`} style={controlInputStyle} />
              {(["source", "target"] as const).flatMap((side) => (["X", "Y", "Z"] as const).map((axis, axisIndex) => (
                <input
                  key={`${side}-${axis}`}
                  aria-label={`Контроль ${controlIndex + 1} · ${side === "source" ? "станция A" : "станция B"} · ${axis}, м`}
                  type="number"
                  step="any"
                  value={control[side][axisIndex]}
                  onChange={(event) => { setControlEvaluation(null); setSurveyControls((current) => current.map((item, index) => index === controlIndex ? {
                    ...item,
                    [side]: item[side].map((value, coordinateIndex) => coordinateIndex === axisIndex ? event.target.value : value) as CoordinateInput,
                  } : item)); }}
                  placeholder={`${side === "source" ? "A" : "B"} ${axis}`}
                  style={controlInputStyle}
                />
              )))}
              {surveyControls.length > 3 && <button type="button" aria-label={`Удалить контроль ${controlIndex + 1}`} onClick={() => { setControlEvaluation(null); setSurveyControls((current) => current.filter((_, index) => index !== controlIndex)); }} style={controlButtonStyle}>Удалить</button>}
            </div>
          ))}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginTop: 7, alignItems: "center" }}>
          <button type="button" onClick={() => { setControlEvaluation(null); setSurveyControls((current) => [...current, emptySurveyControl(current.length)]); }} style={controlButtonStyle}>Добавить контроль</button>
          <button type="button" onClick={() => void handleEvaluateSurveyControls()} disabled={isEvaluatingControls || (!manualResult && !registrationResult) || !sourceCloud || !targetCloud || !controlsIndependent} style={{ ...controlButtonStyle, background: "#FF812E", color: "#10151B", borderColor: "#FF812E", fontWeight: 700, opacity: isEvaluatingControls || (!manualResult && !registrationResult) || !controlsIndependent ? 0.55 : 1 }}>
            {isEvaluatingControls ? "Проверка…" : "Проверить допуск 10 мм"}
          </button>
          <button type="button" onClick={resetSurveyControls} style={controlButtonStyle}>Очистить контроли</button>
          {controlEvaluation && <strong role="status" style={{ color: controlEvaluation.criterion_passed ? "#49C980" : "#F2B84B" }}>{controlEvaluation.criterion_passed ? "Критерий выполнен" : "Критерий не выполнен"} · p95 {controlEvaluation.p95_error_mm.toFixed(2)} мм</strong>}
        </div>
      </details>
        <div className="registration-sphere-tools">
          <label>Диаметр сферы, мм
            <input aria-label="Диаметр сферы в миллиметрах" type="number" min="0.1" step="0.1" value={targetDiameterMm} onChange={(event) => setTargetDiameterMm(event.target.value)} />
          </label>
          <button type="button" onClick={() => sourceCloud && handleDetectTargets(sourceCloud.id)} disabled={isDetecting || !sourceCloud || !targetDiameterMm}>
            {isDetecting ? "Поиск целей…" : "Найти сферы на станции A"}
          </button>
          {detectedTargets > 0 && <span>Найдено кандидатов: {detectedTargets} · регистрация не выполнена</span>}
        </div>
        </div>
      </details>

      {/* Side-by-side Viewports */}
      {showCombinedPreview && previewTransform && sourceCloud && targetCloud
        ? <RegistrationOverlayPreview key={`${sourceCloud.id}:${targetCloud.id}`} source={sourceCloud} target={targetCloud} sourceToTarget={previewTransform} />
        : <div className="registration-viewports">
        {/* Left Viewport: Station A */}
        <div className="registration-viewport registration-viewport-source">
          <div className="registration-view-label is-source">Подвижная станция A: {sourceCloud?.name || "не выбрана"}</div>
          {sourceCloud ? <Viewer3D
              cloud={sourceCloud}
              elements={[]}
              groupPositions={new Float32Array(0)}
              selectedElement={null}
              selectedElementPositions={new Float32Array(0)}
              selectedElementSections={emptySections}
              pointSize={2.0}
              colorMode="rgb"
              showPlane={false}
              section={null}
              pointPickModeActive={pickSide === "source"}
              onPointPicked={handleSourcePointPicked}
              onPointPickMiss={() => handlePointPickMiss("A")}
            /> : <EmptyStationViewport role="A" hasReadyStations={readyClouds.length > 0} />}
        </div>

        {/* Right Viewport: Station B */}
        <div className="registration-viewport registration-viewport-target">
          <div className="registration-view-label is-target">Опорная станция B: {targetCloud?.name || "не выбрана"}</div>
          {targetCloud ? <Viewer3D
              cloud={targetCloud}
              elements={[]}
              groupPositions={new Float32Array(0)}
              selectedElement={null}
              selectedElementPositions={new Float32Array(0)}
              selectedElementSections={emptySections}
              pointSize={2.0}
              colorMode="rgb"
              showPlane={false}
              section={null}
              pointPickModeActive={pickSide === "target"}
              onPointPicked={handleTargetPointPicked}
              onPointPickMiss={() => handlePointPickMiss("B")}
            /> : <EmptyStationViewport role="B" hasReadyStations={readyClouds.length > 1} />}
        </div>
      </div>}
        </main>

        <aside className="registration-inspector" aria-label="Параметры сшивки и качество">
          <div className="registration-panel-heading"><strong>Результат совмещения</strong><span className="registration-status-pill">{controlEvaluation ? controlEvaluation.criterion_passed ? "Порог ≤10 мм · временно" : "Контроль не пройден" : registrationResult || manualResult ? "Нужна проверка" : "Ожидает расчёта"}</span></div>
          <div className="registration-workflow-steps" aria-label="Порядок работы со станциями">
            <div className={`registration-workflow-step${sourceCloud && targetCloud && sourceCloud.id !== targetCloud.id ? " is-done" : " is-current"}`} aria-current={!sourceCloud || !targetCloud || sourceCloud.id === targetCloud.id ? "step" : undefined}>
              <strong>01</strong><span>Станции</span><small>{sourceCloud && targetCloud && sourceCloud.id !== targetCloud.id ? "A и B выбраны" : "Выберите A и B"}</small>
            </div>
            <div className={`registration-workflow-step${registrationResult || manualResult ? " is-result" : sourceCloud && targetCloud ? " is-current" : ""}`} aria-current={sourceCloud && targetCloud && !registrationResult && !manualResult ? "step" : undefined}>
              <strong>02</strong><span>Совмещение</span><small>{registrationResult || manualResult ? "Кандидат · нужна проверка" : "Рассчитать положение"}</small>
            </div>
            <div className={`registration-workflow-step${controlEvaluation ? " is-result" : registrationResult || manualResult ? " is-current" : ""}`} aria-current={(registrationResult || manualResult) && !controlEvaluation ? "step" : undefined}>
              <strong>03</strong><span>Контроль</span><small>{controlEvaluation ? "Проверено · порог временный" : "Нужны отдельные точки"}</small>
            </div>
          </div>
          <div className="registration-quality-heading">Показатели качества</div>
          <label className="registration-parameter-control">
            <span>Радиус соответствий FGR → ICP</span>
            <select value={maxCorrespondenceDistanceM} onChange={(event) => setMaxCorrespondenceDistanceM(Number(event.target.value))} disabled={isMatching}>
              <option value={0.15}>150 мм · узкий кандидат</option>
              <option value={0.25}>250 мм · средний поиск</option>
              <option value={0.5}>500 мм · широкий поиск</option>
            </select>
            <small>Радиус поиска, не допуск точности. Настройка влияет на подгонку и holdout.</small>
          </label>
          <div className="registration-metrics-grid" aria-label="Показатели совмещения">
            <div className="registration-metric"><span>{registrationResult?.method === "open3d_fgr_point_to_plane_icp" ? "Соответствия FGR → ICP" : "Соответствия ICP"}</span><strong>{registrationResult ? `${(registrationResult.inlier_fraction * 100).toFixed(1)}%` : "—"}</strong><small>{registrationResult?.method === "open3d_fgr_point_to_plane_icp" ? `поиск в радиусе ${(registrationResult.max_correspondence_distance_m * 1000).toFixed(0)} мм` : "поиск в радиусе 500 мм"}</small></div>
            <div className="registration-metric"><span>Невязка расчёта</span><strong>{registrationResult?.rmse_mm != null ? `${registrationResult.rmse_mm.toFixed(2)} мм` : manualResult ? `${manualResult.rmse_mm.toFixed(2)} мм` : "—"}</strong><small>не независимая точность</small></div>
            <div className="registration-metric"><span>Пары реперов</span><strong>{manualPairs.length} / 3</strong><small>минимум для ручного расчёта</small></div>
            <div className="registration-metric"><span>Полевые контроли</span><strong>{controlEvaluation ? `${controlEvaluation.independent_control_count} · ${controlEvaluation.criterion_passed ? "пройдены" : "не пройдены"}` : `${filledSurveyControlCount}/3 готовы`}</strong><small>отдельно от реперов совмещения</small></div>
          </div>
          {registrationResult?.method === "open3d_fgr_point_to_plane_icp" && <div className="registration-quality-note" role="status">
            <strong>Отложенная оценка (не участвовала в подгонке):</strong> {registrationResult.holdout.status === "evaluated"
              ? `A→B: RMSE ${registrationResult.holdout.rmse_mm != null ? `${registrationResult.holdout.rmse_mm.toFixed(2)} мм` : "не вычислена"}, покрытие ${(registrationResult.holdout.inlier_fraction != null ? registrationResult.holdout.inlier_fraction * 100 : 0).toFixed(1)}%; B→A: RMSE ${registrationResult.holdout.reverse?.rmse_mm != null ? `${registrationResult.holdout.reverse.rmse_mm.toFixed(2)} мм` : "нет данных"}, покрытие ${registrationResult.holdout.reverse?.inlier_fraction != null ? `${(registrationResult.holdout.reverse.inlier_fraction * 100).toFixed(1)}%` : "—"}. Это два направления на других строках тех же сканов, не независимый полевой контроль.`
              : "недоступна — в одном из облаков недостаточно точек для непересекающихся выборок."}
          </div>}
          <div className="registration-quality-note" role="note">Результат — предварительная матрица: станции не перемещаются и RCP не меняется. FGR → ICP отдельно оценивается по невязке и покрытию в обоих направлениях на отложенных строках, не использованных при подгонке; это всё ещё не независимый геодезический контроль. Open3D не сообщает сходимость итераций. Допуск проекта не задан; 10 мм — временный порог проверки.</div>
          <div className="registration-inspector-actions">
            <button type="button" onClick={() => void handleAutoMatchICP()} disabled={isMatching || !sourceCloud || !targetCloud || sourceCloud.id === targetCloud.id}>{isMatching ? "Идёт предварительная оценка…" : "Оценить совмещение ICP"}</button>
            <button type="button" onClick={() => void handleGlobalFgrMatch()} disabled={isMatching || !sourceCloud || !targetCloud || sourceCloud.id === targetCloud.id}>{isMatching ? "Идёт глобальный расчёт…" : "Глобальная регистрация FGR → ICP"}</button>
            <button type="button" onClick={() => void handleSaveStationPair()} disabled={isSavingStationPair || (!manualResult && !registrationResult) || !sourceCloud || !targetCloud}>{isSavingStationPair ? "Сохраняю…" : "Сохранить черновик пары станций"}</button>
            <button type="button" onClick={() => void handleExportStationPairToRecap()} disabled={isExportingStationPair || !projectId || !sourceCloud?.source_path || !targetCloud?.source_path || sourceCloud?.id === targetCloud?.id}>{isExportingStationPair ? "Создаю RCP…" : "Подготовить проект ReCap из 2 станций"}</button>
          </div>
          {stationRcpExport && <div className="registration-quality-note" role="status">
            <strong>RCP для станций:</strong> {stationRcpExport.sourceName} + {stationRcpExport.targetName}
            <br />Узлов в RCP: {stationRcpExport.rcpNodeCount} · RCS в комплекте: {stationRcpExport.linkedRcsCount} · внешних RCS: {stationRcpExport.externalRcsCount}
            <br /><code className="registration-rcp-path" title={stationRcpExport.rcpPath}>{stationRcpExport.rcpPath}</code>
            <br />{stationRcpExport.packageVerified
              ? "RCP проверен вместе с файлами RCS."
              : stationRcpExport.sourceFilesCopiedForDecap
                ? "Станции скопированы в локальный кэш этого компьютера. RCP не переносится отдельно; сохраните кэш и проверьте ссылки после переноса."
                : "RCP ссылается на исходные RCS и не является автономным комплектом."} Расчёт SCAN не записывается в RCP — зарегистрируйте станции в ReCap.
            {stationRcpExport.sourceCachePath && <><br />Кэш: <code className="registration-rcp-path">{stationRcpExport.sourceCachePath}</code></>}
          </div>}
          <div className="registration-inspector-note">Для точного результата сначала укажите общие реперы в блоке «Точная настройка», затем проверьте преобразование отдельными геодезическими точками.</div>
        </aside>
      </div>

      <details className="registration-links" aria-label="Пары станций">
        <summary className="registration-links-heading">
          <div>
            <strong>Пары станций</strong>
            <span>Текущая пара и сохранённые черновики</span>
          </div>
          <div className="registration-links-summary">
            <span>{readyClouds.length} станций</span>
            <span>{savedStationPairs.length} черновиков</span>
            <span>{totalReadyPoints.toLocaleString("ru-RU")} точек</span>
          </div>
        </summary>
        <div className="registration-links-table-wrap">
          <table className="registration-links-table">
            <thead><tr><th>Пара</th><th>Подвижная A</th><th>Опорная B</th><th>Оценка</th><th>RMSE</th><th>Статус</th></tr></thead>
            <tbody>
              {activeStationPair ? (() => {
                const error = registrationResult?.rmse_mm ?? manualResult?.rmse_mm ?? null;
                const state = currentPairState;
                return <tr className="is-current">
                  <td><span className="registration-link-index">A↔B</span></td>
                  <td>{activeStationPair.source.name}</td>
                  <td>{activeStationPair.target.name}</td>
                  <td>{registrationResult ? `${(registrationResult.inlier_fraction * 100).toFixed(1)}% ${registrationResult.method === "open3d_fgr_point_to_plane_icp" ? "FGR→ICP" : "ICP"}` : manualResult ? `${manualResult.pairs_count} репера` : "—"}</td>
                  <td>{error != null ? `${error.toFixed(2)} мм` : "—"}</td>
                  <td><span className={`registration-link-state is-${state}`} title={state === "provisional" ? "Порог 10 мм пока временный: допуск проекта не задан." : undefined}><i />{state === "provisional" ? "≤10 мм · временно" : state === "review" ? "Нужна проверка" : "Не оценено"}</span></td>
                </tr>;
              })() : <tr><td colSpan={6} className="registration-links-empty">Выберите две разные готовые станции, чтобы сформировать пару.</td></tr>}
              {savedStationPairs.map((pair) => <tr key={pair.id}>
                <td><span className="registration-link-index">A↔B</span></td>
                <td>{pair.source_station_name}</td>
                <td>{pair.target_station_name}</td>
                <td>{pair.method === "rigid_icp" ? "ICP" : pair.method === "manual_kabsch_icp" ? "Реперы + ICP" : "Реперы"}</td>
                <td>{pair.fit_rmse_mm != null ? `${pair.fit_rmse_mm.toFixed(2)} мм` : "—"}</td>
                <td><span className="registration-link-state is-review" title="Черновик регистрации станции; точность не подтверждена."><i />Черновик · не проверено</span></td>
              </tr>)}
              {!savedStationPairs.length && !activeStationPair && <tr><td colSpan={6} className="registration-links-empty">Сохранённых черновиков пар станций пока нет.</td></tr>}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
};

const EmptyStationViewport: React.FC<{ role: "A" | "B"; hasReadyStations: boolean }> = ({ role, hasReadyStations }) => (
  <div className="registration-empty-viewport">
    <div className="registration-empty-mark" aria-hidden="true">{role}</div>
    <strong>{hasReadyStations ? `Выберите станцию ${role}` : "Нет готовых станций"}</strong>
    <span>{hasReadyStations
      ? "Назначьте эту роль кнопкой A или B в списке слева."
      : "Импортируйте исходные сканы в разделе «Обработка» и дождитесь завершения подготовки."}</span>
  </div>
);

const controlInputStyle: React.CSSProperties = {
  minWidth: 0,
  width: "100%",
  background: "#0E1318",
  color: "#FFFFFF",
  border: "1px solid #475569",
  borderRadius: 4,
  padding: "5px 6px",
  fontSize: 11,
};

const controlButtonStyle: React.CSSProperties = {
  background: "#252D35",
  color: "#E2E8F0",
  border: "1px solid #475569",
  borderRadius: 5,
  padding: "5px 8px",
  cursor: "pointer",
  fontSize: 11,
};
