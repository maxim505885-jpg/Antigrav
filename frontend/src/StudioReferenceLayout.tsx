import React, { useEffect, useMemo, useState } from "react";
import Viewer3D, { type CameraPreset } from "./components/Viewer3D";
import { GostProfileInspectorModal } from "./components/GostProfileInspectorModal";
import ColumnAnnotationPanel from "./components/ColumnAnnotationPanel";
import ColumnTypesPanel from "./components/ColumnTypesPanel";
import ElementAnnotationPanel from "./components/ElementAnnotationPanel";
import { BubblePanoramaViewer } from "./components/BubblePanoramaViewer";
import { SplitScreenRegistrationView } from "./components/SplitScreenRegistrationView";
import { api, type LearningManifestPreview, type LearningManifestExportResult } from "./api";
import { recognitionReviewState } from "./recognitionReviewState";
import { rcpDeclaredCountWarning } from "./studioPresentation";
import { elementRoleSummary } from "./elementRoleSummary";
import "./StudioReferenceLayout.css";
import { type Cloud, type Element, type Job, type Project, classLabel } from "./types";
import {
  Hexagon, Sparkles, Folder, Network, Scan, FileText, Box, Layers, Settings,
  Search, Bell, User, Maximize2, Minimize2, X, Check, Play, Camera, Database,
  Sliders, ChevronLeft, ChevronRight, Eye, Plus, HardDrive, Compass, Crosshair,
  Grid, Building, RefreshCw, BarChart3, ShieldCheck, Download, CheckCircle2,
  Cpu, Activity, CheckSquare, Square
} from "lucide-react";

export interface StudioLayoutProps {
  projects: Project[];
  project: Project | null;
  cloud: Cloud | null;
  clouds: Cloud[];
  elements: Element[];
  jobs: Job[];
  dataLoading: boolean;
  selectedElement: Element | null;
  onSelectElement: (el: Element | null) => void;
  onRunSinglePass: (cloudId: string | null) => void;
  onCloudChange: (cloudId: string) => void;
  onProjectChange: (projectId: string) => void;
  onCreateProject?: (name: string) => Promise<void>;
  onUploadScan?: (file: File, maxPoints?: number) => Promise<void>;
  onImportPath?: (path: string, maxPoints?: number) => Promise<void>;
  onCancelImport?: () => Promise<void>;
  canCancelImport?: boolean;
  onTabChange?: (tab: string) => void;
  busy: boolean;
  jobLabel: string | null;
  jobProgress: number | null;
}

