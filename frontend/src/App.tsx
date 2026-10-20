import { useEffect, useMemo, useRef, useState } from "react";
import { api, waitForCloud, waitForJob } from "./api";
import ElementTable from "./components/ElementTable";
import SectionCanvas from "./components/SectionCanvas";
import Viewer3D from "./components/Viewer3D";
import type { Cloud, Element, ModelInfo, Project, Section, SectionResult } from "./types";

type Tab = "section" | "recognition" | "learning" | "export";
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
    api.health().catch(() => setError("Local API is not running. Start it with: python backend/run.py"));
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
    setJobLabel("Processing point cloud");
    setJobProgress(0.05);
    try {
      const ready = await waitForCloud(incoming.id, (update) => {
        setCloud(update);
        setJobProgress(update.status === "processing" ? 0.4 : 0.8);
        setClouds((list) => list.map((item) => (item.id === update.id ? update : item)));
      });
      setClouds((list) => list.map((item) => (item.id === ready.id ? ready : item)));
      setCloud(ready);
      if (ready.status === "failed") setError(ready.error || "cloud processing failed");
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
    setJobLabel("Recognising construction elements");
    setJobProgress(0.02);
    try {
      const job = await api.recognize(cloud.id);
      const finished = await waitForJob(job.id, (update) => {
        setJobProgress(update.progress || 0.05);
        setJobLabel(`Recognition: ${update.message || update.status}`);
      });
      if (finished.status === "failed") {
        setError(finished.error || "recognition failed");
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
    setJobLabel("Computing measured section");
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
            <small>independent point-cloud engineering workspace</small>
          </div>
        </div>
        <div className="topbar-right">
          <span className="pill">local API · v1</span>
          <span className="pill muted">no Autodesk required</span>
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <section className="panel">
            <div className="panel-title">
              <span>Projects</span>
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
                  <small>{item.cloud_count ?? 0} clouds</small>
                </button>
              ))}
              {!projects.length && <p className="hint">No projects yet. Create one or load the demo.</p>}
            </div>
            <div className="row">
              <input
                value={newProject}
                placeholder="New project name"
                onChange={(event) => setNewProject(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && createProject()}
              />
              <button onClick={createProject} disabled={!newProject.trim()}>
                Add
              </button>
            </div>
            <button className="demo-button" onClick={handleDemo} disabled={busy}>
              Load synthetic demo room (6 × 4 × 3 m)
            </button>
          </section>

          <section className="panel">
            <div className="panel-title">
              <span>Point clouds</span>
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
                  <span className={`badge-status ${item.status}`}>{item.status}</span>
                  <small>
                    {item.point_count.toLocaleString()} pts · {item.source_format.toUpperCase()}
                  </small>
                </button>
              ))}
              {!clouds.length && <p className="hint">Import E57, LAS/LAZ, PLY, PCD, PTS or XYZ.</p>}
            </div>
            <div className="import-block">
              <label className="field-label">Import by local path (large scans stay in place)</label>
              <div className="row">
                <input
                  value={pathInput}
                  placeholder="C:\\scans\\building.e57"
                  onChange={(event) => setPathInput(event.target.value)}
                  onKeyDown={(event) => event.key === "Enter" && handleImport()}
                  disabled={!project || busy}
                />
                <button onClick={handleImport} disabled={!project || !pathInput.trim() || busy}>
                  Import
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
                Upload a file copy…
              </button>
              <p className="hint">
                Originals are never modified. RCS/RCP are read through the installed Autodesk
                ReCap library when it is present; otherwise convert once to E57/LAS.
              </p>
            </div>
          </section>

          {cloud && (
            <section className="panel meta-panel">
              <div className="panel-title">
                <span>Cloud</span>
                <span className={`badge-status ${cloud.status}`}>{cloud.status}</span>
              </div>
              <dl>
                <dt>points</dt>
                <dd>{cloud.point_count.toLocaleString()}</dd>
                <dt>preview</dt>
                <dd>{cloud.preview_count.toLocaleString()}</dd>
                <dt>format</dt>
                <dd>{cloud.source_format.toUpperCase()}</dd>
                <dt>bbox</dt>
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
                  Height
                </button>
              </div>
              <label className="slider-label">
                point size
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
                section plane
              </label>
              <span className="spacer" />
              <span className="hint">drag orbit · wheel zoom · right-drag pan</span>
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
                  {name}
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
                <strong>RCS/RCP conversion required</strong>
                <p>{rcsInfo.summary}</p>
                <ol>
                  {(rcsInfo.steps || []).map((step: string) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
                <small>Status: not natively supported in this build.</small>
              </div>
            )}

            {tab === "section" && (
              <div className="tab-body">
                {!cloud && <div className="empty-note">Select a ready point cloud first.</div>}
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
                          Horizontal plan
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
                          Vertical section
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
                            cut along X (view Y/Z)
                          </button>
                          <button
                            className={sectionForm.axis === "y" ? "active" : ""}
                            onClick={() => {
                              const min = cloud.bbox_min?.[1] ?? 0;
                              const max = cloud.bbox_max?.[1] ?? 1;
                              setSectionForm({ ...sectionForm, axis: "y", position: (min + max) / 2 });
                            }}
                          >
                            cut along Y (view X/Z)
                          </button>
                        </div>
                      )}
                      <label className="field-label">
                        position ({sectionForm.kind === "horizontal" ? "Z" : sectionForm.axis.toUpperCase()}) —
                        {" "}
                        {sectionForm.position.toFixed(3)} m
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
                          <span className="field-label">section thickness (m)</span>
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
                          <span className="field-label">raster resolution (m)</span>
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
                        orthogonal regularisation
                      </label>
                      <button className="primary wide" onClick={createSection} disabled={busy || cloud.status !== "ready"}>
                        Build measured section
                      </button>
                    </div>

                    {sectionResult && (
                      <>
                        <div className="section-summary">
                          <div>
                            <b>{sectionResult.polygons.length}</b>
                            <small>contours</small>
                          </div>
                          <div>
                            <b>{sectionResult.point_count.toLocaleString()}</b>
                            <small>points in slab</small>
                          </div>
                          <div>
                            <b>{sectionResult.total_area_m2.toFixed(2)}</b>
                            <small>net area m²</small>
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
                              onClick={() => download(() => api.exportSection(section!.id, format), `Export ${format.toUpperCase()}`)}
                              disabled={busy}
                            >
                              Export {format.toUpperCase()}
                            </button>
                          ))}
                        </div>
                        <p className="hint">
                          DXF contains editable polylines, layers, overall dimensions, level text and an A3 sheet.
                          DWG requires AutoCAD or a licensed converter.
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
                    Run geometric recognition
                  </button>
                </div>
                <p className="hint">
                  Baseline detects walls, columns and slab footprints. Other classes are not guessed; they are
                  reported as unimplemented.
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
                    <span className="field-label">detected levels</span>
                    {recognition.levels.map((level: any) => (
                      <button
                        key={level.z}
                        className="level-chip"
                        onClick={() => {
                          setSectionForm({ ...sectionForm, kind: "horizontal", position: level.z });
                          setTab("section");
                        }}
                      >
                        {level.z.toFixed(3)} m
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
                          {key}: <b>{String(value)}</b>
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
                      <span>Edit selected element</span>
                      <code>{selectedElement.id.slice(0, 8)}</code>
                    </div>
                    <div className="editor-grid">
                      <label>
                        <span className="field-label">merge with</span>
                        <select value={mergeTarget} onChange={(event) => setMergeTarget(event.target.value)}>
                          <option value="">choose element…</option>
                          {elements
                            .filter((item) => item.id !== selectedElement.id && item.review_status !== "rejected")
                            .map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.class_name} · {item.id.slice(0, 6)}
                              </option>
                            ))}
                        </select>
                      </label>
                      <button onClick={doMerge} disabled={!mergeTarget || busy}>
                        Merge
                      </button>
                      <label>
                        <span className="field-label">split axis</span>
                        <select value={splitAxis} onChange={(event) => setSplitAxis(event.target.value as any)}>
                          <option value="x">X</option>
                          <option value="y">Y</option>
                          <option value="z">Z</option>
                        </select>
                      </label>
                      <label>
                        <span className="field-label">split at (m)</span>
                        <input
                          type="number"
                          step={0.05}
                          value={splitValue}
                          onChange={(event) => setSplitValue(Number(event.target.value))}
                        />
                      </label>
                      <button onClick={doSplit} disabled={busy}>
                        Split
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
                        Similar verified examples
                      </button>
                    </div>
                    <p className="hint">
                      Merge/split create inferred geometry and are recorded in the feedback history. Adjust class
                      per element in the table.
                    </p>
                    {similar.length > 0 && (
                      <ul className="similar-list">
                        {similar.map((item) => (
                          <li key={item.id}>
                            {item.class_name} · distance {item.distance}
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
                {!project && <div className="empty-note">Select a project.</div>}
                {project && (
                  <>
                    <div className="stats-line">
                      <span>
                        reviewed samples: <b>{learning?.samples ?? 0}</b>
                      </span>
                      <span>
                        classes: <b>{learning?.classes?.length ?? 0}</b>
                      </span>
                      <span>
                        active model: <b>{learning?.active_model?.version ?? "none"}</b>
                      </span>
                    </div>
                    <div className="button-row">
                      <button className="primary" onClick={train} disabled={training}>
                        {training ? "Training…" : "Train candidate from reviewed examples"}
                      </button>
                      <button
                        onClick={() =>
                          download(async () => {
                            await api.rollback();
                            setModels(await api.models());
                            setLearning(await api.modelStatus(project.id));
                          }, "Rolling back model")
                        }
                        disabled={busy}
                      >
                        Roll back
                      </button>
                    </div>
                    <p className="hint">
                      Training uses a deterministic held-out split. A candidate becomes active only when held-out
                      macro-F1 and sample count pass the thresholds; nothing updates automatically.
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
                                <th>class</th>
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
                              Activate
                            </button>
                          )}
                        </div>
                      ))}
                      {!models.length && <p className="hint">No candidate models yet.</p>}
                    </div>
                    <div className="alert info">
                      <strong>ML adapter status</strong>
                      <p>
                        Provider: {learning?.ml?.provider || "pointcept"} · available:{" "}
                        {String(learning?.ml?.available ?? false)}
                      </p>
                      <small>
                        Heavy segmentation models run in a separate PyTorch environment. The core works without a GPU.
                      </small>
                    </div>
                  </>
                )}
              </div>
            )}

            {tab === "export" && (
              <div className="tab-body">
                {!cloud && <div className="empty-note">Select a cloud.</div>}
                {cloud && (
                  <>
                    <div className="panel-title">
                      <span>BIM</span>
                    </div>
                    <div className="button-row">
                      <button onClick={() => download(() => api.exportBim(cloud.id, "ifc"), "Export IFC")} disabled={busy}>
                        Export IFC4
                      </button>
                      <button onClick={() => download(() => api.exportBim(cloud.id, "json"), "Export BIM JSON")} disabled={busy}>
                        Export BIM JSON
                      </button>
                      <button onClick={() => download(() => api.exportElementsDxf(cloud.id), "Export elements DXF")} disabled={busy}>
                        Elements DXF
                      </button>
                    </div>
                    <p className="hint">
                      IFC contains native IfcWall/IfcColumn/IfcSlab entities and a Pset_ScanToBIM property set with
                      confidence, measured/inferred flags and review status. Geometry of slabs uses an assumed
                      thickness until it is measured.
                    </p>
                    <div className="panel-title">
                      <span>Section drawings</span>
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
                      <p className="hint">Build a section first.</p>
                    )}
                    <div className="panel-title">
                      <span>Plugin API</span>
                    </div>
                    <pre className="code-block">{`GET  /api/v1/clouds/{cloud}/elements
GET  /api/v1/clouds/{cloud}/bim?format=ifc
GET  /api/v1/clouds/{cloud}/sections
POST /api/v1/elements/{element}/feedback
GET  /api/v1/plugin/manifest`}</pre>
                    <p className="hint">
                      AutoCAD and Revit plugins live in /plugins and use this versioned API. The application does not
                      require either CAD system to run.
                    </p>
                    {cloudBBox && (
                      <p className="hint">
                        Cloud bbox: {cloudBBox.map((value) => value.toFixed(3)).join(", ")} (world metres)
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
