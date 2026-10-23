import { useEffect, useMemo, useRef, useState } from "react";
import { api, waitForCloud, waitForJob, type ColumnSurfaceTrackAnalysisResponse, type DerivedCloud } from "./api";
import ElementTable from "./components/ElementTable";
import ColumnTypesPanel from "./components/ColumnTypesPanel";
import ColumnSectionFitPanel from "./components/ColumnSectionFitPanel";
import ColumnAnnotationPanel from "./components/ColumnAnnotationPanel";
import SectionCanvas from "./components/SectionCanvas";
import Viewer3D from "./components/Viewer3D";
import { sliceElementPositions, toLocalElementPositions } from "./elementPointGeometry";
import { columnGroupLinePositions } from "./columnGroupGeometry";
import { buildOrientedBoxGeometry, orientedBoxDraft, type OrientedBoxDraft } from "./orientedBoxEditor";
import { classLabel, REVIEW_LABELS, statusLabel, type Cloud, type Element, type ModelInfo, type Project, type Section, type SectionResult } from "./types";

type Tab = "section" | "recognition" | "learning" | "export" | "registration" | "expert";

const TAB_LABELS: Record<Tab, string> = {
  section: "СЕЧЕНИЕ",
  recognition: "РАСПОЗНАВАНИЕ",
  learning: "ОБУЧЕНИЕ",
  export: "ЭКСПОРТ",
  registration: "Сшивка ReCap",
  expert: "Агент-Конструктор",
};

const STAT_LABELS: Record<string, string> = {
  wall_count: "стен",
  column_count: "колонн",
  slab_count: "плит",
  stair_count: "лестниц",
  opening_count: "проёмов",
  density_grade: "плотность",
  grid_res_m: "шаг сетки, м",
  level_candidates: "уровней",
};
const CLEANUP_LABELS: Record<string, string> = {
  voxel: "воксельное прореживание",
  statistical: "статистический (SOR)",
  radius: "радиусный (ROR)",
};
const CLASSES = [
  "wall",
  "column",
  "beam",
  "girder",
  "slab",
  "roof",
  "truss",
  "brace",
  "stair",
  "opening",
  "pipe",
  "duct",
  "equipment",
  "other",
  "unknown",
];

function detailText(error: any): string {
  const detail = error?.detail;
  if (detail?.detail) {
    if (typeof detail.detail === "string") return detail.detail;
    return detail.detail.summary || JSON.stringify(detail.detail);
  }
  if (typeof detail === "string") return detail;
  return error?.message || String(error);
}