export const StudioReferenceLayout: React.FC<StudioLayoutProps> = ({
  projects,
  project,
  cloud,
  clouds,
  elements,
  jobs,
  dataLoading,
  selectedElement,
  onSelectElement,
  onRunSinglePass,
  onCloudChange,
  onProjectChange,
  onCreateProject,
  onUploadScan,
  onImportPath,
  onCancelImport,
  canCancelImport = false,
  busy,
  jobLabel,
  jobProgress,
}) => {
  // Navigation & Viewport State
  const [activeWorkspace, setActiveWorkspace] = useState("processing");
  const [activeTopTab, setActiveTopTab] = useState("processing");
  const [activeSideNav, setActiveSideNav] = useState("processing");
  const [dataSourceFilter, setDataSourceFilter] = useState<"all" | "ready" | "faro">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeStepper, setActiveStepper] = useState(4); // 4 = Распознавание
  const [viewportTab, setViewportTab] = useState<"cloud" | "rgb" | "classes" | "mesh">("cloud");
  const [colorMode, setColorMode] = useState<"rgb" | "height" | "intensity" | "classes">("rgb");
  const [pointCloudVisible, setPointCloudVisible] = useState(true);
  const [structuralModelVisible, setStructuralModelVisible] = useState(false);
  const [pointPickMode, setPointPickMode] = useState(false);
  const [pickedPoint, setPickedPoint] = useState<[number, number, number] | null>(null);
  const [measureMode, setMeasureMode] = useState(false);
  const [showLimitBox, setShowLimitBox] = useState(false);
  const [inspectingElement, setInspectingElement] = useState<Element | null>(null);
  const [showRecognitionReview, setShowRecognitionReview] = useState(false);
  const [showLearningManifest, setShowLearningManifest] = useState(false);
  const [learningManifest, setLearningManifest] = useState<LearningManifestPreview | null>(null);
  const [learningManifestExport, setLearningManifestExport] = useState<LearningManifestExportResult | null>(null);
  const [learningManifestError, setLearningManifestError] = useState<string | null>(null);
  const [learningManifestBusy, setLearningManifestBusy] = useState(false);
  const [recognitionQuery, setRecognitionQuery] = useState("");
  const [recognitionKind, setRecognitionKind] = useState<"all" | "column" | "structural">("all");
  const [recognitionVisibleCount, setRecognitionVisibleCount] = useState(100);
  const [showImportDialog, setShowImportDialog] = useState(false);
  const [importPathValue, setImportPathValue] = useState("");
  const [keepFullResolution, setKeepFullResolution] = useState(true);
  const [importDialogError, setImportDialogError] = useState<string | null>(null);
  const [cancelPending, setCancelPending] = useState(false);
  const [independentReviewState, setIndependentReviewState] = useState<Record<string, string>>({});
  const [showColumnTypes, setShowColumnTypes] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportMessage, setExportMessage] = useState<string | null>(null);

  const navigateTo = (workspace: string, topTab: string, sideNav: string) => {
    setActiveWorkspace(workspace);
    setActiveTopTab(topTab);
    setActiveSideNav(sideNav);
    setExportMessage(null);
  };
  const runExport = async (label: string, action: () => Promise<unknown>) => {
    if (!cloud?.id || exportBusy) return;
    setExportBusy(true);
    setExportMessage(null);
    try {
      await action();
      setExportMessage(`${label}: файл подготовлен и отправлен в загрузки браузера.`);
    } catch (error) {
      setExportMessage(`${label}: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setExportBusy(false);
    }
  };

  // Object Properties Tab State
  const [objTab, setObjTab] = useState<"general" | "geometry" | "classes" | "attributes">("general");

  // Element Counts
  const countClass = (className: string) => elements.filter((element) => element.class_name === className).length;
  const beamsCount = countClass("beam") + countClass("crane_girder");
  const columnsCount = countClass("column");
  const slabsCount = countClass("slab");
  const pipesCount = countClass("pipe");
  const wallsCount = countClass("wall");
  const totalObjectsCount = elements.length;
  const rcpCountWarning = rcpDeclaredCountWarning(cloud?.metadata, cloud?.warning);
  const recognitionCandidates = useMemo(() => elements.filter((element) => {
    const isColumn = element.class_name === "column";
    const isStructural = ["beam", "crane_girder", "truss", "brace"].includes(element.class_name);
    const matchesKind = recognitionKind === "all" || (recognitionKind === "column" ? isColumn : isStructural);
    const haystack = `${element.id} ${element.class_name} ${JSON.stringify(element.metadata || {})}`.toLocaleLowerCase();
    return matchesKind && haystack.includes(recognitionQuery.trim().toLocaleLowerCase());
  }), [elements, recognitionKind, recognitionQuery]);
  useEffect(() => {
    if (!showRecognitionReview) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setShowRecognitionReview(false); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [showRecognitionReview]);
  useEffect(() => {
    if (!showImportDialog || busy) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setShowImportDialog(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [showImportDialog, busy]);
  useEffect(() => {
    if (!canCancelImport) setCancelPending(false);
  }, [canCancelImport]);
  useEffect(() => {
    if (!showRecognitionReview || !cloud?.id) return;
    let active = true;
    setIndependentReviewState({});
    void (async () => {
      const states: Record<string, string> = {};
      const [elementsResult, columnsResult] = await Promise.allSettled([
        api.elementAnnotations(cloud.id),
        api.columnAnnotations(cloud.id),
      ]);
      if (elementsResult.status === "fulfilled") {
        for (const annotation of elementsResult.value.annotations) states[annotation.element_id] = annotation.state;
      }
      if (columnsResult.status === "fulfilled") {
        for (const annotation of columnsResult.value.annotations) states[annotation.element_id] = annotation.state;
      }
      if (active) setIndependentReviewState(states);
    })();
    return () => { active = false; };
  }, [showRecognitionReview, cloud?.id]);
  useEffect(() => {
    if (!showRecognitionReview || !project?.id) return;
    let active = true;
    setLearningManifest(null);
    setLearningManifestExport(null);
    setLearningManifestError(null);
    api.learningManifestPreview(project.id)
      .then((preview) => { if (active) setLearningManifest(preview); })
      .catch((error) => { if (active) setLearningManifestError(error instanceof Error ? error.message : String(error)); });
    return () => { active = false; };
  }, [showRecognitionReview, project?.id]);

  const exportLearningManifest = async () => {
    if (!project || !learningManifest || learningManifest.eligible_sample_count < 1) return;
    const confirmed = window.confirm(
      `Экспортировать ${learningManifest.eligible_sample_count} проверенных примеров в каталог проекта? ` +
      "Экспорт не запускает обучение и не меняет рабочую модель.",
    );
    if (!confirmed) return;
    setLearningManifestBusy(true);
    setLearningManifestError(null);
    try {
      const result = await api.exportLearningManifest(project.id, learningManifest.manifest_sha256);
      setLearningManifestExport(result);
      setLearningManifest(await api.learningManifestPreview(project.id));
    } catch (error) {
      setLearningManifestError(error instanceof Error ? error.message : String(error));
    } finally {
      setLearningManifestBusy(false);
    }
  };
  const projectStorageBytes = clouds.reduce((total, item) => total + (Number.isFinite(item.size_bytes) ? item.size_bytes : 0), 0);
  const elementBounds = selectedElement?.bbox;
  const bboxExtents = Array.isArray(elementBounds?.min) && elementBounds.min.length >= 3 && Array.isArray(elementBounds?.max) && elementBounds.max.length >= 3
    ? elementBounds.min.slice(0, 3).map((value, index) => Math.max(0, elementBounds.max[index] - value))
    : null;
  const planElements = elements.filter((item) => item.bbox?.min?.length >= 2 && item.bbox?.max?.length >= 2);
  const planMinX = planElements.length ? Math.min(...planElements.map((item) => item.bbox.min[0])) : 0;
  const planMaxX = planElements.length ? Math.max(...planElements.map((item) => item.bbox.max[0])) : 1;
  const planMinY = planElements.length ? Math.min(...planElements.map((item) => item.bbox.min[1])) : 0;
  const planMaxY = planElements.length ? Math.max(...planElements.map((item) => item.bbox.max[1])) : 1;
  const planSpanX = Math.max(planMaxX - planMinX, 1e-6);
  const planSpanY = Math.max(planMaxY - planMinY, 1e-6);
  const elementColor = (className: string) => ({ column: "#10b981", beam: "#38bdf8", crane_girder: "#38bdf8", wall: "#f59e0b", brace: "#fdba74", truss: "#f97316", pipe: "#fdba74" }[className] || "#94a3b8");
  const searchMatches = useMemo(() => {
    const query = searchQuery.trim().toLocaleLowerCase();
    if (!query) return [];
    const projectMatches = projects.filter((item) => item.name.toLocaleLowerCase().includes(query)).map((item) => ({ kind: "project" as const, id: item.id, label: item.name, detail: "Проект" }));
    const cloudMatches = clouds.filter((item) => `${item.name} ${item.source_format} ${item.id}`.toLocaleLowerCase().includes(query)).map((item) => ({ kind: "cloud" as const, id: item.id, label: item.name, detail: `${item.source_format} · ${item.status}` }));
    const elementMatches = elements.filter((item) => `${item.id} ${item.class_name} ${JSON.stringify(item.metadata || {})}`.toLocaleLowerCase().includes(query)).slice(0, 6).map((item) => ({ kind: "element" as const, id: item.id, label: `${classLabel(item.class_name)} · ${item.id.slice(0, 10)}`, detail: "Кандидат текущего облака" }));
    return [...projectMatches, ...cloudMatches, ...elementMatches].slice(0, 8);
  }, [elements, projects, clouds, searchQuery]);
  const visibleClouds = clouds.filter((item) => dataSourceFilter === "all"
    || (dataSourceFilter === "ready" && item.status === "ready")
    || (dataSourceFilter === "faro" && /faro|rcs|fls/i.test(`${item.source_format} ${item.name}`)));
  const selectSearchMatch = (match: (typeof searchMatches)[number]) => {
    setSearchQuery("");
    if (match.kind === "project") {
      void onProjectChange(match.id);
      navigateTo("projects", "projects", "data");
    } else if (match.kind === "cloud") {
      void onCloudChange(match.id);
      navigateTo("projects", "projects", "data");
    } else {
      const element = elements.find((item) => item.id === match.id);
      if (element) onSelectElement(element);
      navigateTo("processing", "processing", "processing");
    }
  };

  // Selected Object Details
  const activeObjName = selectedElement ? `Элемент ${selectedElement.id.slice(0, 7)}` : "Элемент не выбран";
  const activeObjClass = selectedElement?.class_name ? classLabel(selectedElement.class_name) : "—";
  const selectedRoleSummary = elementRoleSummary(selectedElement);
  const recentJobs = [...jobs].sort((a, b) => (b.updated_at || b.created_at || "").localeCompare(a.updated_at || a.created_at || "")).slice(0, 8);
  const jobTypeLabel = (type: string) => ({ ingest: "Импорт облака", recognize: "Распознавание", cleanup: "Очистка", registration: "Регистрация", export: "Экспорт" }[type] || type);
  const jobStatusLabel = (status: string) => ({ succeeded: "Завершено", running: "Выполняется", queued: "В очереди", failed: "Ошибка", cancelled: "Отменено" }[status] || status);
  const formatBytes = (bytes: number) => bytes < 1024 ** 3 ? `${(bytes / 1024 ** 2).toFixed(1)} МБ` : `${(bytes / 1024 ** 3).toFixed(2)} ГБ`;
  const formatMeters = (meters: number | undefined) => Number.isFinite(meters) ? `${(meters as number).toFixed(3)} м` : "—";

  return (
    <div className="scan-studio-root" style={{ display: "flex", flexDirection: "column", width: "100vw", height: "100vh", background: "#111213", color: "#f8fafc", fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", overflow: "hidden", userSelect: "none" }}>
      
      {/* 1. TOP HEADER */}
      <header className="scan-studio-header" style={{ height: 48, background: "#1b1c1e", borderBottom: "1px solid #333436", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 14px", flexShrink: 0 }}>
        {/* Left: Brand Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", width: 28, height: 28 }}>
            <Hexagon size={28} color="#fb923c" fill="#ea580c" style={{ opacity: 0.85 }} />
            <Sparkles size={14} color="#ffffff" style={{ position: "absolute" }} />
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: 13.5, fontWeight: 900, letterSpacing: 0.8, color: "#ffffff", lineHeight: 1.1 }}>SCAN STUDIO 4.0</span>
            <span style={{ fontSize: 8.5, fontWeight: 700, color: "#fdba74", letterSpacing: 0.6 }}>ОТ ОБЛАКА ТОЧЕК К ЧЕРТЕЖУ</span>
          </div>
        </div>

        {/* Center: Main Navigation Tabs (Pills) */}
        <div style={{ display: "flex", alignItems: "center", gap: 4, background: "#111213", padding: "3px 5px", borderRadius: 20, border: "1px solid #333436" }}>
          {[
            { id: "projects", label: "Проекты", icon: <Folder size={13} /> },
            { id: "processing", label: "Обработка", icon: <Network size={13} /> },
            { id: "registration", label: "Сшивка станций", icon: <Crosshair size={13} /> },
            { id: "recognition", label: "Распознавание", icon: <Scan size={13} /> },
            { id: "drafting", label: "Чертежи", icon: <Sliders size={13} /> },
            { id: "bim", label: "BIM", icon: <Box size={13} /> },
            { id: "reports", label: "Отчёты", icon: <FileText size={13} /> },
          ].map((tab) => {
            const isActive = activeTopTab === tab.id;
            return (
              <button
                key={tab.id}
                aria-current={isActive ? "page" : undefined}
                onClick={() => {
                  const route = tab.id === "drafting" ? "drawings" : tab.id;
                  const side = ({ projects: "data", processing: "processing", registration: "stitching", recognition: "results", drafting: "drawings", bim: "bim_model", reports: "reports_side" } as Record<string, string>)[tab.id];
                  navigateTo(route, tab.id, side);
                  if (tab.id === "recognition") setShowRecognitionReview(true);
                }}
                style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 16,
                  background: isActive ? "linear-gradient(135deg, #f97316 0%, #ea580c 100%)" : "transparent",
                  color: isActive ? "#ffffff" : "#94a3b8", border: "none", fontSize: 11.5, fontWeight: isActive ? 700 : 500,
                  cursor: "pointer", boxShadow: isActive ? "0 0 10px rgba(249, 115, 22, 0.32)" : "none", transition: "all 0.15s ease"
                }}
              >
                {tab.icon}
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* Right: Search, Notifications, Settings, User */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 7, background: "#2a2b2d", border: "1px solid #3f4144", borderRadius: 18, padding: "4px 12px", width: 220 }}>
            <Search size={13} color="#fb923c" />
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter" && searchMatches[0]) selectSearchMatch(searchMatches[0]); if (event.key === "Escape") setSearchQuery(""); }}
              aria-label="Поиск по проекту и объектам"
              type="text"
              placeholder="Поиск по проекту, объектам..."
              style={{ background: "transparent", border: "none", color: "#f8fafc", fontSize: 11, outline: "none", width: "100%" }}
            />
            {searchQuery.trim() && <div role="listbox" aria-label="Результаты поиска" style={{ position: "absolute", zIndex: 30, top: "calc(100% + 7px)", right: 0, width: 330, maxHeight: 320, overflowY: "auto", padding: 5, background: "#202123", border: "1px solid #515357", borderRadius: 7, boxShadow: "0 12px 30px #0009" }}>
              {searchMatches.length ? searchMatches.map((match) => <button type="button" role="option" aria-selected="false" key={`${match.kind}:${match.id}`} onClick={() => selectSearchMatch(match)} style={{ width: "100%", display: "flex", justifyContent: "space-between", gap: 10, textAlign: "left", padding: "8px 9px", border: 0, borderRadius: 4, background: "transparent", color: "#f8fafc", cursor: "pointer" }}><span>{match.label}</span><span style={{ color: "#94a3b8", fontSize: 10, whiteSpace: "nowrap" }}>{match.detail}</span></button>) : <div role="status" style={{ padding: 8, color: "#94a3b8", fontSize: 11 }}>Ничего не найдено в загруженных данных.</div>}
            </div>}
          </div>
          <button style={{ background: "transparent", border: "none", color: "#94a3b8", cursor: "pointer", display: "grid", placeItems: "center" }}><Bell size={15} /></button>
          <button type="button" aria-label="Настройки проекта" onClick={() => navigateTo("settings", "settings", "settings_side")} style={{ background: "transparent", border: "none", color: "#94a3b8", cursor: "pointer", display: "grid", placeItems: "center" }}><Settings size={15} /></button>
          <div style={{ width: 1, height: 16, background: "#3f4144" }} />
          <div style={{ display: "flex", gap: 6, alignItems: "center", color: "#64748b" }}>
            <span style={{ fontSize: 12, cursor: "pointer" }}>—</span>
            <span style={{ fontSize: 11, cursor: "pointer" }}>□</span>
            <span style={{ fontSize: 12, cursor: "pointer" }}>✕</span>
          </div>
          <div style={{ width: 26, height: 26, borderRadius: "50%", background: "#ea580c", display: "grid", placeItems: "center", border: "1px solid #fb923c", marginLeft: 4 }}>
            <User size={14} color="#ffffff" />
          </div>
        </div>
      </header>

      {/* 2. MAIN WORKSPACE ROW */}
      <div className={`scan-studio-main${activeWorkspace === "registration" ? " scan-studio-main--registration" : ""}`} style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        
        {/* LEFT SIDEBAR */}
        <aside className="scan-studio-sidebar" style={{ width: 195, background: "#171819", borderRight: "1px solid #333436", display: "flex", flexDirection: "column", padding: "10px 8px", flexShrink: 0, gap: 10 }}>
          
          {/* Project Header Card */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: 8, background: "#232426", borderRadius: 8, border: "1px solid #3f4144" }}>
            <div style={{ height: 48, borderRadius: 5, background: "linear-gradient(135deg, #35373a 0%, #313336 100%)", display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", position: "relative" }}>
              <Building size={28} color="#fb923c" style={{ opacity: 0.6 }} />
              <div style={{ position: "absolute", bottom: 4, left: 6, fontSize: 8.5, background: "rgba(17, 18, 19, 0.88)", padding: "1px 5px", borderRadius: 3, color: "#fed7aa" }}>
                {cloud?.point_count ? `${cloud.point_count.toLocaleString("ru-RU")} точек` : "Размеры не вычислены"}
              </div>
            </div>
            <div>
              <select
                value={project?.id || ""}
                onChange={(e) => onProjectChange(e.target.value)}
                style={{ width: "100%", background: "transparent", color: "#ffffff", border: "none", fontSize: 12.5, fontWeight: 800, outline: "none", cursor: "pointer" }}
              >
                {projects.map(p => <option key={p.id} value={p.id} style={{ background: "#171819", color: "#fff" }}>{p.name}</option>)}
              </select>
              <div style={{ fontSize: 9.5, color: "#fb923c", marginTop: 1 }}>{project?.units || "Единицы не заданы"} · {clouds.length} облаков</div>
            </div>
          </div>

          {/* Sources Section */}
          <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ fontSize: 10, fontWeight: 800, color: "#6b7280", letterSpacing: 0.5, padding: "0 6px" }}>ИСТОЧНИКИ ДАННЫХ</div>
            {[
              { label: "Облака точек", count: clouds.length, filter: "all" as const },
              { label: "Готовые облака", count: clouds.filter((item) => item.status === "ready").length, filter: "ready" as const },
              { label: "FARO / RCS", count: clouds.filter((item) => /faro|rcs|fls/i.test(`${item.source_format} ${item.name}`)).length, filter: "faro" as const },
              { label: "Панорамы 360°", count: null, filter: null },
              { label: "Планы / CAD", count: null, filter: null },
            ].map(s => (
              <button
                type="button"
                key={s.label}
                onClick={() => {
                  if (s.label === "Панорамы 360°") { navigateTo("panoramas", "processing", "data"); return; }
                  if (s.label === "Планы / CAD") { navigateTo("drawings", "drafting", "drawings"); return; }
                  setDataSourceFilter(s.filter || "all");
                  navigateTo("projects", "projects", "data");
                }}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between", padding: "4px 8px", borderRadius: 4,
                  background: s.filter === dataSourceFilter ? "rgba(249, 115, 22, 0.16)" : "transparent", border: s.filter === dataSourceFilter ? "1px solid rgba(249, 115, 22, 0.45)" : "1px solid transparent",
                  fontSize: 10.5, color: s.filter === dataSourceFilter ? "#fed7aa" : "#94a3b8", cursor: "pointer", textAlign: "left"
                }}
              >
                <span>{s.label}</span>
                <span style={{ fontSize: 9.5, background: "#35373a", color: "#fdba74", padding: "1px 5px", borderRadius: 8, fontWeight: 700 }}>{dataLoading ? "…" : s.count === null ? "открыть" : s.count}</span>
              </button>
            ))}
          </div>

          {/* Storage Meter */}
          <div style={{ marginTop: "auto", padding: "8px 6px", background: "#1b1c1e", borderRadius: 6, border: "1px solid #333436", fontSize: 9.5 }}>
            <div style={{ display: "flex", justifyContent: "space-between", color: "#94a3b8", marginBottom: 4 }}>
              <span>Хранилище</span>
              <strong style={{ color: "#ffffff" }}>{dataLoading ? "загрузка…" : clouds.length ? formatBytes(projectStorageBytes) : "нет данных"}</strong>
            </div>
            <div style={{ width: "100%", height: 5, background: "#383a3d", borderRadius: 3, overflow: "hidden" }}>
              <div style={{ width: "100%", height: "100%", background: "linear-gradient(90deg, #fb923c 0%, #fb923c 100%)", opacity: clouds.length ? 1 : 0 }} />
            </div>
          </div>
        </aside>

        {/* WORKSPACE CONTENT AREA (TOP & BOTTOM) */}
        {activeWorkspace === "processing" ? <div className="scan-studio-workspace" style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
          
          {/* TOP SECTION: PIPELINE + 3D VIEWPORT */}
          <div className="scan-studio-top" style={{ display: "flex", flex: 1.25, minHeight: 0, borderBottom: "1px solid #333436" }}>
            
            {/* LEFT: ИИ-КОНВЕЙЕР ОБРАБОТКИ (NODE GRAPH) */}
            <div className="scan-studio-pipeline" style={{ flex: 1.2, background: "#18191b", padding: "10px 14px", display: "flex", flexDirection: "column", gap: 8, overflow: "hidden", borderRight: "1px solid #333436" }}>
              
              {/* Stepper Header Bar */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "#242527", padding: "5px 12px", borderRadius: 20, border: "1px solid #3f4144" }}>
                {[
                  { step: 1, label: "Импорт" },
                  { step: 2, label: "Сшивка станций" },
                  { step: 3, label: "Очистка" },
                  { step: 4, label: "Распознавание" },
                  { step: 5, label: "Моделирование" },
                  { step: 6, label: "Чертежи" },
                ].map(st => (
                  <div
                    key={st.step}
                    role="button"
                    tabIndex={0}
                    aria-label={st.step === 2 ? "Открыть регистрацию станций" : st.label}
                    onClick={() => {
                      setActiveStepper(st.step);
                      if (st.step === 2) navigateTo("registration", "registration", "stitching");
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setActiveStepper(st.step);
                        if (st.step === 2) navigateTo("registration", "registration", "stitching");
                      }
                    }}
                    style={{
                      display: "flex", alignItems: "center", gap: 5, padding: "3px 9px", borderRadius: 14,
                      background: st.step === activeStepper ? "linear-gradient(135deg, #f97316 0%, #ea580c 100%)" : "transparent",
                      boxShadow: st.step === activeStepper ? "0 0 10px rgba(249, 115, 22, 0.4)" : "none",
                      color: st.step === activeStepper ? "#ffffff" : "#94a3b8",
                      fontSize: 10.5, fontWeight: st.step === activeStepper ? 800 : 600, cursor: "pointer"
                    }}
                  >
                    <span style={{ width: 15, height: 15, borderRadius: "50%", background: st.step === activeStepper ? "#ffffff" : "#45474a", color: st.step === activeStepper ? "#ea580c" : "#cbd5e1", display: "grid", placeItems: "center", fontSize: 8.5, fontWeight: 900 }}>
                      {st.step}
                    </span>
                    <span>{st.label}</span>
                  </div>
                ))}
              </div>

              {/* Sub-toolbar */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 4px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <Sparkles size={14} color="#fdba74" />
                  <span style={{ fontSize: 12, fontWeight: 800, color: "#ffffff" }}>ИИ-Конвейер обработки</span>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button style={{ background: "#2a2b2d", border: "1px solid #3f4144", color: "#fed7aa", padding: "3px 8px", borderRadius: 5, fontSize: 10, cursor: "pointer" }}>⚙ Настройки конвейера</button>
                  <button style={{ background: "#2a2b2d", border: "1px solid #3f4144", color: "#fed7aa", padding: "3px 8px", borderRadius: 5, fontSize: 10, cursor: "pointer" }}>💾 Сохранить как шаблон</button>
                </div>
              </div>

              {/* Visual Node Graph Cards */}
              <div className="scan-studio-pipeline-grid" style={{ flex: 1, display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8, alignItems: "stretch", overflow: "hidden", position: "relative" }}>
                
                {/* Node 1: Импорт данных */}
                <div style={{ background: "#202123", borderRadius: 8, border: "1px solid #3f4144", padding: 8, display: "flex", flexDirection: "column", gap: 6, fontSize: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #383a3d", paddingBottom: 4 }}>
                    <span style={{ fontWeight: 800, color: "#ffffff" }}>Импорт данных</span>
                    <Square size={13} color="#64748b" />
                  </div>
                  <div style={{ height: 46, borderRadius: 4, background: "#303235", display: "grid", placeItems: "center", color: "#fdba74" }}>
                    <Database size={20} />
                  </div>
                  <div style={{ color: "#fdba74", fontWeight: 700 }}>{cloud?.name || "Облако не выбрано"}</div>
                  <div style={{ fontSize: 9, color: "#94a3b8" }}>Формат: {cloud?.source_format || "нет данных"}</div>
                  <div
                    className={`scan-studio-import-status${cloud?.decimated ? " scan-studio-import-status--sampled" : ""}`}
                    role="status"
                  >
                    {cloud
                      ? `${cloud.ingested_count.toLocaleString("ru-RU")} из ${cloud.point_count.toLocaleString("ru-RU")} точек${cloud.decimated ? " · ПРОРЕЖЕНО" : ""} · ${cloud.status}`
                      : dataLoading ? "Загрузка облака и точек…" : "Импорт не выполнен"}
                  </div>
                  {cloud?.warning && (
                    <div className="scan-studio-import-warning" role="alert" title={cloud.warning}>
                      ⚠ {cloud.warning}
                    </div>
                  )}
                  {rcpCountWarning && (
                    <div className="scan-studio-import-warning" role="alert">
                      ⚠ {rcpCountWarning}
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={() => { setImportDialogError(null); setShowImportDialog(true); }}
                    disabled={busy || !project}
                    style={{ background: "#f97316", color: "#fff", border: 0, borderRadius: 5, padding: "5px 6px", fontSize: 9, fontWeight: 800, cursor: busy ? "wait" : "pointer" }}
                  >
                    <Plus size={10} style={{ verticalAlign: "-2px", marginRight: 3 }} />Добавить скан
                  </button>
                </div>

                {/* Node 2: Регистрация / Сшивка */}
                <div style={{ background: "#202123", borderRadius: 8, border: "1px solid #3f4144", padding: 8, display: "flex", flexDirection: "column", gap: 5, fontSize: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #383a3d", paddingBottom: 4 }}>
                    <span style={{ fontWeight: 800, color: "#ffffff" }}>Сшивка станций</span>
                    <Square size={13} color="#64748b" />
                  </div>
                  <div style={{ height: 46, borderRadius: 4, background: "#303235", display: "grid", placeItems: "center", color: "#38bdf8" }}>
                    <Activity size={20} />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <span style={{ fontSize: 8.5, color: "#94a3b8" }}>Оценка регистрации:</span>
                    <div style={{ background: "#303235", padding: "2px 4px", borderRadius: 3, color: "#e2e8f0", fontSize: 9 }}>не измерена</div>
                  </div>
                  <div style={{ marginTop: "auto", fontSize: 8.5, color: "#10b981", fontWeight: 700 }}>
                    Нет результата регистрации для этого облака
                  </div>
                </div>

                {/* Node 3: Очистка облака */}
                <div style={{ background: "#202123", borderRadius: 8, border: "1px solid #3f4144", padding: 8, display: "flex", flexDirection: "column", gap: 5, fontSize: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #383a3d", paddingBottom: 4 }}>
                    <span style={{ fontWeight: 800, color: "#ffffff" }}>Очистка</span>
                    <Square size={13} color="#64748b" />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3, margin: "auto 0" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, color: "#e2e8f0", fontSize: 9 }}>
                      <Square size={10} color="#64748b" /> Удаление шума
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, color: "#e2e8f0", fontSize: 9 }}>
                      <Square size={10} color="#64748b" /> Классификация
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, color: "#e2e8f0", fontSize: 9 }}>
                      <Square size={10} color="#64748b" /> Фильтр выбросов
                    </div>
                  </div>
                  <div style={{ marginTop: "auto", fontSize: 8.5, color: "#38bdf8", fontWeight: 700 }}>
                    {jobs.find((job) => job.type === "cleanup") ? jobStatusLabel(jobs.find((job) => job.type === "cleanup")!.status) : dataLoading ? "Загрузка истории…" : "Очистка не запускалась"}
                  </div>
                </div>

                {/* Node 4: Распознавание конструкций */}
                <div style={{ background: "#2b2c2e", borderRadius: 8, border: "1px solid #fb923c", padding: 8, display: "flex", flexDirection: "column", gap: 4, fontSize: 9.5, boxShadow: "0 0 12px rgba(249, 115, 22, 0.2)" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #515357", paddingBottom: 3 }}>
                    <span style={{ fontWeight: 800, color: "#fed7aa" }}>Распознавание</span>
                    <Square size={13} color="#64748b" />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}><span>Балки:</span> <strong>{dataLoading ? "…" : beamsCount}</strong></div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}><span>Колонны:</span> <strong>{dataLoading ? "…" : columnsCount}</strong></div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}><span>Плиты:</span> <strong>{dataLoading ? "…" : slabsCount}</strong></div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}><span>Трубы:</span> <strong>{dataLoading ? "…" : pipesCount}</strong></div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}><span>Стены:</span> <strong>{dataLoading ? "…" : wallsCount}</strong></div>
                  </div>
                  <div style={{ marginTop: "auto", fontSize: 8.5, color: "#10b981", fontWeight: 700 }}>
                    {dataLoading ? "Загрузка кандидатов…" : `${totalObjectsCount.toLocaleString("ru-RU")} кандидатов · точность не измерена`}
                  </div>
                  <button
                    onClick={() => onRunSinglePass(cloud?.id || null)}
                    disabled={busy || cloud?.status !== "ready"}
                    style={{ background: "linear-gradient(135deg, #f97316 0%, #ea580c 100%)", color: "#ffffff", border: "none", borderRadius: 5, padding: "5px 0", fontWeight: 800, fontSize: 10.5, cursor: busy ? "wait" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 4, opacity: busy || cloud?.status !== "ready" ? 0.55 : 1 }}
                  >
                    <Play size={11} fill="#ffffff" />
                    <span>{busy ? "Обработка..." : "Запустить распознавание"}</span>
                  </button>
                </div>

                {/* Node 5: Создание чертежей */}
                <div style={{ background: "#202123", borderRadius: 8, border: "1px solid #3f4144", padding: 8, display: "flex", flexDirection: "column", gap: 5, fontSize: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #383a3d", paddingBottom: 4 }}>
                    <span style={{ fontWeight: 800, color: "#ffffff" }}>Чертежи</span>
                    <Square size={13} color="#64748b" />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3, margin: "auto 0", fontSize: 9 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><Square size={10} color="#64748b" /> План этажа — не сформирован</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><Square size={10} color="#64748b" /> Разрезы — не сформированы</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><Square size={10} color="#64748b" /> Узлы — не сформированы</div>
                  </div>
                </div>

              </div>
            </div>

            {/* RIGHT: 3D VIEWPORT */}
            <div className="scan-studio-viewport" style={{ flex: 1, background: "#111213", display: "flex", flexDirection: "column", position: "relative", overflow: "hidden" }}>
              
              {/* Viewport Top Bar */}
              <div style={{ height: 32, background: "#252628", borderBottom: "1px solid #333436", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 10px" }}>
                <div style={{ display: "flex", gap: 4 }}>
                  {[
                    { id: "cloud", label: "Облако точек" },
                    { id: "rgb", label: "RGB" },
                    { id: "classes", label: "Классы" },
                    { id: "mesh", label: "Конструкции" },
                  ].map(tab => (
                    <button
                      key={tab.id}
                      onClick={() => setViewportTab(tab.id as any)}
                      style={{
                        background: viewportTab === tab.id ? "#f97316" : "transparent",
                        color: viewportTab === tab.id ? "#ffffff" : "#94a3b8",
                        border: "none", borderRadius: 12, padding: "2px 8px", fontSize: 10, fontWeight: 700, cursor: "pointer"
                      }}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#94a3b8" }}>
                  <button type="button" title={pointCloudVisible ? "Скрыть облако точек" : "Показать облако точек"} aria-label={pointCloudVisible ? "Скрыть облако точек" : "Показать облако точек"} aria-pressed={pointCloudVisible} onClick={() => setPointCloudVisible((value) => !value)} style={{ background: "transparent", border: 0, color: pointCloudVisible ? "#fdba74" : "#64748b", cursor: "pointer", padding: 3 }}><Eye size={13} /></button>
                  <button type="button" title={structuralModelVisible ? "Скрыть конструктивные кандидаты" : "Показать конструктивные кандидаты"} aria-label={structuralModelVisible ? "Скрыть конструктивные кандидаты" : "Показать конструктивные кандидаты"} aria-pressed={structuralModelVisible} onClick={() => setStructuralModelVisible((value) => !value)} style={{ background: "transparent", border: 0, color: structuralModelVisible ? "#fdba74" : "#64748b", cursor: "pointer", padding: 3 }}><Layers size={13} /></button>
                  <button type="button" title="Настройки проекта" aria-label="Настройки вида" onClick={() => navigateTo("settings", "settings", "settings_side")} style={{ background: "transparent", border: 0, color: "#94a3b8", cursor: "pointer", padding: 3 }}><Settings size={13} /></button>
                </div>
              </div>

              {/* Real 3D Three.js Viewport */}
              <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
                <Viewer3D
                  cloud={cloud}
                  elements={elements}
                  selectedElement={selectedElement}
                  groupPositions={new Float32Array(0)}
                  selectedElementPositions={new Float32Array(0)}
                  selectedElementSections={[new Float32Array(0), new Float32Array(0), new Float32Array(0)]}
                  pointSize={1.8}
                  colorMode={colorMode === "classes" ? "height" : colorMode}
                  showPlane={false}
                  section={null}
                  hideInternalHud={structuralModelVisible}
                  showBim={structuralModelVisible}
                  pointCloudVisible={pointCloudVisible}
                  measureModeActive={measureMode}
                  onToggleMeasureMode={setMeasureMode}
                  limitBoxActive={showLimitBox}
                  onToggleLimitBox={setShowLimitBox}
                  pointPickModeActive={pointPickMode}
                  onPointPicked={(point) => { setPickedPoint(point); setPointPickMode(false); }}
                  onPointPickMiss={() => setPickedPoint(null)}
                />

                {/* Floating Left 3D Tools Toolbar */}
                <div style={{ position: "absolute", left: 10, top: 10, display: "flex", flexDirection: "column", gap: 5, background: "rgba(27, 28, 30, 0.9)", backdropFilter: "blur(6px)", padding: 4, borderRadius: 6, border: "1px solid #3f4144", zIndex: 10 }}>
                  <button type="button" title="Указать точку в облаке" aria-label="Выбрать точку в облаке" aria-pressed={pointPickMode} onClick={() => { setPointPickMode((value) => !value); setPickedPoint(null); }} style={{ background: pointPickMode ? "#f97316" : "transparent", border: "none", color: "#fb923c", borderRadius: 4, cursor: "pointer", padding: 4 }}><Crosshair size={14} /></button>
                  <button title="3D Замер" onClick={() => setMeasureMode(!measureMode)} style={{ background: measureMode ? "#f97316" : "transparent", border: "none", color: "#ffffff", borderRadius: 4, cursor: "pointer", padding: 4 }}><Maximize2 size={14} /></button>
                  <button title="Limit Box" onClick={() => setShowLimitBox(!showLimitBox)} style={{ background: showLimitBox ? "#f97316" : "transparent", border: "none", color: "#ffffff", borderRadius: 4, cursor: "pointer", padding: 4 }}><Layers size={14} /></button>
                  <button title="Открыть панораму выбранного облака" aria-label="Панорама 360 градусов" disabled={!cloud} onClick={() => navigateTo("panoramas", "processing", "data")} style={{ background: "transparent", border: "none", color: cloud ? "#ffffff" : "#64748b", cursor: cloud ? "pointer" : "not-allowed", padding: 4 }}><Camera size={14} /></button>
                  {pointPickMode && <span role="status" style={{ color: "#fed7aa", fontSize: 10, alignSelf: "center" }}>Кликните точку облака</span>}
                  {pickedPoint && <span role="status" style={{ color: "#86efac", fontSize: 9, alignSelf: "center" }}>XYZ: {pickedPoint.map((value) => value.toFixed(3)).join(", ")} м</span>}
                </div>
              </div>

              {/* Viewport Bottom Colormap Toolbar */}
              <div style={{ height: 28, background: "#252628", borderTop: "1px solid #333436", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 8px" }}>
                <div style={{ display: "flex", gap: 4 }}>
                  {[
                    { id: "rgb", label: "RGB" },
                    { id: "intensity", label: "Интенсивность" },
                    { id: "classes", label: "Классы" },
                    { id: "height", label: "Высотная карта" },
                  ].map(mode => (
                    <button
                      key={mode.id}
                      onClick={() => setColorMode(mode.id as any)}
                      style={{
                        background: colorMode === mode.id ? "#f97316" : "#2a2b2d",
                        color: colorMode === mode.id ? "#ffffff" : "#94a3b8",
                        border: "1px solid #3f4144", borderRadius: 10, padding: "1px 7px", fontSize: 9.5, cursor: "pointer"
                      }}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
                <Maximize2 size={12} color="#94a3b8" style={{ cursor: "pointer" }} />
              </div>
            </div>

          </div>

          {/* BOTTOM SECTION: 3 CARDS (LOG, STATIONS + CAD PLAN, PROPERTIES) */}
          <div className="scan-studio-bottom" style={{ display: "flex", flex: 1, minHeight: 0, background: "#111213", padding: "8px 12px", gap: 10 }}>
            
            {/* CARD 1: ЖУРНАЛ ВЫПОЛНЕНИЯ */}
            <div style={{ flex: 1, background: "#1b1c1e", borderRadius: 8, border: "1px solid #333436", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #303235", paddingBottom: 4 }}>
                <span style={{ fontSize: 11.5, fontWeight: 800, color: "#ffffff" }}>Журнал выполнения</span>
                <span style={{ background: "#2a2b2d", color: "#fed7aa", padding: "1px 6px", borderRadius: 8, fontSize: 9 }}>{jobs.length} заданий</span>
              </div>
              <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6, fontSize: 9.5 }}>
                {dataLoading ? <div style={{ color: "#94a3b8", padding: 8 }}>Загрузка журнала заданий…</div> : recentJobs.length ? recentJobs.map((item) => (
                  <div key={item.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "#202123", padding: "4px 6px", borderRadius: 4 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ color: "#6b7280" }}>{item.updated_at ? new Date(item.updated_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "—"}</span>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", background: item.status === "succeeded" ? "#10b981" : item.status === "failed" ? "#ef4444" : "#f59e0b" }} />
                      <div>
                        <div style={{ fontWeight: 700, color: "#f8fafc" }}>{jobTypeLabel(item.type)}</div>
                        <div style={{ color: "#94a3b8", fontSize: 8.5 }}>{item.error || item.message || jobStatusLabel(item.status)}</div>
                      </div>
                    </div>
                    <span style={{ color: item.status === "failed" ? "#f87171" : "#fb923c", fontSize: 9 }}>{jobStatusLabel(item.status)}</span>
                  </div>
                )) : <div style={{ color: "#94a3b8", padding: 8 }}>Для проекта ещё нет записей о выполненных заданиях.</div>}
              </div>
            </div>

            {/* CARD 2: СТАНЦИИ + ПЛАН ЭТАЖА CAD */}
            <div className="scan-studio-cloud-plan" style={{ flex: 1.5, display: "flex", flexDirection: "column", gap: 8 }}>
              
              {/* Top subcard: Actual project clouds */}
              <div style={{ flex: 1, background: "#1b1c1e", borderRadius: 8, border: "1px solid #333436", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 11, fontWeight: 800, color: "#ffffff" }}>Облака проекта ({clouds.length})</span>
                  <span style={{ fontSize: 9.5, color: "#94a3b8" }}>данные из API</span>
                </div>
                <div style={{ display: "flex", gap: 6, flex: 1, overflowX: "auto", alignItems: "center" }}>
                  {clouds.length ? clouds.map((item) => {
                    const sel = cloud?.id === item.id;
                    return (
                      <div
                        key={item.id}
                        onClick={() => onCloudChange(item.id)}
                        title={`${item.name} · ${item.source_format} · ${item.point_count.toLocaleString("ru-RU")} точек`}
                        style={{
                          flex: 1, minWidth: 92, height: 52, background: sel ? "rgba(249, 115, 22, 0.2)" : "#2c2d30",
                          border: sel ? "1px solid #fb923c" : "1px solid #3f4144", borderRadius: 4,
                          display: "flex", flexDirection: "column", alignItems: "flex-start", justifyContent: "center", padding: "0 6px",
                          cursor: "pointer", fontSize: 9, color: sel ? "#fed7aa" : "#94a3b8"
                        }}
                      >
                        <span style={{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", width: "100%" }}>{item.name}</span>
                        <span>{item.source_format} · {item.status}</span>
                        <span>{item.point_count.toLocaleString("ru-RU")} точек</span>
                      </div>
                    );
                  }) : <span style={{ color: "#94a3b8", fontSize: 9 }}>{dataLoading ? "Загрузка облаков проекта…" : "В выбранном проекте нет импортированных облаков."}</span>}
                </div>
              </div>

              {/* Bottom subcard: План этажа (результат) */}
              <div style={{ flex: 1.3, background: "#1b1c1e", borderRadius: 8, border: "1px solid #333436", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 11, fontWeight: 800, color: "#ffffff" }}>Обзор кандидатов по координатам XY</span>
                  <button
                    onClick={() => {
                      if (cloud?.id) window.open(`/api/v1/clouds/${cloud.id}/elements.dxf`, "_blank");
                    }}
                    style={{ background: "#f97316", color: "#ffffff", border: "none", borderRadius: 4, padding: "2px 8px", fontSize: 9.5, fontWeight: 700, cursor: "pointer" }}
                  >
                    📐 Открыть в CAD
                  </button>
                </div>
                <div style={{ flex: 1, display: "flex", gap: 6, alignItems: "center" }}>
                  {/* Schematic Vector Drawing */}
                  <div style={{ flex: 1, height: "100%", background: "#111213", borderRadius: 4, border: "1px solid #303235", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
                    <svg width="100%" height="100%" viewBox="0 0 200 60" style={{ padding: 4 }} aria-label="Схема габаритов кандидатов по фактическим координатам">
                      {planElements.map((item) => {
                        const dx = Math.max(0, item.bbox.max[0] - item.bbox.min[0]);
                        const dy = Math.max(0, item.bbox.max[1] - item.bbox.min[1]);
                        const cx = (item.bbox.min[0] + item.bbox.max[0]) / 2;
                        const cy = (item.bbox.min[1] + item.bbox.max[1]) / 2;
                        const x = 8 + ((cx - planMinX) / planSpanX) * 184;
                        const y = 8 + ((planMaxY - cy) / planSpanY) * 44;
                        return <rect key={item.id} x={x - Math.max(1, (dx / planSpanX) * 92)} y={y - Math.max(1, (dy / planSpanY) * 22)} width={Math.max(2, (dx / planSpanX) * 184)} height={Math.max(2, (dy / planSpanY) * 44)} fill={elementColor(item.class_name)} fillOpacity={0.72} stroke="#111213" strokeWidth={0.35} />;
                      })}
                      {!planElements.length && <text x="100" y="32" textAnchor="middle" fill="#94a3b8" fontSize="7">Нет кандидатов с координатами</text>}
                    </svg>
                  </div>
                  {/* Legend */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 8.5, color: "#94a3b8" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: "#f59e0b" }}>■</span> Стены</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: "#10b981" }}>■</span> Колонны</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: "#38bdf8" }}>■</span> Балки</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: "#fb923c" }}>■</span> Трубы</div>
                  </div>
                </div>
              </div>

            </div>

            {/* CARD 3: СВОЙСТВА ОБЪЕКТА */}
            <div style={{ flex: 1.1, background: "#1b1c1e", borderRadius: 8, border: "1px solid #333436", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #303235", paddingBottom: 4 }}>
                <span style={{ fontSize: 11.5, fontWeight: 800, color: "#ffffff" }}>Свойства объекта</span>
                <div style={{ display: "flex", gap: 2 }}>
                  {["Общее", "Геометрия", "Атрибуты"].map((t, idx) => (
                    <span key={t} style={{ background: idx === 0 ? "#f97316" : "transparent", color: idx === 0 ? "#fff" : "#94a3b8", fontSize: 9, padding: "1px 5px", borderRadius: 4, cursor: "pointer" }}>{t}</span>
                  ))}
                </div>
              </div>

              {/* Object Header */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div>
                  <div style={{ fontWeight: 800, color: "#ffffff", fontSize: 12 }}>{activeObjName}</div>
                  <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
                    {selectedElement && <span style={{ background: "#f9731622", color: "#fdba74", padding: "1px 5px", borderRadius: 3, fontSize: 8.5, fontWeight: 700 }}>{activeObjClass}</span>}
                    {selectedElement && <span style={{ background: "#f59e0b22", color: "#fbbf24", padding: "1px 5px", borderRadius: 3, fontSize: 8.5, fontWeight: 700 }}>{selectedElement.review_status || "без статуса"}</span>}
                  </div>
                </div>
                <div style={{ width: 44, height: 44, borderRadius: 5, background: "#303235", display: "grid", placeItems: "center", color: "#fb923c" }}>
                  <Box size={24} />
                </div>
              </div>

              {/* Property Table */}
              <div style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 9.5, color: "#cbd5e1", marginTop: 2 }}>
                <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #303235", paddingBottom: 2 }}>
                  <span style={{ color: "#94a3b8" }}>Тип:</span>
                  <span>{selectedElement ? `${selectedElement.inferred ? "Выведенный кандидат" : selectedElement.measured ? "Измеренная геометрия" : "Кандидат распознавания"}` : "—"}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #303235", paddingBottom: 2 }}>
                  <span style={{ color: "#94a3b8" }}>Высота (AABB Z):</span>
                  <span>{bboxExtents ? formatMeters(bboxExtents[2]) : "—"}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #303235", paddingBottom: 2 }}>
                  <span style={{ color: "#94a3b8" }}>Размеры XY (AABB):</span>
                  <span>{bboxExtents ? `${formatMeters(bboxExtents[0])} × ${formatMeters(bboxExtents[1])} (AABB XY)` : "—"}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #303235", paddingBottom: 2 }}>
                  <span style={{ color: "#94a3b8" }}>Оценка модели:</span>
                  <span>{selectedElement ? `оценка модели ${Number.isFinite(selectedElement.confidence) ? `${(selectedElement.confidence * 100).toFixed(0)}%` : "не задана"} · ${selectedElement.confidence_kind || "не калибрована"}` : "—"}</span>
                </div>
                {selectedRoleSummary && <div style={{ borderBottom: "1px solid #303235", paddingBottom: 3 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                    <span style={{ color: "#94a3b8" }}>Конструктивная роль:</span>
                    <span style={{ color: selectedRoleSummary.status === "проверено человеком" ? "#86efac" : "#fdba74", textAlign: "right" }} title={selectedRoleSummary.status}>{selectedRoleSummary.role} · {selectedRoleSummary.status}</span>
                  </div>
                  {selectedRoleSummary.columnSupport && <div style={{ marginTop: 3, color: "#fdba74", lineHeight: 1.3 }} title="Геометрическая проверка не подтверждает фактическое опирание или наличие кранового рельса.">{selectedRoleSummary.columnSupport}</div>}
                </div>}
              </div>

              {/* Buttons */}
              <div style={{ display: "flex", gap: 6, marginTop: "auto" }}>
                <button
                  onClick={() => {
                    if (selectedElement) setInspectingElement(selectedElement);
                  }}
                  style={{ flex: 1, background: "#2a2b2d", border: "1px solid #3f4144", color: "#fed7aa", borderRadius: 4, padding: "5px 0", fontSize: 9.5, cursor: "pointer", fontWeight: 700 }}
                >
                  👁 На модели
                </button>
                <button
                  disabled
                  title="Добавление отдельных элементов в чертёж ещё не подключено"
                  style={{ flex: 1.2, background: "#303235", color: "#94a3b8", border: "none", borderRadius: 4, padding: "5px 0", fontSize: 9.5, cursor: "not-allowed", fontWeight: 700 }}
                >
                  ➕ В чертёж
                </button>
              </div>

            </div>

          </div>

        </div> : activeWorkspace === "registration" ? <section className="scan-studio-registration-page" aria-label="Сшивка станций">
          <SplitScreenRegistrationView clouds={clouds} initialSourceCloudId={cloud?.id} onClose={() => navigateTo("processing", "processing", "processing")} />
        </section> : <section aria-label="Рабочий раздел" style={{ flex: 1, minWidth: 0, overflow: "auto", padding: 20, background: "#111213" }}>
          {(() => {
            const card: React.CSSProperties = { background: "#1b1c1e", border: "1px solid #333436", borderRadius: 9, padding: 16, display: "flex", flexDirection: "column", gap: 10 };
            const actionButton: React.CSSProperties = { background: "#f97316", color: "#fff", border: 0, borderRadius: 5, padding: "9px 12px", fontSize: 12, fontWeight: 700, cursor: exportBusy ? "wait" : "pointer", opacity: exportBusy || !cloud ? 0.55 : 1 };
            const quietButton: React.CSSProperties = { ...actionButton, background: "#2a2b2d", border: "1px solid #514136", color: "#fed7aa" };
            const title = ({ projects: "Проекты и облака", recognition: "Результаты распознавания", drawings: "Чертежи цеха", bim: "Экспорт BIM", reports: "Отчёты проекта", settings: "Сведения о проекте", panoramas: "Панорамы стоянок 360°" } as Record<string, string>)[activeWorkspace] || "Рабочий раздел";
            const stat = (label: string, value: React.ReactNode) => <div key={label} style={{ ...card, gap: 5 }}><span style={{ fontSize: 11, color: "#94a3b8" }}>{label}</span><strong style={{ fontSize: 20, color: "#fff" }}>{value}</strong></div>;
            const exportButton = (label: string, action: () => Promise<unknown>, secondary = false) => <button type="button" key={label} disabled={!cloud || exportBusy} onClick={() => void runExport(label, action)} style={secondary ? quietButton : actionButton}>{exportBusy ? "Готовлю файл…" : label}</button>;
            return <>
              <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 16 }}>
                <div><h1 style={{ margin: 0, fontSize: 21, color: "#fff" }}>{title}</h1><p style={{ margin: "6px 0 0", color: "#94a3b8", fontSize: 12 }}>{project?.name || "Проект не выбран"} · {cloud?.name || "Облако не выбрано"}</p></div>
                {activeWorkspace === "projects" && <button type="button" style={actionButton} onClick={() => { setImportDialogError(null); setShowImportDialog(true); }}>+ Добавить скан</button>}
              </header>
              {activeWorkspace === "projects" && <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 12 }}>
                <div style={card}><h2 style={{ margin: 0, fontSize: 14 }}>Текущий проект</h2><label style={{ display: "grid", gap: 6, color: "#94a3b8", fontSize: 11 }}>Выбрать проект<select value={project?.id || ""} onChange={(event) => onProjectChange(event.target.value)} style={{ padding: 9, background: "#111213", color: "#fff", border: "1px solid #3f4144", borderRadius: 5 }}>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><p style={{ margin: 0, color: "#cbd5e1", fontSize: 12 }}>{clouds.length} облаков · {elements.length.toLocaleString("ru-RU")} кандидатов</p></div>
                <div style={card}><h2 style={{ margin: 0, fontSize: 14 }}>Облака проекта · {dataSourceFilter === "all" ? "все" : dataSourceFilter === "ready" ? "готовые" : "FARO / RCS"}</h2>{visibleClouds.length ? visibleClouds.map((item) => <button type="button" key={item.id} onClick={() => onCloudChange(item.id)} style={{ ...quietButton, textAlign: "left", borderColor: cloud?.id === item.id ? "#fb923c" : "#3f4144" }}><strong>{item.name}</strong><br/><span style={{ fontSize: 10 }}>{item.source_format} · {item.status} · {item.point_count.toLocaleString("ru-RU")} точек</span></button>) : <p style={{ color: "#94a3b8", fontSize: 12 }}>{dataLoading ? "Загружаю облака…" : "Облаков с выбранным фильтром нет."}</p>}</div>
                {onCreateProject && <div style={card}><h2 style={{ margin: 0, fontSize: 14 }}>Новый проект</h2><button type="button" style={quietButton} onClick={() => { const name = window.prompt("Название проекта"); if (name?.trim()) void onCreateProject(name.trim()); }}>Создать проект</button></div>}
              </div>}
              {activeWorkspace === "recognition" && <>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginBottom: 12 }}>{stat("Всего элементов", elements.length.toLocaleString("ru-RU"))}{stat("Колонны", columnsCount.toLocaleString("ru-RU"))}{stat("Балки и подкрановые балки", beamsCount.toLocaleString("ru-RU"))}{stat("Фермы и связи", elements.filter((item) => ["truss", "brace"].includes(item.class_name)).length.toLocaleString("ru-RU"))}</div>
                <div style={card}><h2 style={{ margin: 0, fontSize: 14 }}>Кандидаты распознавания</h2><p style={{ margin: 0, color: "#94a3b8", fontSize: 12 }}>Геометрические результаты — кандидаты. Физический тип и точность считаются подтверждёнными только после независимой разметки.</p><button type="button" style={actionButton} onClick={() => setShowRecognitionReview(true)} disabled={!cloud}>Открыть проверку и разметку</button></div>
              </>}
              {activeWorkspace === "drawings" && <>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10, marginBottom: 12 }}>{stat("Кандидаты с координатами", planElements.length.toLocaleString("ru-RU"))}{stat("Колонны", columnsCount.toLocaleString("ru-RU"))}{stat("Балки / подкрановые", beamsCount.toLocaleString("ru-RU"))}{stat("Единицы проекта", project?.units || "не заданы")}</div>
                <div style={card}><h2 style={{ margin: 0, fontSize: 14 }}>Выпустить чертежи</h2><p style={{ margin: 0, color: "#94a3b8", fontSize: 12 }}>Чертежи формируются по текущим кандидатам. Непроверенная геометрия не является исполнительной съёмкой.</p><div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>{exportButton("План колонн · DXF", () => api.exportStructuralPlanDxf(cloud!.id, "columns"))}{exportButton("План колонн · PDF", () => api.exportStructuralPlanPdf(cloud!.id, "columns"), true)}{exportButton("Подкрановые балки · DXF", () => api.exportStructuralPlanDxf(cloud!.id, "crane_girders"))}{exportButton("Подкрановые балки · PDF", () => api.exportStructuralPlanPdf(cloud!.id, "crane_girders"), true)}{exportButton("Альбом СПДС · PDF", () => api.exportSpdsAlbumPdf(cloud!.id))}{exportButton("Альбом СПДС · ZIP", () => api.exportSpdsAlbum(cloud!.id), true)}{exportButton("Элементы · DXF", () => api.exportElementsDxf(cloud!.id), true)}</div></div>
              </>}
              {activeWorkspace === "bim" && <>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10, marginBottom: 12 }}>{stat("Объекты для модели", elements.length.toLocaleString("ru-RU"))}{stat("Колонны", columnsCount.toLocaleString("ru-RU"))}{stat("Балки", beamsCount.toLocaleString("ru-RU"))}</div>
                <div style={card}><h2 style={{ margin: 0, fontSize: 14 }}>Экспорт модели</h2><p style={{ margin: 0, color: "#94a3b8", fontSize: 12 }}>IFC и JSON доступны для передачи в BIM-процессы. Проверка открытия в Revit выполняется отдельно.</p><div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{exportButton("Модель IFC", () => api.exportBim(cloud!.id, "ifc"))}{exportButton("Модель JSON", () => api.exportBim(cloud!.id, "json"), true)}{exportButton("Элементы DXF", () => api.exportElementsDxf(cloud!.id), true)}</div></div>
              </>}
              {activeWorkspace === "reports" && <>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10, marginBottom: 12 }}>{stat("Записи заданий", jobs.length.toLocaleString("ru-RU"))}{stat("Завершено", jobs.filter((item) => item.status === "succeeded").length)}{stat("Ошибки", jobs.filter((item) => item.status === "failed").length)}{stat("Размечено независимо", Object.values(independentReviewState).filter((state) => state === "labeled").length)}</div>
                <div style={card}><h2 style={{ margin: 0, fontSize: 14 }}>Последние задания</h2>{recentJobs.length ? recentJobs.map((item) => <div key={item.id} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "8px 0", borderBottom: "1px solid #303235", fontSize: 11 }}><span>{jobTypeLabel(item.type)} · {item.message || item.error || "без сообщения"}</span><strong style={{ color: item.status === "succeeded" ? "#34d399" : item.status === "failed" ? "#f87171" : "#fdba74" }}>{jobStatusLabel(item.status)}</strong></div>) : <p style={{ color: "#94a3b8", fontSize: 12 }}>Для проекта ещё нет заданий.</p>}</div>
              </>}
              {activeWorkspace === "settings" && <div style={{ ...card, maxWidth: 720 }}><h2 style={{ margin: 0, fontSize: 14 }}>Текущая конфигурация проекта</h2><div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: 9, fontSize: 12 }}><span style={{ color: "#94a3b8" }}>Проект</span><strong>{project?.name || "не выбран"}</strong><span style={{ color: "#94a3b8" }}>Единицы</span><strong>{project?.units || "не заданы"}</strong><span style={{ color: "#94a3b8" }}>Облако</span><strong>{cloud?.name || "не выбрано"}</strong><span style={{ color: "#94a3b8" }}>Формат источника</span><strong>{cloud?.source_format || "—"}</strong><span style={{ color: "#94a3b8" }}>Точек в облаке</span><strong>{cloud?.point_count.toLocaleString("ru-RU") || "—"}</strong></div></div>}
              {activeWorkspace === "panoramas" && <div style={{ ...card, minHeight: 570 }}><p style={{ margin: 0, color: "#94a3b8", fontSize: 12 }}>Просмотр использует панораму по точкам или привязанное фото; замер сообщит, если глубины облака недостаточно для надёжного результата.</p><BubblePanoramaViewer cloudId={cloud?.id || null} /></div>}
              {exportMessage && <p role="status" style={{ color: exportMessage.includes(": файл") ? "#86efac" : "#fecaca", background: "#1b1c1e", border: "1px solid #3f4144", padding: 10, borderRadius: 6, fontSize: 12 }}>{exportMessage}</p>}
            </>;
          })()}
        </section>}

      </div>

      {/* GOST/profile inspection modal */}
      {inspectingElement && (
        <GostProfileInspectorModal
          element={inspectingElement}
          onClose={() => setInspectingElement(null)}
                  />
      )}

      {showImportDialog && (
        <div className="recognition-review-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !busy) setShowImportDialog(false);
        }}>
          <section className="recognition-review-dialog" role="dialog" aria-modal="true" aria-labelledby="scan-import-title" style={{ width: "min(560px, calc(100vw - 28px))", height: "auto", maxHeight: "calc(100vh - 32px)", padding: 18 }}>
            <header className="recognition-review-header">
              <div>
                <div id="scan-import-title" className="recognition-review-title">Импорт облака точек</div>
                <div className="recognition-review-subtitle">FARO RCS и проекты ReCap RCP открываются по локальному пути.</div>
              </div>
              <button type="button" className="recognition-review-close" onClick={() => setShowImportDialog(false)} disabled={busy} aria-label="Закрыть импорт"><X size={18} /></button>
            </header>
            <label style={{ display: "grid", gap: 6, margin: "16px 0 10px", color: "#e2e8f0", fontSize: 12 }}>
              Путь к файлу на этом компьютере
              <input
                autoFocus
                value={importPathValue}
                disabled={busy}
                onChange={(event) => setImportPathValue(event.target.value)}
                placeholder={'C:\\Сканы\\Станция 01.rcs или C:\\Проект\\Проект.rcp'}
                aria-label="Локальный путь к файлу сканирования"
                style={{ background: "#202123", border: "1px solid #515357", borderRadius: 5, color: "#fff", padding: "10px 11px", fontSize: 12, width: "100%", boxSizing: "border-box" }}
              />
            </label>
            <label style={{ display: "flex", gap: 8, alignItems: "flex-start", color: "#e2e8f0", fontSize: 11, margin: "12px 0" }}>
              <input type="checkbox" checked={keepFullResolution} disabled={busy} onChange={(event) => setKeepFullResolution(event.target.checked)} />
              <span><strong>Сохранить все точки без прореживания</strong><br /><span style={{ color: "#94a3b8" }}>Рекомендуется для FARO и точных обмеров. Требуется достаточно свободного места на диске.</span></span>
            </label>
            {importDialogError && <div role="alert" style={{ color: "#fecaca", background: "#7f1d1d55", padding: 9, borderRadius: 5, fontSize: 11 }}>{importDialogError}</div>}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
              <button type="button" onClick={() => setShowImportDialog(false)} disabled={busy} style={{ background: "#303235", color: "#e2e8f0", border: "1px solid #515357", borderRadius: 5, padding: "8px 12px", cursor: "pointer" }}>Отмена</button>
              {canCancelImport && <button
                type="button"
                disabled={cancelPending || !onCancelImport}
                onClick={async () => {
                  setCancelPending(true);
                  try {
                    await onCancelImport?.();
                  } catch (error) {
                    setImportDialogError(error instanceof Error ? error.message : String(error));
                    setCancelPending(false);
                  }
                }}
                style={{ background: "#7f1d1d", color: "#fee2e2", border: "1px solid #b91c1c", borderRadius: 5, padding: "8px 12px", fontWeight: 700, cursor: "pointer" }}
              >{cancelPending ? "Отмена запрошена…" : "Отменить импорт"}</button>}
              <button
                type="button"
                disabled={busy || !importPathValue.trim() || !onImportPath}
                onClick={async () => {
                  setImportDialogError(null);
                  try {
                    await onImportPath?.(importPathValue.trim(), keepFullResolution ? 0 : undefined);
                    setImportPathValue("");
                    setShowImportDialog(false);
                  } catch (error) {
                    setImportDialogError(error instanceof Error ? error.message : String(error));
                  }
                }}
                style={{ background: "#f97316", color: "#fff", border: 0, borderRadius: 5, padding: "8px 12px", fontWeight: 800, cursor: busy ? "wait" : "pointer", opacity: busy || !importPathValue.trim() ? 0.55 : 1 }}
              >
                {busy ? "Импорт выполняется…" : "Импортировать путь"}
              </button>
              <label style={{ background: "#2a2b2d", color: "#fed7aa", border: "1px solid #514136", borderRadius: 5, padding: "8px 12px", fontSize: 11, fontWeight: 700, cursor: busy ? "wait" : "pointer", opacity: busy ? 0.5 : 1 }}>
                Загрузить файл
                <input
                  type="file"
                  accept=".e57,.las,.laz,.ply,.pcd,.pts,.xyz,.txt,.csv"
                  disabled={busy || !onUploadScan}
                  style={{ display: "none" }}
                  onChange={async (event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    setImportDialogError(null);
                    try {
                      await onUploadScan?.(file, keepFullResolution ? 0 : undefined);
                      setShowImportDialog(false);
                    } catch (error) {
                      setImportDialogError(error instanceof Error ? error.message : String(error));
                    } finally {
                      event.target.value = "";
                    }
                  }}
                />
              </label>
            </div>
          </section>
        </div>
      )}

      {showRecognitionReview && (
        <div className="recognition-review-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setShowRecognitionReview(false);
        }}>
          <section className="recognition-review-dialog" role="dialog" aria-modal="true" aria-labelledby="recognition-review-title">
            <header className="recognition-review-header">
              <div>
                <div id="recognition-review-title" className="recognition-review-title">Независимая разметка конструкций</div>
                <div className="recognition-review-subtitle">Эталон задаёт проверяющий. Предложенный класс модели не становится меткой автоматически.</div>
              </div>
              <div className="recognition-review-header-actions">
                <button
                  type="button"
                  className="learning-manifest-toggle"
                  aria-pressed={showLearningManifest}
                  onClick={() => setShowLearningManifest((visible) => !visible)}
                >
                  {showLearningManifest ? "К разметке" : `Обучение · ${learningManifest?.eligible_sample_count ?? "…"}`}
                </button>
                <button type="button" className="recognition-review-close" onClick={() => setShowRecognitionReview(false)} aria-label="Закрыть разметку"><X size={18} /></button>
              </div>
            </header>
            {showLearningManifest ? <section className="learning-manifest-panel" aria-label="Каталог обучающих примеров">
              <div className="learning-manifest-panel-heading">
                <div>
                  <h2>Каталог проверенных примеров</h2>
                  <p>Подготовка набора для будущей оценки модели. Экспорт не запускает обучение и не меняет активную модель.</p>
                </div>
                <strong>{learningManifest?.eligible_sample_count ?? "—"} готово</strong>
              </div>
              {learningManifest && <>
                <div className="learning-manifest-class-counts">
                  {Object.entries(learningManifest.class_counts).length
                    ? Object.entries(learningManifest.class_counts).map(([name, count]) => <span key={name}>{classLabel(name)}: {count}</span>)
                    : <span>Пока нет независимых обучающих меток.</span>}
                </div>
                {Object.keys(learningManifest.excluded_sample_counts).length > 0 && <p className="learning-manifest-muted">
                  Исключено устаревших или неподтверждённых примеров: {Object.values(learningManifest.excluded_sample_counts).reduce((sum, count) => sum + count, 0)}.
                </p>}
                <p className="learning-manifest-muted">
                  В набор входят только проверенные элементы с актуальными точками, независимым классом и совпадающим физическим ID.
                </p>
              </>}
              {learningManifestError && <p className="learning-manifest-error" role="alert">{learningManifestError}</p>}
              {learningManifestExport && <p className="learning-manifest-success" role="status">
                Сохранено: {learningManifestExport.relative_path}. Обучение не запускалось.
              </p>}
              <button
                type="button"
                className="learning-manifest-export"
                onClick={exportLearningManifest}
                disabled={learningManifestBusy || !learningManifest || learningManifest.eligible_sample_count < 1}
              >
                {learningManifestBusy ? "Экспорт…" : "Экспортировать манифест…"}
              </button>
            </section> : !cloud ? <div className="recognition-review-empty">Сначала выберите облако точек.</div> : <div className="recognition-review-body">
              <aside className="recognition-review-candidates" aria-label="Кандидаты для проверки">
                <div className="recognition-review-filters">
                  <input value={recognitionQuery} onChange={(event) => { setRecognitionQuery(event.target.value); setRecognitionVisibleCount(100); }} placeholder="Поиск по ID или классу" aria-label="Поиск кандидатов" />
                  <select value={recognitionKind} onChange={(event) => { setRecognitionKind(event.target.value as typeof recognitionKind); setRecognitionVisibleCount(100); }} aria-label="Фильтр кандидатов">
                    <option value="all">Все элементы</option><option value="column">Колонны</option><option value="structural">Балка / ферма / связь</option>
                  </select>
                  <span className="recognition-review-count">{recognitionCandidates.length.toLocaleString("ru-RU")} кандидатов</span>
                </div>
                <div className="recognition-review-list">
                  {recognitionCandidates.slice(0, recognitionVisibleCount).map((element) => {
                    const { state: reviewState, label: reviewLabel } = recognitionReviewState(independentReviewState[element.id]);
                    return <button type="button" key={element.id} className={`recognition-review-row${selectedElement?.id === element.id ? " is-selected" : ""}`} onClick={() => onSelectElement(element)}>
                      <span className="recognition-review-row-class">{classLabel(element.class_name)}</span><span className="recognition-review-row-id">{element.id}</span><span className={`recognition-review-row-state is-${reviewState}`}>{reviewLabel}</span>
                    </button>;
                  })}
                  {!recognitionCandidates.length && <div className="recognition-review-empty">{elements.length ? "По вашему запросу ничего не найдено." : "В облаке пока нет кандидатов. Запустите распознавание."}</div>}
                  {recognitionVisibleCount < recognitionCandidates.length && <button type="button" className="recognition-review-more" onClick={() => setRecognitionVisibleCount((count) => count + 100)}>Показать ещё {Math.min(100, recognitionCandidates.length - recognitionVisibleCount)}</button>}
                </div>
              </aside>
              <main className="recognition-review-form">
                {!selectedElement ? <div className="recognition-review-empty">Выберите кандидата слева, чтобы внести независимую метку.</div> : selectedElement.class_name === "column" ? <>
                  <ColumnAnnotationPanel key={`${cloud.id}:${selectedElement.id}`} cloudId={cloud.id} element={selectedElement} busy={busy} surfaceAnalysis={null} columns={elements.filter((item) => item.class_name === "column")} onSelectColumn={onSelectElement} onAnnotationSaved={(annotation) => setIndependentReviewState((current) => ({ ...current, [annotation.element_id]: annotation.state }))} />
                  <button
                    type="button"
                    className="recognition-column-types-toggle"
                    aria-expanded={showColumnTypes}
                    aria-controls="recognition-column-types"
                    onClick={() => setShowColumnTypes((visible) => !visible)}
                  >
                    {showColumnTypes ? "Скрыть сравнение типов" : "Сравнить повторяющиеся типы колонн"}
                  </button>
                  {showColumnTypes && <div id="recognition-column-types">
                    <ColumnTypesPanel cloudId={cloud.id} projectId={project?.id} elements={elements} selected={selectedElement} busy={busy} onSelect={onSelectElement} />
                  </div>}
                </> : <ElementAnnotationPanel key={`${cloud.id}:${selectedElement.id}`} cloudId={cloud.id} element={selectedElement} busy={busy} onAnnotationSaved={(annotation) => setIndependentReviewState((current) => ({ ...current, [annotation.element_id]: annotation.state }))} />}
              </main>
            </div>}
          </section>
        </div>
      )}

    </div>
  );
};
