import { useEffect, useMemo, useRef, useState } from "react";
import { api, waitForCloud, waitForJob } from "./api";
import ElementTable from "./components/ElementTable";
import SectionCanvas from "./components/SectionCanvas";
import Viewer3D from "./components/Viewer3D";
import { classLabel, statusLabel, type Cloud, type Element, type ModelInfo, type Project, type Section, type SectionResult } from "./types";

type Tab = "section" | "recognition" | "learning" | "export";

const TAB_LABELS: Record<Tab, string> = {
  section: "СЕЧЕНИЕ",
  recognition: "РАСПОЗНАВАНИЕ",
  learning: "ОБУЧЕНИЕ",
  export: "ЭКСПОРТ",
};

const STAT_LABELS: Record<string, string> = {
  wall_count: "стен",
  column_count: "колонн",
  slab_count: "плит",
  grid_res_m: "шаг сетки, м",
  level_candidates: "уровней",
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
  const [tab, setTab] = useState<Tab>("section");
  const [error, setError] = useState<string | null>(null);
  const [rcsInfo, setRcsInfo] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [jobLabel, setJobLabel] = useState<string | null>(null);
  const [jobProgress, setJobProgress] = useState(0);

  const [newProject, setNewProject] = useState("");
  const [pathInput, setPathInput] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const [pointSize, setPointSize] = useState(2.2);
  const [colorMode, setColorMode] = useState<"rgb" | "height">("rgb");
  const [showPlane, setShowPlane] = useState(true);

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
  const [selectedElement, setSelectedElement] = useState<Element | null>(null);
  const [mergeTarget, setMergeTarget] = useState("");
  const [splitAxis, setSplitAxis] = useState<"x" | "y" | "z">("x");
  const [splitValue, setSplitValue] = useState(0);
  const [similar, setSimilar] = useState<any[]>([]);

  const [learning, setLearning] = useState<any>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [trainResult, setTrainResult] = useState<ModelInfo | null>(null);
  const [training, setTraining] = useState(false);

  const recognition = useMemo(() => cloud?.metadata?.recognition ?? null, [cloud]);

  const refreshProjects = async () => {
    const list = await api.listProjects();
    setProjects(list);
    return list;
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
    if (cloud.status === "ready") {
      api.elements(cloud.id).then(setElements).catch(() => setElements([]));
    } else {
      setElements([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cloud?.id, cloud?.status, cloud?.updated_at]);

  const trackCloud = async (incoming: Cloud) => {
    setBusy(true);
    setJobLabel("Обработка облака точек");
    setJobProgress(0.05);
    try {
      const ready = await waitForCloud(incoming.id, (update) => {
        setCloud(update);
        setJobProgress(update.status === "processing" ? 0.4 : 0.8);
        setClouds((list) => list.map((item) => (item.id === update.id ? update : item)));
      });
      setClouds((list) => list.map((item) => (item.id === ready.id ? ready : item)));
      setCloud(ready);
      if (ready.status === "failed") setError(ready.error || "не удалось обработать облако точек");
      await refreshProjects();
    } catch (err) {
      setError(detailText(err));
    } finally {
      setBusy(false);
      setJobLabel(null);
      setJobProgress(0);
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
      if (cloud) setElements(await api.elements(cloud.id));
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
              {(["section", "recognition", "learning", "export"] as Tab[]).map((name) => (
                <button key={name} className={tab === name ? "tab active" : "tab"} onClick={() => setTab(name)}>
                  {TAB_LABELS[name]}
                </button>
              ))}
            </div>

            {jobLabel && (
              <div className="job-banner">
                <span>{jobLabel}</span>
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
                  Базовый модуль находит стены, колонны и контуры плит. Остальные классы не
                  угадываются, а честно помечаются как нереализованные.
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
                      .filter(([key]) => ["wall_count", "column_count", "slab_count", "grid_res_m", "level_candidates"].includes(key))
                      .map(([key, value]) => (
                        <span key={key}>
                          {STAT_LABELS[key] || key}: <b>{String(value)}</b>
                        </span>
                      ))}
                  </div>
                )}
                <ElementTable
                  elements={elements}
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

            {tab === "export" && (
              <div className="tab-body">
                {!cloud && <div className="empty-note">Выберите облако.</div>}
                {cloud && (
                  <>
                    <div className="panel-title">
                      <span>BIM</span>
                    </div>
                    <div className="button-row">
                      <button onClick={() => download(() => api.exportBim(cloud.id, "ifc"), "Экспорт IFC")} disabled={busy}>
                        Экспорт IFC4
                      </button>
                      <button onClick={() => download(() => api.exportBim(cloud.id, "json"), "Экспорт BIM JSON")} disabled={busy}>
                        Экспорт BIM JSON
                      </button>
                      <button onClick={() => download(() => api.exportElementsDxf(cloud.id), "Экспорт DXF элементов")} disabled={busy}>
                        DXF элементов
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