function rcsDetail(error: any): any {
  const detail = error?.detail;
  if (detail?.detail && typeof detail.detail === "object" && detail.detail.steps) return detail.detail;
  return null;
}

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [clouds, setClouds] = useState<Cloud[]>([]);
  const [cloud, setCloud] = useState<Cloud | null>(null);
  const [tab, setTab] = useState<Tab>("recognition");
  const [error, setError] = useState<string | null>(null);
  const [rcsInfo, setRcsInfo] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [planScale, setPlanScale] = useState(100);
  const [drawingIssueMode, setDrawingIssueMode] = useState<"draft" | "final">("final");
  const [jobLabel, setJobLabel] = useState<string | null>(null);
  const [jobProgress, setJobProgress] = useState(0);
  const [importJobId, setImportJobId] = useState<string | null>(null);
  const [cancelingImport, setCancelingImport] = useState(false);
  const [importCancellationRequested, setImportCancellationRequested] = useState(false);

  const [newProject, setNewProject] = useState("");
  const [pathInput, setPathInput] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const [pointSize, setPointSize] = useState(2.2);
  const [colorMode, setColorMode] = useState<"rgb" | "height">("rgb");
  const [showPlane, setShowPlane] = useState(false);

  const [section, setSection] = useState<Section | null>(null);
  const [sectionForm, setSectionForm] = useState({
    kind: "horizontal" as "horizontal" | "vertical",
    axis: "x" as "x" | "y",
    position: 0,
    thickness: 0.05,
    gridRes: 0.02,
    regularize: true,
  });

  const [elements, setElements] = useState<Element[]>([]);
  const [derivedClouds, setDerivedClouds] = useState<DerivedCloud[]>([]);
  const [columnReferenceStates, setColumnReferenceStates] = useState<Record<string, string>>({});
  const [columnSurfaceAnalysis, setColumnSurfaceAnalysis] = useState<ColumnSurfaceTrackAnalysisResponse | null>(null);
  const [selectedElement, setSelectedElement] = useState<Element | null>(null);
  const [selectedColumnGroup, setSelectedColumnGroup] = useState<{ cloudId: string; ids: string[] } | null>(null);
  const groupGeometry = useMemo(() => columnGroupLinePositions(
    elements.filter((element) => element.cloud_id === cloud?.id),
    selectedColumnGroup?.cloudId === cloud?.id ? selectedColumnGroup?.ids ?? [] : [],
    cloud?.origin ?? undefined,
  ), [elements, selectedColumnGroup, cloud?.id, cloud?.origin]);
  const [mergeTarget, setMergeTarget] = useState("");
  const [splitAxis, setSplitAxis] = useState<"x" | "y" | "z">("x");
  const [splitValue, setSplitValue] = useState(0);
  const [similar, setSimilar] = useState<any[]>([]);
  const [reviewHistory, setReviewHistory] = useState<any[]>([]);
  const [boundaryDraft, setBoundaryDraft] = useState<OrientedBoxDraft>(() => orientedBoxDraft(null));
  const [boundaryError, setBoundaryError] = useState<string | null>(null);
  const [selectedElementPoints, setSelectedElementPoints] = useState<number[][]>([]);
  const [elementPointsLoading, setElementPointsLoading] = useState(false);
  const selectedElementPositions = useMemo(
    () => toLocalElementPositions(selectedElementPoints, cloud?.origin),
    [selectedElementPoints, cloud?.origin],
  );
  const selectedElementSections = useMemo(
    () => selectedElement
      ? sliceElementPositions(selectedElementPoints, selectedElement.bbox, cloud?.origin)
      : [new Float32Array(), new Float32Array(), new Float32Array()] as [Float32Array, Float32Array, Float32Array],
    [selectedElement?.id, selectedElementPoints, selectedElement?.bbox, cloud?.origin],
  );

  useEffect(() => {
    setBoundaryDraft(orientedBoxDraft(selectedElement?.geometry));
    setBoundaryError(null);
  }, [selectedElement?.id, selectedElement?.geometry]);

  useEffect(() => {
    setColumnSurfaceAnalysis(null);
  }, [cloud?.id, selectedElement?.id]);

  const [learning, setLearning] = useState<any>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [trainResult, setTrainResult] = useState<ModelInfo | null>(null);
  const [training, setTraining] = useState(false);

  const recognition = useMemo(() => cloud?.metadata?.recognition ?? null, [cloud]);

  useEffect(() => {
    let current = true;
    if (!cloud) {
      setDerivedClouds([]);
      return;
    }
    api.derivedClouds(cloud.id)
      .then((items) => { if (current) setDerivedClouds(items); })
      .catch(() => { if (current) setDerivedClouds([]); });
    return () => { current = false; };
  }, [cloud?.id]);

  useEffect(() => {
    if (!selectedElement) {
      setReviewHistory([]);
      return;
    }
    let current = true;
    api.elementHistory(selectedElement.id)
      .then((history) => { if (current) setReviewHistory(history); })
      .catch((err) => { if (current) setError(detailText(err)); });
    return () => { current = false; };
  }, [selectedElement?.id]);

  useEffect(() => {
    if (!selectedElement) {
      setSelectedElementPoints([]);
      setElementPointsLoading(false);
      return;
    }
    let current = true;
    setElementPointsLoading(true);
    api.elementPoints(selectedElement.id)
      .then((result) => { if (current) setSelectedElementPoints(result.points); })
      .catch((err) => { if (current) setError(detailText(err)); })
      .finally(() => { if (current) setElementPointsLoading(false); });
    return () => { current = false; };
  }, [selectedElement?.id, selectedElement?.bbox]);

  const refreshProjects = async () => {
    const list = await api.listProjects();
    const workshop = list.find((p) => p.id === "workshop_project");
    const sorted = workshop ? [workshop, ...list.filter((p) => p.id !== "workshop_project")] : list;
    setProjects(sorted);
    setProject((current) => {
      if (current) {
        const found = sorted.find((p) => p.id === current.id);
        if (found && !found.name.toLowerCase().includes("demo")) return found;
      }
      return workshop ?? (sorted.length > 0 ? sorted[0] : null);
    });
    return sorted;
  };

  useEffect(() => {
    refreshProjects().catch((err) => setError(detailText(err)));
    api.health().catch(() =>
      setError("Локальный API не запущен. Запустите его командой: python backend/run.py"),
    );
  }, []);

  useEffect(() => {
    if (!project) {
      setClouds([]);
      setCloud(null);
      return;
    }
    api
      .listClouds(project.id)
      .then((list) => {
        setClouds(list);
        if (!cloud || cloud.project_id !== project.id) {
          setCloud(list[0] ?? null);
        }
      })
      .catch((err) => setError(detailText(err)));
    api.modelStatus(project.id).then(setLearning).catch(() => setLearning(null));
    api.models().then(setModels).catch(() => setModels([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  useEffect(() => {
    if (!cloud) {
      setElements([]);
      setSection(null);
      return;
    }
    const origin = cloud.origin || [0, 0, 0];
    const bmin = cloud.bbox_min || [0, 0, 0];
    const bmax = cloud.bbox_max || [1, 1, 1];
    if (sectionForm.kind === "horizontal") {
      setSectionForm((form) => ({ ...form, position: (bmin[2] + bmax[2]) / 2 }));
    } else {
      const index = sectionForm.axis === "x" ? 0 : 1;
      setSectionForm((form) => ({ ...form, position: (bmin[index] + bmax[index]) / 2 }));
    }
    setSection(null);
    setSelectedElement(null);
    setSelectedColumnGroup(null);
    if (cloud.status === "ready") {
      api.elements(cloud.id).then(setElements).catch(() => setElements([]));
    } else {
      setElements([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cloud?.id, cloud?.status, cloud?.updated_at]);

  useEffect(() => {
    if (!cloud || cloud.status !== "ready"
        || !elements.some((element) => element.cloud_id === cloud.id && element.class_name === "column")) {
      setColumnReferenceStates({});
      return;
    }
    let active = true;
    setColumnReferenceStates({});
    api.columnAnnotations(cloud.id).then((dataset) => {
      if (!active) return;
      setColumnReferenceStates(Object.fromEntries(dataset.annotations.map((annotation) => [annotation.element_id, annotation.state])));
    }).catch(() => {
      if (active) setColumnReferenceStates({});
    });
    return () => { active = false; };
  }, [cloud?.id, cloud?.status, cloud?.updated_at, elements]);

  const trackCloud = async (incoming: Cloud) => {
    setBusy(true);
    setImportJobId(incoming.import_job_id ?? null);
    setCancelingImport(false);
    setImportCancellationRequested(false);
    setJobLabel("Обработка облака точек");
    setJobProgress(0.05);
    let cancelled = false;
    try {
      const ready = await waitForCloud(incoming.id, (update) => {
        setCloud(update);
        setJobProgress(update.status === "processing" ? 0.4 : 0.8);
        setClouds((list) => list.map((item) => (item.id === update.id ? update : item)));
      });
      setClouds((list) => list.map((item) => (item.id === ready.id ? ready : item)));
      setCloud(ready);
      if (ready.status === "failed") setError(ready.error || "не удалось обработать облако точек");
      if (ready.status === "cancelled") {
        cancelled = true;
        setJobLabel("Импорт облака отменён");
        setJobProgress(0);
      }
      await refreshProjects();
    } catch (err) {
      setError(detailText(err));
    } finally {
      setBusy(false);
      setImportJobId(null);
      setCancelingImport(false);
      setImportCancellationRequested(false);
      if (!cancelled) {
        setJobLabel(null);
        setJobProgress(0);
      }
    }
  };

  const cancelImport = async () => {
    if (!importJobId || cancelingImport || importCancellationRequested) return;
    setCancelingImport(true);
    try {
      const result = await api.cancelJob(importJobId);
      if (result.cancel_requested) setImportCancellationRequested(true);
      else setError("Импорт уже завершился; отменять нечего.");
    } catch (err) {
      setError(detailText(err));
    } finally {
      setCancelingImport(false);
    }
  };

  const resumeImport = async () => {
    if (!cloud || busy || !["failed", "cancelled"].includes(cloud.status)) return;
    setError(null);
    try {
      const incoming = await api.resumeImport(cloud.id);
      setCloud(incoming);
      setClouds((list) => list.map((item) => (item.id === incoming.id ? incoming : item)));
      await trackCloud(incoming);
    } catch (err) {
      setError(detailText(err));
    }
  };

  const handleImport = async () => {
    if (!project || !pathInput.trim()) return;
    setError(null);
    setRcsInfo(null);
    try {
      const incoming = await api.importPath(project.id, pathInput.trim());
      setClouds((list) => [incoming, ...list]);
      setCloud(incoming);
      setPathInput("");
      await trackCloud(incoming);
    } catch (err: any) {
      setError(detailText(err));
      setRcsInfo(rcsDetail(err));
    }
  };

  const handleUpload = async (file: File) => {
    if (!project) return;
    setError(null);
    setRcsInfo(null);
    setBusy(true);
    try {
      const incoming = await api.uploadCloud(project.id, file);
      setClouds((list) => [incoming, ...list]);
      setCloud(incoming);
      await trackCloud(incoming);
    } catch (err: any) {
      setError(detailText(err));
      setRcsInfo(rcsDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const handleDemo = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.demo();
      await refreshProjects();
      setProject(result.project);
      setClouds([result.cloud]);
      setCloud(result.cloud);
      await trackCloud(result.cloud);
    } catch (err) {
      setError(detailText(err));
    } finally {
      setBusy(false);
    }
  };

  const createProject = async () => {
    if (!newProject.trim()) return;
    try {
      const created = await api.createProject(newProject.trim());
      setNewProject("");
      await refreshProjects();
      setProject(created);
    } catch (err) {
      setError(detailText(err));
    }
  };

  const runRecognition = async () => {
    if (!cloud) return;
    setError(null);
    setBusy(true);
    setTab("recognition");
    setJobLabel("Распознавание конструкций");
    setJobProgress(0.02);
    try {
      const job = await api.recognize(cloud.id);
      const finished = await waitForJob(job.id, (update) => {
        setJobProgress(update.progress || 0.05);
        setJobLabel(`Распознавание: ${update.message || statusLabel(update.status)}`);
      });
      if (finished.status === "failed") {
        setError(finished.error || "распознавание завершилось ошибкой");
      } else {
        const refreshed = await api.getCloud(cloud.id);
        setCloud(refreshed);
        setClouds((list) => list.map((item) => (item.id === refreshed.id ? refreshed : item)));
        setElements(await api.elements(cloud.id));
      }
    } catch (err) {
      setError(detailText(err));
    } finally {
      setBusy(false);
      setJobLabel(null);
      setJobProgress(0);
    }
  };

  const runCleanup = async (payload: Record<string, unknown>) => {
    if (!cloud) return;
    setError(null);
    setBusy(true);
    setJobLabel("Очистка облака");
    setJobProgress(0.02);
    try {
      const job = await api.runCleanup(cloud.id, payload);
      const finished = await waitForJob(job.id, (update) => {
        setJobProgress(update.progress || 0.05);
        setJobLabel(`Очистка: ${update.message || statusLabel(update.status)}`);
      });
      if (finished.status === "failed") {
        setError(finished.error || "очистка завершилась ошибкой");
      } else {
        setDerivedClouds(await api.derivedClouds(cloud.id));
      }
    } catch (err) {
      setError(detailText(err));
    } finally {
      setBusy(false);
      setJobLabel(null);
      setJobProgress(0);
    }
  };

  const createSection = async () => {
    if (!cloud) return;
    setError(null);
    setBusy(true);
    setJobLabel("Построение измеренного сечения");
    setJobProgress(0.4);
    try {
      const created = await api.createSection(cloud.id, {
        kind: sectionForm.kind,
        position: sectionForm.position,
        axis: sectionForm.kind === "vertical" ? sectionForm.axis : null,
        thickness: sectionForm.thickness,
        grid_res: sectionForm.gridRes,
        regularize: sectionForm.regularize,
      });
      setSection(created);
      setTab("section");
    } catch (err) {
      setError(detailText(err));
    } finally {
      setBusy(false);
      setJobLabel(null);
      setJobProgress(0);
    }
  };

  const download = async (fn: () => Promise<void>, label: string) => {
    setError(null);
    setBusy(true);
    setJobLabel(label);
    try {
      await fn();
    } catch (err: any) {
      setError(detailText(err));
      setRcsInfo(rcsDetail(err));
    } finally {
      setBusy(false);
      setJobLabel(null);
    }
  };

  const feedback = async (elementId: string, payload: Record<string, unknown>) => {
    setBusy(true);
    try {
      await api.feedback(elementId, payload);
      if (cloud) {
        const refreshed = await api.elements(cloud.id);
        setElements(refreshed);
        if (selectedElement?.id === elementId) {
          setSelectedElement(refreshed.find((item) => item.id === elementId) ?? null);
        }
      }
      if (selectedElement?.id === elementId) setReviewHistory(await api.elementHistory(elementId));
      if (project) {
        setLearning(await api.modelStatus(project.id));
      }
      setSimilar([]);
    } catch (err) {
      setError(detailText(err));
    } finally {
      setBusy(false);
    }
  };

  const undoReviewAction = async (feedbackId: string) => {
    if (!selectedElement || !cloud) return;
    setBusy(true);
    try {
      await api.undoFeedback(selectedElement.id, feedbackId);
      const refreshed = await api.elements(cloud.id);
      setElements(refreshed);
      setSelectedElement(refreshed.find((item) => item.id === selectedElement.id) ?? null);
      setReviewHistory(await api.elementHistory(selectedElement.id));
      if (project) setLearning(await api.modelStatus(project.id));
      setSimilar([]);
    } catch (err) {
      setError(detailText(err));
    } finally {
      setBusy(false);
    }
  };

  const doMerge = async () => {
    if (!selectedElement || !mergeTarget) return;
    await feedback(selectedElement.id, {
      action: "merge",
      other_element_id: mergeTarget,
      note: "merged in engineer editor",
    });
    setMergeTarget("");
  };

  const doSplit = async () => {
    if (!selectedElement) return;
    await feedback(selectedElement.id, {
      action: "split",
      axis: splitAxis,
      value: splitValue,
      note: "split in engineer editor",
    });
  };

  const saveBoundary = async () => {
    if (!selectedElement || selectedElement.geometry?.kind !== "oriented_box") return;
    let geometry;
    try {
      geometry = buildOrientedBoxGeometry(boundaryDraft);
    } catch (err) {
      setBoundaryError(detailText(err));
      return;
    }
    setBoundaryError(null);
    await feedback(selectedElement.id, {
      action: "adjust_boundary",
      geometry,
      note: "Ручная правка границ в интерфейсе проверки",
    });
  };

  const applySectionHypothesis = (hypothesis: {
    corners_world_m: [number, number][];
    side_lengths_m: number[];
  }) => {
    const [p0, p1, p2, p3] = hypothesis.corners_world_m;
    if (!p0 || !p1 || !p2 || !p3) return;
    const centerX = (p0[0] + p1[0] + p2[0] + p3[0]) / 4;
    const centerY = (p0[1] + p1[1] + p2[1] + p3[1]) / 4;
    const edgeX = p1[0] - p0[0];
    const edgeY = p1[1] - p0[1];
    setBoundaryDraft((draft) => ({
      ...draft,
      centerX: String(centerX),
      centerY: String(centerY),
      length: String(Math.hypot(edgeX, edgeY)),
      thickness: String(Math.hypot(p3[0] - p0[0], p3[1] - p0[1])),
      rotationDegrees: String(Math.atan2(edgeY, edgeX) * 180 / Math.PI),
    }));
    setBoundaryError(null);
  };

  const train = async () => {
    if (!project) return;
    setTraining(true);
    setError(null);
    try {
      const model = await api.train(project.id, {
        name: "geometric-knn",
        test_fraction: 0.25,
        min_test_samples: 6,
        min_macro_f1: 0.6,
        notes: "trained from engineer-reviewed examples",
      });
      setTrainResult(model);
      setModels(await api.models());
      setLearning(await api.modelStatus(project.id));
    } catch (err) {
      setError(detailText(err));
    } finally {
      setTraining(false);
    }
  };

  const activateModel = async (model: ModelInfo) => {
    setError(null);
    try {
      await api.activateModel(model.id);
      setModels(await api.models());
      setLearning(await api.modelStatus(project!.id));
    } catch (err) {
      setError(detailText(err));
    }
  };

  const selectedBBox = selectedElement?.bbox;
  const splitDefault = useMemo(() => {
    if (!selectedBBox) return 0;
    const index = splitAxis === "x" ? 0 : splitAxis === "y" ? 1 : 2;
    return (selectedBBox.min[index] + selectedBBox.max[index]) / 2;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedElement?.id, splitAxis]);

  useEffect(() => {
    setSplitValue(splitDefault);
  }, [splitDefault]);

  const sectionResult: SectionResult | null = section?.result || null;
  const cloudBBox = cloud?.bbox_min && cloud?.bbox_max ? [...cloud.bbox_min, ...cloud.bbox_max] : null;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">S2B</span>
          <div>
            <strong>Intelligent Scan-to-BIM</strong>
            <small>рабочее место инженера по облакам точек</small>
          </div>
        </div>
        <div className="topbar-right">
          <span className="pill">локальный API · v1</span>
          <span className="pill muted">Autodesk не требуется</span>
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <section className="panel">
            <div className="panel-title">
              <span>Проекты</span>
              <span className="counter">{projects.length}</span>
            </div>
            <div className="project-list">
              {projects.map((item) => (
                <button
                  key={item.id}
                  className={project?.id === item.id ? "project active" : "project"}
                  onClick={() => {
                    setProject(item);
                    setCloud(null);
                    setSection(null);
                    setElements([]);
                  }}
                >
                  <span>{item.name}</span>
                  <small>облаков: {item.cloud_count ?? 0}</small>
                </button>
              ))}
              {!projects.length && (
                <p className="hint">Проектов пока нет. Создайте проект или загрузите демо-комнату.</p>
              )}
            </div>
            <div className="row">
              <input
                value={newProject}
                placeholder="Название нового проекта"
                onChange={(event) => setNewProject(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && createProject()}
              />
              <button onClick={createProject} disabled={!newProject.trim()}>
                Создать
              </button>
            </div>
            <button className="demo-button" onClick={handleDemo} disabled={busy}>
              Загрузить демо-комнату (6 × 4 × 3 м)
            </button>
          </section>

          <section className="panel">
            <div className="panel-title">
              <span>Облака точек</span>
              <span className="counter">{clouds.length}</span>
            </div>
            <div className="cloud-list">
              {clouds.map((item) => (
                <button
                  key={item.id}
                  className={cloud?.id === item.id ? "cloud active" : "cloud"}
                  onClick={() => setCloud(item)}
                  title={item.source_path}
                >
                  <span className="cloud-name">{item.name}</span>
                  <span className={`badge-status ${item.status}`}>{statusLabel(item.status)}</span>
                  <small>
                    {item.point_count.toLocaleString()} точек · {item.source_format.toUpperCase()}
                  </small>
                </button>
              ))}
              {!clouds.length && (
                <p className="hint">Поддерживаются E57, LAS/LAZ, PLY, PCD, PTS, XYZ, RCS.</p>
              )}
            </div>
            <div className="import-block">
              <label className="field-label">
                Импорт по локальному пути (большой скан остаётся на месте)
              </label>
              <div className="row">
                <input
                  value={pathInput}
                  placeholder="C:\\scans\\building.e57"
                  onChange={(event) => setPathInput(event.target.value)}
                  onKeyDown={(event) => event.key === "Enter" && handleImport()}
                  disabled={!project || busy}
                />
                <button onClick={handleImport} disabled={!project || !pathInput.trim() || busy}>
                  Импортировать
                </button>
              </div>
              <input
                ref={fileRef}
                type="file"
                hidden
                accept=".e57,.las,.laz,.ply,.pcd,.pts,.xyz,.txt,.csv,.rcs,.rcp"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) handleUpload(file);
                  event.target.value = "";
                }}
              />
              <button className="ghost" onClick={() => fileRef.current?.click()} disabled={!project || busy}>
                Загрузить копию файла…
              </button>
              <p className="hint">
                Исходные файлы не изменяются. RCS/RCP читаются через установленную библиотеку
                Autodesk ReCap; если её нет — конвертируйте файл в E57/LAS один раз.
              </p>
            </div>
          </section>

          {cloud && (
            <section className="panel meta-panel">
              <div className="panel-title">
                <span>Облако</span>
                <span className={`badge-status ${cloud.status}`}>{statusLabel(cloud.status)}</span>
              </div>
              <dl>
                <dt>точек</dt>
                <dd>{cloud.point_count.toLocaleString()}</dd>
                <dt>в превью</dt>
                <dd>{cloud.preview_count.toLocaleString()}</dd>
                <dt>формат</dt>
                <dd>{cloud.source_format.toUpperCase()}</dd>
                <dt>габарит</dt>
                <dd>
                  {cloud.bbox_min && cloud.bbox_max
                    ? `${(cloud.bbox_max[0] - cloud.bbox_min[0]).toFixed(2)} × ${(
                        cloud.bbox_max[1] - cloud.bbox_min[1]
                      ).toFixed(2)} × ${(cloud.bbox_max[2] - cloud.bbox_min[2]).toFixed(2)} m`
                    : "—"}
                </dd>
              </dl>
              {cloud.warning && <p className="warn-box">{cloud.warning}</p>}
              {cloud.error && <p className="error-box">{cloud.error}</p>}
              {["failed", "cancelled"].includes(cloud.status) && (
                <div className="resume-import">
                  <p>Импорт можно продолжить. Сохранённая контрольная точка будет проверена перед повторной обработкой.</p>
                  <button className="primary wide" onClick={resumeImport} disabled={busy}>
                    Возобновить импорт
                  </button>
                </div>
              )}
            </section>
          )}
        </aside>

        <main className="main">
          <section className="viewer-panel">
            <div className="viewer-toolbar">
              <div className="segmented">
                <button className={colorMode === "rgb" ? "active" : ""} onClick={() => setColorMode("rgb")}>
                  RGB
                </button>
                <button className={colorMode === "height" ? "active" : ""} onClick={() => setColorMode("height")}>
                  Высота
                </button>
              </div>
              <label className="slider-label">
                размер точек
                <input
                  type="range"
                  min={0.5}
                  max={8}
                  step={0.1}
                  value={pointSize}
                  onChange={(event) => setPointSize(Number(event.target.value))}
                />
              </label>
              <label className="check">
                <input type="checkbox" checked={showPlane} onChange={(event) => setShowPlane(event.target.checked)} />
                плоскость сечения
              </label>
              <span className="spacer" />
              <span className="hint">ЛКМ — вращение · колесо — масштаб · ПКМ — панорама</span>
            </div>
            <Viewer3D
              cloud={cloud}
              elements={elements}
              groupPositions={groupGeometry.positions}
              selectedElement={selectedElement}
              selectedElementPositions={selectedElementPositions}
              selectedElementSections={selectedElementSections}
              pointSize={pointSize}
              colorMode={colorMode}
              showPlane={showPlane}
              section={
                cloud
                  ? {
                      kind: sectionForm.kind,
                      axis: sectionForm.axis,
                      position: sectionForm.position,
                    }
                  : null
              }
            />
          </section>

          <aside className="right-panel">
            <div className="tabs">
              {(["section", "recognition", "learning", "export", "registration", "expert"] as Tab[]).map((name) => (
                <button key={name} className={tab === name ? "tab active" : "tab"} onClick={() => setTab(name)}>
                  {TAB_LABELS[name]}
                </button>
              ))}
            </div>

            {jobLabel && (
              <div className="job-banner">
                <div className="job-banner-head">
                  <span>{jobLabel}</span>
                  {importJobId && cloud?.status === "processing" && (
                    <button className="job-cancel" onClick={cancelImport}
                      disabled={cancelingImport || importCancellationRequested}>
                      {importCancellationRequested ? "Отмена…" : cancelingImport ? "Запрос…" : "Отменить"}
                    </button>
                  )}
                </div>
                <div className="progress">
                  <div style={{ width: `${Math.round(jobProgress * 100)}%` }} />
                </div>
              </div>
            )}

            {error && (
              <div className="alert error">
                <div>{error}</div>
                <button className="close" onClick={() => setError(null)}>
                  ×
                </button>
              </div>
            )}
            {rcsInfo && (
              <div className="alert info">
                <strong>RCS/RCP: нужна конвертация или ReCap</strong>
                <p>{rcsInfo.summary}</p>
                <ol>
                  {(rcsInfo.steps || []).map((step: string) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
                <small>Статус: формат не реализован нативно, только через ReCap или конвертацию.</small>
              </div>
            )}

            {tab === "section" && (
              <div className="tab-body">
                {!cloud && <div className="empty-note">Сначала выберите готовое облако точек.</div>}
                {cloud && (
                  <>
                    <div className="controls">
                      <div className="segmented full">
                        <button
                          className={sectionForm.kind === "horizontal" ? "active" : ""}
                          onClick={() => {
                            const min = cloud.bbox_min?.[2] ?? 0;
                            const max = cloud.bbox_max?.[2] ?? 1;
                            setSectionForm({ ...sectionForm, kind: "horizontal", position: (min + max) / 2 });
                          }}
                        >
                          Горизонтальный план
                        </button>
                        <button
                          className={sectionForm.kind === "vertical" ? "active" : ""}
                          onClick={() => {
                            const index = sectionForm.axis === "x" ? 0 : 1;
                            const min = cloud.bbox_min?.[index] ?? 0;
                            const max = cloud.bbox_max?.[index] ?? 1;
                            setSectionForm({ ...sectionForm, kind: "vertical", position: (min + max) / 2 });
                          }}
                        >
                          Вертикальный разрез
                        </button>
                      </div>
                      {sectionForm.kind === "vertical" && (
                        <div className="segmented full">
                          <button
                            className={sectionForm.axis === "x" ? "active" : ""}
                            onClick={() => {
                              const min = cloud.bbox_min?.[0] ?? 0;
                              const max = cloud.bbox_max?.[0] ?? 1;
                              setSectionForm({ ...sectionForm, axis: "x", position: (min + max) / 2 });
                            }}
                          >
                            разрез по X (вид Y/Z)
                          </button>
                          <button
                            className={sectionForm.axis === "y" ? "active" : ""}
                            onClick={() => {
                              const min = cloud.bbox_min?.[1] ?? 0;
                              const max = cloud.bbox_max?.[1] ?? 1;
                              setSectionForm({ ...sectionForm, axis: "y", position: (min + max) / 2 });
                            }}
                          >
                            разрез по Y (вид X/Z)
                          </button>
                        </div>
                      )}
                      <label className="field-label">
                        положение ({sectionForm.kind === "horizontal" ? "Z" : sectionForm.axis.toUpperCase()}) —
                        {" "}
                        {sectionForm.position.toFixed(3)} м
                      </label>
                      <input
                        type="range"
                        min={
                          sectionForm.kind === "horizontal"
                            ? cloud.bbox_min?.[2] ?? 0
                            : cloud.bbox_min?.[sectionForm.axis === "x" ? 0 : 1] ?? 0
                        }
                        max={
                          sectionForm.kind === "horizontal"
                            ? cloud.bbox_max?.[2] ?? 1
                            : cloud.bbox_max?.[sectionForm.axis === "x" ? 0 : 1] ?? 1
                        }
                        step={0.01}
                        value={sectionForm.position}
                        onChange={(event) => setSectionForm({ ...sectionForm, position: Number(event.target.value) })}
                      />
                      <div className="grid-2">
                        <label>
                          <span className="field-label">толщина сечения (м)</span>
                          <input
                            type="number"
                            min={0.005}
                            step={0.005}
                            value={sectionForm.thickness}
                            onChange={(event) =>
                              setSectionForm({ ...sectionForm, thickness: Number(event.target.value) })
                            }
                          />
                        </label>
                        <label>
                          <span className="field-label">шаг растра (м)</span>
                          <select
                            value={sectionForm.gridRes}
                            onChange={(event) =>
                              setSectionForm({ ...sectionForm, gridRes: Number(event.target.value) })
                            }
                          >
                            <option value={0.01}>0.010</option>
                            <option value={0.02}>0.020</option>
                            <option value={0.05}>0.050</option>
                            <option value={0.1}>0.100</option>
                          </select>
                        </label>
                      </div>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={sectionForm.regularize}
                          onChange={(event) =>
                            setSectionForm({ ...sectionForm, regularize: event.target.checked })
                          }
                        />
                        ортогональная регуляризация
                      </label>
                      <button className="primary wide" onClick={createSection} disabled={busy || cloud.status !== "ready"}>
                        Построить измеренное сечение
                      </button>
                    </div>

                    {sectionResult && (
                      <>
                        <div className="section-summary">
                          <div>
                            <b>{sectionResult.polygons.length}</b>
                            <small>контуров</small>
                          </div>
                          <div>
                            <b>{sectionResult.point_count.toLocaleString()}</b>
                            <small>точек в слое</small>
                          </div>
                          <div>
                            <b>{sectionResult.total_area_m2.toFixed(2)}</b>
                            <small>площадь, м²</small>
                          </div>
                        </div>
                        <div className="section-view">
                          <SectionCanvas result={sectionResult} />
                        </div>
                        {sectionResult.warnings.length > 0 && (
                          <ul className="warnings">
                            {sectionResult.warnings.map((warning) => (
                              <li key={warning}>{warning}</li>
                            ))}
                          </ul>
                        )}
                        <div className="button-row">
                          {(["dxf", "pdf", "json"] as const).map((format) => (
                            <button
                              key={format}
                              onClick={() =>
                                download(
                                  () => api.exportSection(section!.id, format),
                                  `Экспорт ${format.toUpperCase()}`,
                                )
                              }
                              disabled={busy}
                            >
                              Экспорт {format.toUpperCase()}
                            </button>
                          ))}
                        </div>
                        <p className="hint">
                          В DXF передаются редактируемые полилинии, слои, габаритные размеры,
                          высотные отметки и лист A3. Для DWG нужен AutoCAD или лицензированный конвертер.
                        </p>
                      </>
                    )}
                  </>
                )}
              </div>
            )}

            {tab === "recognition" && (
              <div className="tab-body">
                <div className="button-row">
                  <button className="primary" onClick={runRecognition} disabled={!cloud || busy || cloud.status !== "ready"}>
                    Запустить геометрическое распознавание
                  </button>
                </div>
                <p className="hint">
                  Геометрический модуль формирует непроверенные кандидаты стен, колонн,
                  балок, подкрановых балок, ферм, связей, лестничных маршей и проёмов по
                  данным облака. Для каждого сохраняется evidence исходных точек; роль,
                  сечение, опоры, ступени и тип проёма требуют ручной проверки.
                  Неподдержанные классы не дорисовываются.
                </p>
                {recognition?.warnings && (
                  <ul className="warnings">
                    {recognition.warnings.map((warning: string) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                )}
                {recognition?.levels?.length > 0 && (
                  <div className="levels">
                    <span className="field-label">найденные уровни</span>
                    {recognition.levels.map((level: any) => (
                      <button
                        key={level.z}
                        className="level-chip"
                        onClick={() => {
                          setSectionForm({ ...sectionForm, kind: "horizontal", position: level.z });
                          setTab("section");
                        }}
                      >
                        {level.z.toFixed(3)} м
                      </button>
                    ))}
                  </div>
                )}
                {recognition?.stats && (
                  <div className="stats-line">
                    {Object.entries(recognition.stats)
                      .filter(([key]) => ["wall_count", "column_count", "slab_count", "stair_count", "opening_count", "density_grade", "grid_res_m", "level_candidates"].includes(key))
                      .map(([key, value]) => (
                        <span key={key}>
                          {STAT_LABELS[key] || key}: <b>{String(value)}</b>
                        </span>
                      ))}
                  </div>
                )}
                {cloud && <ColumnTypesPanel key={cloud.id} cloudId={cloud.id} elements={elements}
                  onSelectGroup={(ids) => setSelectedColumnGroup({ cloudId: cloud.id, ids })}
                  busy={busy} selected={selectedElement} onSelect={(element) => {
                    setSelectedElement(element);
                    setSimilar([]);
                  }} />}
                {selectedColumnGroup?.cloudId === cloud?.id && selectedColumnGroup && <p className="hint" role="status">
                  Контуры группы в 3D: {groupGeometry.rendered_ids.length}.
                  {groupGeometry.unavailable_ids.length > 0 && ` Недоступны в этом облаке или нет полной геометрии: ${groupGeometry.unavailable_ids.length}.`}
                  <button type="button" onClick={() => setSelectedColumnGroup(null)}>Снять выделение группы</button>
                </p>}
                <ElementTable
                  elements={elements}
                  referenceStates={columnReferenceStates}
                  busy={busy}
                  selected={selectedElement}
                  onSelect={(element) => {
                    setSelectedElement(element);
                    setSimilar([]);
                  }}
                  onFeedback={feedback}
                />
                {selectedElement && (
                  <div className="editor-box">
                    <div className="panel-title">
                      <span>Редактирование элемента</span>
                      <code>{selectedElement.id.slice(0, 8)}</code>
                    </div>
                    <p className="hint" role="status">
                      {elementPointsLoading
                        ? "Загружаю исходные точки выбранного элемента…"
                        : `Исходные точки: ${selectedElementPoints.length.toLocaleString("ru-RU")} · сечения X/Y/Z: ${selectedElementSections.map((slice) => (slice.length / 3).toLocaleString("ru-RU")).join(" / ")}`}
                    </p>
                    {selectedElement.geometry?.kind === "oriented_box" && (
                      <div className="boundary-editor">
                        <div className="panel-title">
                          <span>Границы элемента</span>
                          <small>координаты и размеры в метрах</small>
                        </div>
                        <div className="boundary-fields">
                          {([
                            ["centerX", "Центр X"],
                            ["centerY", "Центр Y"],
                            ["centerZ", "Центр Z"],
                            ["length", "Длина"],
                            ["thickness", "Ширина"],
                            ["height", "Высота"],
                            ["rotationDegrees", "Поворот °"],
                          ] as [keyof OrientedBoxDraft, string][]).map(([key, label]) => (
                            <label key={key}>
                              <span className="field-label">{label}</span>
                              <input
                                type="number"
                                step="any"
                                value={boundaryDraft[key]}
                                onChange={(event) => setBoundaryDraft((draft) => ({ ...draft, [key]: event.target.value }))}
                                aria-label={label}
                              />
                            </label>
                          ))}
                        </div>
                        {boundaryError && <p className="error" role="alert">{boundaryError}</p>}
                        <button type="button" onClick={saveBoundary} disabled={busy}>
                          Сохранить исправленную геометрию
                        </button>
                        <p className="hint">
                          Изменение сохранится как исправленный элемент и появится в истории; его можно отменить.
                        </p>
                        {selectedElement.class_name === "column" && (
                          <ColumnSectionFitPanel
                            element={selectedElement}
                            candidateConflicts={elements.filter((item) => item.id !== selectedElement.id
                              && item.review_status === "unreviewed"
                              && selectedElement.bbox.min.length === 3 && selectedElement.bbox.max.length === 3
                              && item.bbox.min.length === 3 && item.bbox.max.length === 3
                              && item.bbox.min.every((value, axis) => value <= selectedElement.bbox.max[axis]
                                && item.bbox.max[axis] >= selectedElement.bbox.min[axis]))}
                            priorDecisions={reviewHistory.slice(-5).reverse()}
                            busy={busy}
                            onApplyHypothesis={applySectionHypothesis}
                            onSurfaceAnalysis={setColumnSurfaceAnalysis}
                          />
                        )}
                      </div>
                    )}
                    {cloud && selectedElement.class_name === "column" && (
                      <ColumnAnnotationPanel cloudId={cloud.id} element={selectedElement} busy={busy}
                        surfaceAnalysis={columnSurfaceAnalysis?.cloud_id === cloud.id && columnSurfaceAnalysis.candidate_id === selectedElement.id
                          ? columnSurfaceAnalysis : null}
                        onAnnotationSaved={(annotation) => setColumnReferenceStates((states) => ({ ...states, [annotation.element_id]: annotation.state }))} />
                    )}
                    <div className="editor-grid">
                      <label>
                        <span className="field-label">объединить с</span>
                        <select value={mergeTarget} onChange={(event) => setMergeTarget(event.target.value)}>
                          <option value="">выберите элемент…</option>
                          {elements
                            .filter((item) => item.id !== selectedElement.id && item.review_status !== "rejected")
                            .map((item) => (
                              <option key={item.id} value={item.id}>
                                {classLabel(item.class_name)} · {item.id.slice(0, 6)}
                              </option>
                            ))}
                        </select>
                      </label>
                      <button onClick={doMerge} disabled={!mergeTarget || busy}>
                        Объединить
                      </button>
                      <label>
                        <span className="field-label">ось разрезания</span>
                        <select value={splitAxis} onChange={(event) => setSplitAxis(event.target.value as any)}>
                          <option value="x">X</option>
                          <option value="y">Y</option>
                          <option value="z">Z</option>
                        </select>
                      </label>
                      <label>
                        <span className="field-label">разрезать в (м)</span>
                        <input
                          type="number"
                          step={0.05}
                          value={splitValue}
                          onChange={(event) => setSplitValue(Number(event.target.value))}
                        />
                      </label>
                      <button onClick={doSplit} disabled={busy}>
                        Разрезать
                      </button>
                      <button
                        onClick={async () => {
                          try {
                            setSimilar(await api.similar(selectedElement.id));
                          } catch (err) {
                            setError(detailText(err));
                          }
                        }}
                        disabled={busy}
                      >
                        Похожие подтверждённые примеры
                      </button>
                    </div>
                    <p className="hint">
                      Объединение и разрезание создают восстановленную геометрию и попадают в историю
                      правок. Класс элемента меняется в таблице.
                    </p>
                    {similar.length > 0 && (
                      <ul className="similar-list">
                        {similar.map((item) => (
                          <li key={item.id}>
                            {classLabel(item.class_name)} · расстояние {item.distance}
                          </li>
                        ))}
                      </ul>
                    )}
                    <div className="panel-title">
                      <span>История изменений</span>
                      <code>{reviewHistory.length}</code>
                    </div>
                    {reviewHistory.length > 0 ? (
                      <ul className="similar-list">
                        {reviewHistory.map((entry) => (
                          <li key={entry.id}>
                            <b>{entry.action}</b>
                            {entry.after?.review_status && ` · ${REVIEW_LABELS[entry.after.review_status] || entry.after.review_status}`}
                            {entry.after?.class_name && ` · ${classLabel(entry.after.class_name)}`}
                            {entry.engineer && ` · ${entry.engineer}`}
                            {entry.note && ` — ${entry.note}`}
                            <small>{new Date(entry.created_at).toLocaleString()}</small>
                            {entry.can_undo && (
                              <button type="button" onClick={() => undoReviewAction(entry.id)} disabled={busy}>
                                Отменить
                              </button>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="hint">Для этого элемента записей пока нет.</p>
                    )}
                  </div>
                )}
              </div>
            )}

            {tab === "learning" && (
              <div className="tab-body">
                {!project && <div className="empty-note">Выберите проект.</div>}
                {project && (
                  <>
                    <div className="stats-line">
                      <span>
                        проверенных примеров: <b>{learning?.samples ?? 0}</b>
                      </span>
                      <span>
                        классов: <b>{learning?.classes?.length ?? 0}</b>
                      </span>
                      <span>
                        рабочая модель: <b>{learning?.active_model?.version ?? "нет"}</b>
                      </span>
                    </div>
                    <div className="button-row">
                      <button className="primary" onClick={train} disabled={training}>
                        {training ? "Обучение…" : "Обучить кандидата на проверенных примерах"}
                      </button>
                      <button
                        onClick={() =>
                          download(async () => {
                            await api.rollback();
                            setModels(await api.models());
                            setLearning(await api.modelStatus(project.id));
                          }, "Откат модели")
                        }
                        disabled={busy}
                      >
                        Откатить
                      </button>
                    </div>
                    <p className="hint">
                      Обучение использует детерминированное отложенное разбиение. Кандидат
                      становится рабочей моделью только при прохождении порогов macro-F1 и числа
                      примеров; ничего не обновляется автоматически.
                    </p>
                    {trainResult && (
                      <div className={trainResult.metrics?.eligible_for_activation ? "alert info" : "alert error"}>
                        <strong>
                          v{trainResult.version} · {trainResult.status}
                        </strong>
                        <div>
                          macro-F1 {trainResult.metrics?.macro_f1 ?? "—"} · test support{" "}
                          {trainResult.metrics?.test_support ?? 0} · accuracy {trainResult.metrics?.accuracy ?? "—"}
                        </div>
                        {trainResult.metrics?.blocking_reason && <p>{trainResult.metrics.blocking_reason}</p>}
                        {trainResult.metrics?.per_class && (
                          <table className="metrics-table">
                            <thead>
                              <tr>
                                <th>класс</th>
                                <th>P</th>
                                <th>R</th>
                                <th>F1</th>
                                <th>n</th>
                              </tr>
                            </thead>
                            <tbody>
                              {Object.entries(trainResult.metrics.per_class).map(([name, value]: any) => (
                                <tr key={name}>
                                  <td>{name}</td>
                                  <td>{value.precision}</td>
                                  <td>{value.recall}</td>
                                  <td>{value.f1}</td>
                                  <td>{value.support}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    )}
                    <div className="model-list">
                      {models.map((model) => (
                        <div key={model.id} className={`model-row ${model.status}`}>
                          <div>
                            <b>
                              {model.name} v{model.version}
                            </b>
                            <small>
                              {model.status} · macro-F1 {model.metrics?.macro_f1 ?? "—"}
                            </small>
                          </div>
                          {model.status !== "active" && (
                            <button onClick={() => activateModel(model)} disabled={busy}>
                              Активировать
                            </button>
                          )}
                        </div>
                      ))}
                      {!models.length && <p className="hint">Кандидатных моделей пока нет.</p>}
                    </div>
                    <div className="alert info">
                      <strong>Состояние ML-адаптера</strong>
                      <p>
                        Провайдер: {learning?.ml?.provider || "pointcept"} · доступен:{" "}
                        {learning?.ml?.available ? "да" : "нет"}
                      </p>
                      <small>
                        Тяжёлые модели сегментации работают в отдельном окружении PyTorch.
                        Ядро системы работает без GPU.
                      </small>
                    </div>
                  </>
                )}
              </div>
            )}

            
            
            {tab === "expert" && (
              <div className="tab-body">
                <div className="panel-title">
                  <span>🧠 ИИ Ассистент-Конструктор по промышленным цехам (СПДС / ГОСТ / СП 16 / СП 70)</span>
                </div>
                <p className="hint">
                  Инженерный агент обладает глубокими знаниями конструктива каркасных цехов, кранового оборудования, серий ферм, раскладки связей и правил оформления рабочей документации.
                </p>

                <div style={{ display: "flex", gap: "8px", margin: "14px 0" }}>
                  <input
                    type="text"
                    id="expert-query-input"
                    placeholder="Спросите инженера (например: 'Какие допуски на рельс КР-70?', 'Как завязать связи ферм?')..."
                    style={{ flex: 1, padding: "8px 12px", background: "#1e1e24", border: "1px solid #333", borderRadius: "4px", color: "#fff" }}
                    onKeyDown={async (e) => {
                      if (e.key === "Enter") {
                        const target = e.currentTarget;
                        const val = target.value.trim();
                        if (!val) return;
                        try {
                          setBusy(true);
                          const res = await api.askWorkshopExpert(val, { columns_count: 233 });
                          const outDiv = document.getElementById("expert-answer-box");
                          if (outDiv) {
                            outDiv.innerHTML = `
                              <div style="background: #18181e; border-left: 4px solid #3b82f6; padding: 14px; border-radius: 4px; margin-top: 12px;">
                                <h3 style="margin-top: 0; color: #60a5fa;">${res.topic}</h3>
                                <div style="white-space: pre-wrap; line-height: 1.6;">${res.answer}</div>
                                <h4 style="margin-bottom: 6px; color: #f59e0b;">Нормативные документы:</h4>
                                <ul>${res.referenced_norms.map(n => `<li><b>${n}</b></li>`).join("")}</ul>
                                <h4 style="margin-bottom: 6px; color: #10b981;">Рекомендации и допуски:</h4>
                                <ul>${res.recommendations.map(r => `<li>${r}</li>`).join("")}</ul>
                                <h4 style="margin-bottom: 6px; color: #a78bfa;">Советы по черчению в AutoCAD:</h4>
                                <ul>${res.cad_shortcut_tips.map(t => `<li>${t}</li>`).join("")}</ul>
                              </div>
                            `;
                          }
                        } catch (err: any) {
                          alert("Ошибка связи с агентом: " + err.message);
                        } finally {
                          setBusy(false);
                        }
                      }
                    }}
                  />
                  <button
                    className="primary-button"
                    onClick={async () => {
                      const inp = document.getElementById("expert-query-input") as HTMLInputElement;
                      if (!inp || !inp.value.trim()) return;
                      const val = inp.value.trim();
                      try {
                        setBusy(true);
                        const res = await api.askWorkshopExpert(val, { columns_count: 233 });
                        const outDiv = document.getElementById("expert-answer-box");
                        if (outDiv) {
                          outDiv.innerHTML = `
                            <div style="background: #18181e; border-left: 4px solid #3b82f6; padding: 14px; border-radius: 4px; margin-top: 12px;">
                              <h3 style="margin-top: 0; color: #60a5fa;">${res.topic}</h3>
                              <div style="white-space: pre-wrap; line-height: 1.6;">${res.answer}</div>
                              <h4 style="margin-bottom: 6px; color: #f59e0b;">Нормативные документы:</h4>
                              <ul>${res.referenced_norms.map(n => `<li><b>${n}</b></li>`).join("")}</ul>
                              <h4 style="margin-bottom: 6px; color: #10b981;">Рекомендации и допуски:</h4>
                              <ul>${res.recommendations.map(r => `<li>${r}</li>`).join("")}</ul>
                              <h4 style="margin-bottom: 6px; color: #a78bfa;">Советы по черчению в AutoCAD:</h4>
                              <ul>${res.cad_shortcut_tips.map(t => `<li>${t}</li>`).join("")}</ul>
                            </div>
                          `;
                        }
                      } catch (err: any) {
                        alert("Ошибка связи с агентом: " + err.message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                    disabled={busy}
                  >
                    Задать вопрос
                  </button>
                </div>

                <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "12px" }}>
                  <button onClick={() => { const inp = document.getElementById("expert-query-input") as HTMLInputElement; if (inp) { inp.value = "Как выполнить привязку колонн цеха к осям?"; } }}>
                    📌 Привязка колонн
                  </button>
                  <button onClick={() => { const inp = document.getElementById("expert-query-input") as HTMLInputElement; if (inp) { inp.value = "Какие требования и допуски к рельсам крана КР-70?"; } }}>
                    🚂 Рельсы КР-70
                  </button>
                  <button onClick={() => { const inp = document.getElementById("expert-query-input") as HTMLInputElement; if (inp) { inp.value = "Как устроены стропильные фермы ФС-30?"; } }}>
                    🏗️ Фермы покрытия
                  </button>
                  <button onClick={() => { const inp = document.getElementById("expert-query-input") as HTMLInputElement; if (inp) { inp.value = "Система связей каркаса цеха"; } }}>
                    ⚡ Связи каркаса
                  </button>
                  <button onClick={() => { const inp = document.getElementById("expert-query-input") as HTMLInputElement; if (inp) { inp.value = "Отметки верха фундамента под колонны"; } }}>
                    🏛️ Фундаменты
                  </button>
                </div>

                <div id="expert-answer-box">
                  <div style={{ padding: "16px", background: "#141418", borderRadius: "4px", color: "#888", fontSize: "14px" }}>
                    💡 Выберите один из быстрых вопросов выше или введите свой вопрос. Агент подскажет нормативы СП/ГОСТ, правильную привязку элементов, допуски монтажа и нюансы для AutoCAD 2026.
                  </div>
                </div>
              </div>
            )}

            {tab === "registration" && (
              <div className="tab-body">
                <div className="panel-title">
                  <span>Сшивка сканов и экспорт в Autodesk ReCap</span>
                </div>
                <p className="hint">
                  Совмещение нескольких стоянок сканера по алгоритму жесткого ICP (Kabsch SVD + KDTree) с контролем среднеквадратичной ошибки (RMSE в мм) и формированием проекта ReCap.
                </p>
                <div className="button-row" style={{ marginTop: 12 }}>
                  <button
                    className="primary-button"
                    onClick={async () => {
                      if (!cloud) {
                        alert("Сначала выберите опорное облако проекта слева.");
                        return;
                      }
                      try {
                        setBusy(true);
                        const res = await api.matchCloudsIcp(cloud.id, cloud.id, 10000, 25);
                        const residual = res.rmse_mm === null
                          ? "не оценена: недостаточно соответствий"
                          : `${res.rmse_mm.toFixed(2)} мм`;
                        alert(`Сшивка выполнена! Сходимость: ${res.converged ? "ДА" : "НЕТ"}\nНевязка RMSE: ${residual}\nИтераций: ${res.iterations}`);
                      } catch (e: any) {
                        alert("Ошибка сшивки: " + e.message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                    disabled={busy || !cloud}
                  >
                    🔗 Запустить сшивку ICP (Kabsch SVD)
                  </button>
                  <button
                    onClick={async () => {
                      try {
                        setBusy(true);
                        const res = await api.openInReCap();
                        alert(res.status === "ok" ? "Autodesk ReCap запущен!" : "Не удалось открыть ReCap.");
                      } catch (e: any) {
                        alert("Ошибка: " + e.message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                    disabled={busy}
                  >
                    🚀 Запустить Autodesk ReCap
                  </button>
                </div>
              </div>
            )}

            {tab === "export" && (
              <div className="tab-body">
                {!cloud && <div className="empty-note">Выберите облако.</div>}
                {cloud && (
                  <>
                    <div className="panel-title">
                      <span>ОЧИСТКА ОБЛАКА</span>
                    </div>
                    <p className="hint">
                      Фильтры создают отдельную копию облака: исходные точки не изменяются.
                      Воксель прореживает равномерно, SOR/ROR убирают выбросы по соседям.
                      Ограничение этой сборки — 5 млн точек; результат скачивается как PLY/XYZ.
                    </p>
                    <div className="button-row">
                      <button onClick={() => runCleanup({ method: "voxel", voxel_m: 0.05 })} disabled={busy}>
                        Воксель 5 см
                      </button>
                      <button onClick={() => runCleanup({ method: "statistical", k: 16, std_ratio: 2.0 })} disabled={busy}>
                        Шумовой фильтр (SOR)
                      </button>
                      <button onClick={() => runCleanup({ method: "radius", radius_m: 0.05, min_neighbors: 4 })} disabled={busy}>
                        Радиусный фильтр (ROR)
                      </button>
                    </div>
                    {derivedClouds.length > 0 && (
                      <table className="element-table">
                        <thead>
                          <tr><th>метод</th><th>точек</th><th>удалено</th><th /></tr>
                        </thead>
                        <tbody>
                          {derivedClouds.map((item) => (
                            <tr key={item.derived_id}>
                              <td>{CLEANUP_LABELS[item.method] || item.method}</td>
                              <td>{item.output_count} из {item.input_count}</td>
                              <td>{item.removed_count}</td>
                              <td className="actions">
                                <button onClick={() => download(() => api.downloadDerived(cloud.id, item.derived_id, "ply"), "Скачивание PLY")} disabled={busy}>
                                  PLY
                                </button>
                                <button onClick={() => download(() => api.downloadDerived(cloud.id, item.derived_id, "xyz"), "Скачивание XYZ")} disabled={busy}>
                                  XYZ
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    <div className="panel-title">
                      <span>BIM</span>
                    </div>
                    <div className="button-row">
                      <button onClick={() => download(() => api.exportBim(cloud.id, "ifc"), "Экспорт IFC")} disabled={busy}>
                        Экспорт IFC4
                      </button>
                      <button
                        onClick={async () => {
                          try {
                            setBusy(true);
                            const res = await api.openInRevit();
                            alert(res.status === "ok" ? "Autodesk Revit 2027 запущен!" : "Не удалось открыть Revit.");
                          } catch (e: any) {
                            alert("Ошибка запуска Revit: " + e.message);
                          } finally {
                            setBusy(false);
                          }
                        }}
                        disabled={busy}
                      >
                        🏛️ Открыть в Autodesk Revit 2027
                      </button>
                      <button onClick={() => download(() => api.exportBim(cloud.id, "json"), "Экспорт BIM JSON")} disabled={busy}>
                        Экспорт BIM JSON
                      </button>
                      <button onClick={() => download(() => api.exportElementsDxf(cloud.id), "Экспорт DXF элементов")} disabled={busy}>
                        DXF элементов
                      </button>
                    </div>
                    <div className="panel-title">
                      <span>Планы конструкций AutoCAD</span>
                    </div>
                    <label>Масштаб PDF
                      <select value={planScale} disabled={busy} onChange={(event) => setPlanScale(Number(event.target.value))}>
                        {[50, 100, 200, 500].map((value) => <option key={value} value={value}>1:{value}</option>)}
                      </select>
                    </label>
                    <label>Тип выпуска
                      <select value={drawingIssueMode} disabled={busy} onChange={(event) => setDrawingIssueMode(event.target.value as "draft" | "final")}>
                        <option value="draft">Черновик — с кандидатами</option>
                        <option value="final">Финал — только проверенные</option>
                      </select>
                    </label>
                    <p className="hint">
                      {drawingIssueMode === "draft"
                        ? "Черновик содержит непроверенные объекты с маркировкой КАНДИДАТ и штампом «НЕ ДЛЯ РАБОТЫ»."
                        : "Финальный выпуск включает только подтверждённые или исправленные объекты и подтверждённые типы колонн."}
                    </p>
                    <p className="hint">Планы печатать 100%, без подгонки. Ведомость — на отдельных листах A3.</p>
                    <div className="button-row">
                      <button
                        onClick={() => download(() => api.exportStructuralPlanDxf(cloud.id, "columns", drawingIssueMode), "План колонн DXF")}
                        disabled={busy}
                      >
                        План колонн
                      </button>
                      <button
                        onClick={() => download(() => api.exportStructuralPlanDxf(cloud.id, "crane_girders", drawingIssueMode), "План подкрановых балок DXF")}
                        disabled={busy}
                      >
                        План подкрановых балок
                      </button>
                      <button
                        onClick={() => download(() => api.exportStructuralPlanPdf(cloud.id, "columns", planScale, drawingIssueMode), "План колонн PDF")}
                        disabled={busy}
                      >
                        Колонны PDF
                      </button>
                      <button
                        onClick={() => download(() => api.exportStructuralPlanPdf(cloud.id, "crane_girders", planScale, drawingIssueMode), "План подкрановых балок PDF")}
                        disabled={busy}
                      >
                        Подкрановые балки PDF
                      </button>
                    </div>
                    <p className="hint">
                      Непроверенные конструкции будут отмечены как кандидаты. Шаг сетки 6000 мм не подменяет измеренные координаты.
                    </p>
                    <div className="panel-title">
                      <span>Полный комплект СПДС</span>
                    </div>
                    <p className="hint">
                      Альбом включает планы колонн и подкрановых балок, разрез и схему покрытия в DXF и PDF. Все листы помечены как эскизные и требуют проверки инженером.
                    </p>
                    <div className="button-row">
                      <button onClick={() => download(() => api.exportSpdsAlbumPdf(cloud.id), "Экспорт альбома СПДС (PDF)")} disabled={busy} className="primary-button">
                        📄 Скачать альбом РД КР/КМ (ГОСТ PDF)
                      </button>
                      <button onClick={() => download(() => api.exportSpdsAlbum(cloud.id), "Экспорт чертежей СПДС (ZIP/DXF)")} disabled={busy}>
                        📦 Скачать чертежи DWG/DXF (AutoCAD)
                      </button>
                    </div>
                    <p className="hint">
                      В IFC передаются нативные сущности IfcWall/IfcColumn/IfcSlab и набор свойств
                      Pset_ScanToBIM: уверенность, признаки «измерено/восстановлено», статус проверки.
                      Толщина плит до измерения — допущение, а не замер.
                    </p>
                    <div className="panel-title">
                      <span>Чертежи сечений</span>
                    </div>
                    {section ? (
                      <div className="button-row">
                        {(["dxf", "pdf", "json"] as const).map((format) => (
                          <button
                            key={format}
                            onClick={() => download(() => api.exportSection(section.id, format), `Export ${format.toUpperCase()}`)}
                            disabled={busy}
                          >
                            {format.toUpperCase()}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <p className="hint">Сначала постройте сечение.</p>
                    )}
                    <div className="panel-title">
                      <span>API для плагинов</span>
                    </div>
                    <pre className="code-block">{`GET  /api/v1/clouds/{cloud}/elements
GET  /api/v1/clouds/{cloud}/bim?format=ifc
GET  /api/v1/clouds/{cloud}/sections
GET  /api/v1/clouds/{cloud}/structural-plan.dxf?type=columns|crane_girders
POST /api/v1/elements/{element}/feedback
GET  /api/v1/plugin/manifest`}</pre>
                    <p className="hint">
                      Плагины AutoCAD и Revit используют этот версионированный API и не нужны для
                      работы самого приложения.
                    </p>
                    {cloudBBox && (
                      <p className="hint">
                        Габарит облака: {cloudBBox.map((value) => value.toFixed(3)).join(", ")} (мировые метры)
                      </p>
                    )}
                  </>
                )}
              </div>
            )}
          </aside>
        </main>
      </div>
    </div>
  );
}
