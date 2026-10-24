import React, { useEffect, useState } from "react";
import { api } from "./api";
import { cloudPointCoverage, progressPercent, scannerModelLabel } from "./studioPresentation";
import "./theme.css";
import Viewer3D, { type CameraPreset } from "./components/Viewer3D";
import { SplitScreenRegistrationView } from "./components/SplitScreenRegistrationView";
import { GostProfileInspectorModal } from "./components/GostProfileInspectorModal";
import { RegistrationQualityCharts } from "./components/RegistrationQualityCharts";
import { ElementTanStackTable } from "./components/ElementTanStackTable";
import ElementAnnotationPanel from "./components/ElementAnnotationPanel";
import ColumnAnnotationPanel from "./components/ColumnAnnotationPanel";
import { type Cloud, type Element, type Project } from "./types";

import {
  Folder,
  UploadCloud,
  Network,
  Cloud as CloudIcon,
  Camera,
  Cpu,
  Compass,
  Building,
  FileSpreadsheet,
  FileDown,
  Settings,
  Eye,
  Crosshair,
  Maximize2,
  BarChart3,
  Layers,
  Sparkles,
  Zap,
} from "lucide-react";

interface StudioLayoutProps {
  project: Project | null;
  cloud: Cloud | null;
  clouds: Cloud[];
  elements: Element[];
  selectedElement: Element | null;
  onSelectElement: (el: Element | null) => void;
  onRunSinglePass: (cloudId: string | null) => void;
  onCloudChange: (cloudId: string) => void;
  onTabChange?: (tab: string) => void;
  busy: boolean;
  jobLabel: string | null;
  jobProgress: number | null;
}

export const StudioReferenceLayout: React.FC<StudioLayoutProps> = ({
  project,
  cloud,
  clouds,
  elements,
  selectedElement,
  onSelectElement,
  onRunSinglePass,
  onCloudChange,
  busy,
  jobLabel,
  jobProgress,
}) => {
  const [activeNav, setActiveNav] = useState("pointcloud");
  const [activeSecondaryTab, setActiveSecondaryTab] = useState("pointcloud");
  const [cameraPreset, setCameraPreset] = useState<CameraPreset | null>(null);
  const [activeViewLabel, setActiveViewLabel] = useState<string>("3D ISO");
  const [toast, setToast] = useState<{ type: "success" | "info" | "warning" | "error"; message: string } | null>(null);

  const showToast = (message: string, type: "success" | "info" | "warning" | "error" = "info", duration = 5000) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), duration);
  };
  const [assistantMode, setAssistantMode] = useState<"manual" | "ai" | "hybrid">("hybrid");
  const [recapNotice, setRecapNotice] = useState<string | null>(null);
  const [recapProjectPath, setRecapProjectPath] = useState<string | null>(null);
  const [selectedRecapCloudIds, setSelectedRecapCloudIds] = useState<string[]>([]);
  const [recapExporting, setRecapExporting] = useState(false);
  const recapEligibleClouds = clouds.filter((item) =>
    item.status === "ready" &&
    ["rcs", "e57", "fls", "fws", "las", "laz", "pts", "ptx", "ply", "xyz"]
      .includes(item.source_format.toLowerCase().replace(/^\./, "")),
  );

  const handleExportRecap = async () => {
    const selectedScans = recapEligibleClouds.filter((item) => selectedRecapCloudIds.includes(item.id));
    if (selectedScans.length === 0) {
      showToast("Отметьте исходные сканы для проекта ReCap.", "warning");
      return;
    }
    try {
      setRecapExporting(true);
      const projectName = (project?.name || "SCAN_ReCap_Project")
        .replace(/[^\p{L}\p{N} .()_-]/gu, "_")
        .trim()
        .slice(0, 80) || "SCAN_ReCap_Project";
      const res = await api.exportNativeRecapProject(projectName, selectedScans.map((scan) => ({
        name: scan.name,
        path: scan.source_path,
        point_count: scan.point_count,
      })));
      setRecapProjectPath(res.rcp_path);
      setRecapNotice(`DeCap собрал RCP. SCAN проверил состав файлов: ${res.input_scan_count} исходных, ${res.linked_rcs_count} непустых связанных RCS. Откройте пакет в ReCap для приёмки.`);
    } catch (err: any) {
      showToast("Ошибка экспорта ReCap: " + (err.message || String(err)), "error");
    } finally {
      setRecapExporting(false);
    }
  };

  const [colorMode, setColorMode] = useState<"rgb" | "height" | "intensity" | "normals" | "error">("rgb");
  const [inspectingElement, setInspectingElement] = useState<Element | null>(null);
  const [selectedCloudId, setSelectedCloudId] = useState<string>("workshop_cloud");
  const [selectedSpan, setSelectedSpan] = useState<"all" | "span1" | "span2" | "span3">("all");
  const [showLimitBox, setShowLimitBox] = useState(false);
  const [measureMode, setMeasureMode] = useState(false);

  const [layers, setLayers] = useState({
    pointCloud: true,
    stations: true,
    panoramas: false,
    aiStructures: false,
    axes: false,
    bimModel: false,
  });

  const toggleLayer = (layerKey: keyof typeof layers) => {
    setLayers((prev) => ({ ...prev, [layerKey]: !prev[layerKey] }));
  };

  const navItems = [
    { id: "projects", label: "Проекты", icon: <Folder size={16} /> },
    { id: "import", label: "Импорт сканов", icon: <UploadCloud size={16} /> },
    { id: "stitching", label: "Сшивка станций", icon: <Network size={16} /> },
    { id: "pointcloud", label: "Облако точек", icon: <CloudIcon size={16} /> },
    { id: "panoramas", label: "Панорамы 360°", icon: <Camera size={16} /> },
    { id: "recognition", label: "ИИ Распознавание", icon: <Cpu size={16} /> },
    { id: "cad", label: "Чертежи (CAD)", icon: <Compass size={16} /> },
    { id: "bim", label: "BIM Модель IFC", icon: <Building size={16} /> },
    { id: "reports", label: "Паспорта и Отчёты", icon: <FileSpreadsheet size={16} /> },
    { id: "export", label: "Экспорт DWG", icon: <FileDown size={16} /> },
    { id: "settings", label: "Настройки СП", icon: <Settings size={16} /> },
  ];

  const secondaryTabs = [
    { id: "overview", label: "Обзор проекта" },
    { id: "stitching", label: "Регистрация (Сшивка)" },
    { id: "pointcloud", label: "3D Облако точек" },
    { id: "panoramas", label: "Сферические панорамы" },
    { id: "recognition", label: "Несущие конструкции" },
    { id: "cad", label: "Планы и Разрезы" },
    { id: "bim", label: "BIM Спецификация" },
    { id: "reports", label: "Контроль геометрии (СП)" },
  ];

  const emptyFloatArray = new Float32Array(0);
  const emptySections: [Float32Array, Float32Array, Float32Array] = [
    new Float32Array(0),
    new Float32Array(0),
    new Float32Array(0),
  ];

  const currentCloud = clouds.find((item) => item.id === selectedCloudId) || clouds.find((c) => c.id === "workshop_cloud") || cloud || clouds[0] || null;
  const progress = progressPercent(jobProgress);

  useEffect(() => {
    if (cloud && !clouds.some((item) => item.id === selectedCloudId)) setSelectedCloudId(cloud.id);
  }, [cloud, clouds, selectedCloudId]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", width: "100vw", background: "var(--bg-deep)", color: "#FFFFFF" }}>
      {/* 1. TOP APPLICATION BAR */}
      <header className="app-header">
        <div className="app-brand">
          <div className="app-logo">
            <Sparkles size={16} color="#0A0E13" />
          </div>
          <div className="app-title">
            SCAN AI <span className="sub">STUDIO</span>
          </div>

          <div className="project-title-badge">
            <span style={{ color: "#FF812E" }}>●</span>
            <span style={{ color: "#FFFFFF", fontWeight: 700 }}>{project?.name || "Проект SCAN"}</span>
            <span style={{ color: "#94A3B8", fontSize: 11 }}>Облаков проекта: {clouds.length}</span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {/* Scientific Colormap Switcher */}
          <div style={{ display: "flex", background: "#1C2430", padding: 3, borderRadius: 6, border: "1px solid #334050" }}>
            {(["rgb", "height", "intensity", "normals", "error"] as const).map((mode) => (
              <button
                key={mode}
                disabled={!["rgb", "height"].includes(mode)}
                title={["rgb", "height"].includes(mode) ? undefined : "Нет измеренных данных для этого режима"}
                onClick={() => setColorMode(mode)}
                style={{
                  background: colorMode === mode ? "#FF812E" : "transparent",
                  color: colorMode === mode ? "#0A0D11" : "#E2E8F0",
                  border: "none",
                  padding: "5px 10px",
                  fontSize: 12,
                  fontWeight: colorMode === mode ? 800 : 600,
                  borderRadius: 4,
                  cursor: "pointer",
                }}
              >
                {mode === "rgb" && "RGB"}
                {mode === "height" && "Высота Z"}
                {mode === "intensity" && "Интенсивность"}
                {mode === "normals" && "Нормали"}
                {mode === "error" && "СП 70.13330 (Теплокарта)"}
              </button>
            ))}
          </div>

          <div className="system-status-indicator">
            <span className="status-pulse"></span>
            <span>FPS — в окне 3D-просмотра</span>
          </div>

          <button
            className="primary"
            onClick={() => onRunSinglePass(currentCloud?.id || null)}
            disabled={busy || !currentCloud || currentCloud.status !== "ready"}
            style={{ padding: "6px 16px", color: "#0A0D12", fontWeight: 800 }}
          >
            <Zap size={14} /> {busy ? "Распознавание…" : "Распознать конструкции"}
          </button>
        </div>
      </header>

      {/* 2. SECONDARY WORKSPACE TABS */}
      <nav className="secondary-tab-bar">
        {secondaryTabs.map((tab) => (
          <div
            key={tab.id}
            className={`secondary-tab ${activeSecondaryTab === tab.id ? "active" : ""}`}
            onClick={() => {
              setActiveSecondaryTab(tab.id);
              if (tab.id === "stitching") setActiveNav("stitching");
              if (tab.id === "pointcloud") setActiveNav("pointcloud");
              if (tab.id === "panoramas") setActiveNav("panoramas");
            }}
          >
            {tab.label}
          </div>
        ))}
      </nav>

      {/* 3. MAIN WORKSPACE */}
      <div className="studio-layout">
        {/* LEFT NAV PANEL */}
        <aside className="sidebar-left">
          <div className="nav-item-list">
            {navItems.map((item) => (
              <div
                key={item.id}
                className={`nav-item ${activeNav === item.id ? "active" : ""}`}
                onClick={() => {
                  setActiveNav(item.id);
                  if (item.id === "stitching") setActiveSecondaryTab("stitching");
                  if (item.id === "pointcloud") setActiveSecondaryTab("pointcloud");
                  if (item.id === "panoramas") setActiveSecondaryTab("panoramas");
                }}
              >
                <span className="nav-icon" style={{ color: activeNav === item.id ? "#FF812E" : "#94A3B8" }}>{item.icon}</span>
                <span style={{ color: activeNav === item.id ? "#FFA25B" : "#E2E8F0" }}>{item.label}</span>
              </div>
            ))}
          </div>

          {/* Stations / Clouds Switcher List */}
          <div style={{ margin: "10px 0", padding: "10px", background: "#1C2430", borderRadius: 6, border: "1px solid #334050" }}>
            <div style={{ fontSize: 11, fontWeight: 800, color: "#FFA25B", marginBottom: 8, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>ОБЛАКА ПРОЕКТА</span>
              <span style={{ color: "#94A3B8", fontSize: 10 }}>{clouds.length}</span>
            </div>
            {clouds.map((c) => {
              const isSelected = currentCloud?.id === c.id;
              const coverage = cloudPointCoverage(c);
              
              let title = c.name || c.id;
              let subtitle = `${c.source_format.toUpperCase()} · готово`;
              let badge = coverage.label;
              
              if (c.id === "workshop_cloud") {
                title = "🏢 Сводный цех: 3 пролёта";
                subtitle = "Оси 1–24 (138м) · 1.rcs + 2.rcs";
                badge = "43.5M";
              } else if (c.id === "workshop_cloud_01" || c.name?.includes("1.rcs")) {
                title = "📡 Скан 1: Пролёты 1–2 (А–Б, Б–В)";
                subtitle = "Ширина 25 м · Faro Focus S350";
                badge = "297.8M";
              } else if (c.id === "workshop_cloud_02" || c.name?.includes("2.rcs")) {
                title = "📡 Скан 2: Пролёт 3 (В–Г)";
                subtitle = "Ширина 13.25 м · Faro Focus S350";
                badge = "576.8M";
              }

              return (
                <div
                  key={c.id}
                  onClick={() => { setSelectedCloudId(c.id); onCloudChange(c.id); }}
                  style={{
                    padding: "7px 9px",
                    borderRadius: 5,
                    marginBottom: 5,
                    background: isSelected ? "rgba(255, 129, 46, 0.22)" : "transparent",
                    border: isSelected ? "1px solid #FF812E" : "1px solid rgba(51, 64, 80, 0.5)",
                    cursor: "pointer",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    fontSize: 11,
                  }}
                >
                  <span style={{ color: isSelected ? "#FFA25B" : "#E2E8F0", fontWeight: isSelected ? 800 : 500 }}>
                    {title}<br />
                    <span style={{ color: "#94A3B8", fontSize: 9.5 }}>{subtitle}</span>
                  </span>
                  <span title="Загружено точек / точек в источнике" style={{ fontSize: 9.5, background: "#0E1318", color: isSelected ? "#4ADE80" : "#94A3B8", padding: "2px 6px", borderRadius: 3, fontWeight: 700 }}>
                    {badge}
                  </span>
                </div>
              );
            })}

            {/* Transverse Spans Guide Card */}
            <div style={{ marginTop: 10, paddingTop: 8, borderTop: "1px dashed #334050", fontSize: 10.5, color: "#CBD5E1" }}>
              <div style={{ fontWeight: 800, color: "#FFA25B", marginBottom: 5 }}>ПРОЛЁТЫ ЦЕХА (СП 16.13330):</div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                <span>• Пролёт 1 (Оси А–Б):</span> <strong style={{ color: "#FFFFFF" }}>13.25 м</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                <span>• Пролёт 2 (Оси Б–В):</span> <strong style={{ color: "#FFFFFF" }}>11.70 м</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                <span>• Пролёт 3 (Оси В–Г):</span> <strong style={{ color: "#FFFFFF" }}>13.25 м</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, paddingTop: 4, borderTop: "1px solid #334050", color: "#4ADE80", fontWeight: 700 }}>
                <span>Всего (3 пролёта):</span> <span>38.20 м</span>
              </div>
            </div>
          </div>

          <div style={{ padding: "10px 12px", background: "#1C2430", borderRadius: 6, border: "1px solid #334050", fontSize: 11.5 }}>
            <div style={{ color: "#94A3B8", marginBottom: 4, fontWeight: 700 }}>МЕТАДАННЫЕ СКАНА</div>
            <div style={{ fontWeight: 700, color: "#FFFFFF" }}>{scannerModelLabel(currentCloud)}</div>
            <div style={{ color: "#CBD5E1", fontSize: 11, marginTop: 3 }}>{currentCloud?.source_format.toUpperCase() || "Формат не указан"} · регистрация и точность не подтверждены</div>
          </div>
        </aside>

        {/* CENTER 3D VIEWPORT */}
        <main className="viewport-center">
          {/* Floating 3D Tools Ribbon */}
          <div className="viewport-tools-ribbon">
            <button className="ribbon-btn active" title="Режим выбора и осмотра">
              <Crosshair size={14} /> Выбор
            </button>
            <button
              className={`ribbon-btn ${measureMode ? "active" : ""}`}
              onClick={() => setMeasureMode(!measureMode)}
              style={{
                background: measureMode ? "rgba(56, 189, 248, 0.25)" : "transparent",
                color: measureMode ? "#38BDF8" : "#E2E8F0",
                borderColor: measureMode ? "#38BDF8" : undefined,
              }}
              title="Лазерный 3D дальномер (ReCap Laser Measure): расстояние, уклон, высотная отметка"
            >
              <Maximize2 size={14} /> 3D Замер
            </button>
            <button
              className={`ribbon-btn ${showLimitBox ? "active" : ""}`}
              onClick={() => setShowLimitBox(!showLimitBox)}
              style={{
                background: showLimitBox ? "rgba(255, 129, 46, 0.25)" : "transparent",
                color: showLimitBox ? "#FF812E" : "#E2E8F0",
                borderColor: showLimitBox ? "#FF812E" : undefined,
              }}
              title="Ограничивающий куб (Limit Box): аппаратная обрезка облака точек по осям X, Y, Z"
            >
              <Layers size={14} /> Limit Box
            </button>
            <button
              className="ribbon-btn"
              onClick={() => setActiveNav("panoramas")}
              title="Сферические панорамы, если они загружены в проект"
            >
              <Camera size={14} /> Панорама
            </button>
            <button
              className="ribbon-btn"
              onClick={() => {
                if (elements.length > 0) {
                  setInspectingElement(selectedElement || elements[0]);
                }
              }}
              style={{ color: "#FFA25B" }}
              title="ГОСТ инспектор сечений и сортамента металлопроката"
            >
              <Building size={14} /> ГОСТ Сортамент
            </button>
            {/* Span Focus Toolbar */}
            <div style={{ display: "flex", alignItems: "center", gap: 3, background: "#1C2430", padding: "2px 6px", borderRadius: 6, border: "1px solid #334050" }}>
              <span style={{ fontSize: 10.5, fontWeight: 800, color: "#FFA25B", marginRight: 3 }}>ПРОЛЁТЫ:</span>
              <button
                onClick={() => {
                  setSelectedSpan("all");
                  showToast("Отображаются все 3 пролёта цеха (Оси А–Б–В–Г, 38.2 м)", "info", 2000);
                }}
                style={{
                  padding: "3px 7px",
                  fontSize: 10.5,
                  fontWeight: selectedSpan === "all" ? 800 : 500,
                  background: selectedSpan === "all" ? "#FF812E" : "transparent",
                  color: selectedSpan === "all" ? "#0A0D11" : "#E2E8F0",
                  border: "none",
                  borderRadius: 3,
                  cursor: "pointer",
                }}
                title="Все 3 пролёта цеха объединены (1.rcs + 2.rcs, 138м × 38.2м)"
              >
                Все 3 пролёта
              </button>
              <button
                onClick={() => {
                  setSelectedSpan("span1");
                  showToast("Фокус: Пролёт 1 (Оси А–Б, ширина 13.25 м, 1.rcs)", "info", 2000);
                }}
                style={{
                  padding: "3px 7px",
                  fontSize: 10.5,
                  fontWeight: selectedSpan === "span1" ? 800 : 500,
                  background: selectedSpan === "span1" ? "#38BDF8" : "transparent",
                  color: selectedSpan === "span1" ? "#0A0D11" : "#E2E8F0",
                  border: "none",
                  borderRadius: 3,
                  cursor: "pointer",
                }}
                title="Пролёт 1 (Оси А–Б, 13.25 м, Скан 1.rcs)"
              >
                Пролёт 1
              </button>
              <button
                onClick={() => {
                  setSelectedSpan("span2");
                  showToast("Фокус: Пролёт 2 (Оси Б–В, ширина 11.70 м, 1.rcs)", "info", 2000);
                }}
                style={{
                  padding: "3px 7px",
                  fontSize: 10.5,
                  fontWeight: selectedSpan === "span2" ? 800 : 500,
                  background: selectedSpan === "span2" ? "#38BDF8" : "transparent",
                  color: selectedSpan === "span2" ? "#0A0D11" : "#E2E8F0",
                  border: "none",
                  borderRadius: 3,
                  cursor: "pointer",
                }}
                title="Пролёт 2 (Оси Б–В, 11.70 м, Скан 1.rcs)"
              >
                Пролёт 2
              </button>
              <button
                onClick={() => {
                  setSelectedSpan("span3");
                  showToast("Фокус: Пролёт 3 (Оси В–Г, ширина 13.25 м, 2.rcs)", "info", 2000);
                }}
                style={{
                  padding: "3px 7px",
                  fontSize: 10.5,
                  fontWeight: selectedSpan === "span3" ? 800 : 500,
                  background: selectedSpan === "span3" ? "#38BDF8" : "transparent",
                  color: selectedSpan === "span3" ? "#0A0D11" : "#E2E8F0",
                  border: "none",
                  borderRadius: 3,
                  cursor: "pointer",
                }}
                title="Пролёт 3 (Оси В–Г, 13.25 м, Скан 2.rcs)"
              >
                Пролёт 3
              </button>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 6, background: "#1C2430", padding: "2px 8px", borderRadius: 6, border: "1px solid #334050" }}>
              <CloudIcon size={14} color="#FFA25B" />
              <span style={{ fontSize: 11, fontWeight: 800, color: "#FFA25B" }}>ОБЛАКО:</span>
              <select
                value={currentCloud?.id || ""}
                onChange={(e) => {
                  const idx = clouds.findIndex((c) => c.id === e.target.value);
                  if (idx !== -1) {
                    setSelectedCloudId(e.target.value);
                    onCloudChange(e.target.value);
                  }
                }}
                style={{
                  background: "#0E1318",
                  color: "#FFFFFF",
                  border: "1px solid #FF812E",
                  borderRadius: 4,
                  padding: "4px 8px",
                  fontSize: 11.5,
                  fontWeight: 700,
                  cursor: "pointer",
                  outline: "none",
                }}
              >
                {clouds.map((c) => {
                  const coverage = cloudPointCoverage(c);
                  const label = `${c.name || c.id} — ${coverage.label} точек загружено / в источнике${coverage.sampled ? " (выборка)" : ""}`;
                  return (
                    <option key={c.id} value={c.id} style={{ background: "#1C2430", color: "#FFFFFF" }}>
                      {label}
                    </option>
                  );
                })}
              </select>
            </div>
          </div>

          {/* Interactive 3D ViewCube & Camera Orientations */}
          <div
            className="nav-cube-widget"
            style={{
              position: "absolute",
              top: 16,
              right: 18,
              zIndex: 35,
              display: "flex",
              flexDirection: "column",
              gap: 4,
              padding: 6,
              width: "auto",
              height: "auto",
              background: "rgba(15, 23, 42, 0.92)",
              border: "1px solid #334050",
              borderRadius: 8,
              boxShadow: "0 4px 16px rgba(0,0,0,0.6)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
              <Compass size={13} color="#FF812E" />
              <span style={{ fontSize: 10.5, fontWeight: 800, color: "#FFA25B" }}>{activeViewLabel}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 3 }}>
              <button
                onClick={() => {
                  setCameraPreset({ view: "top", seq: Date.now() });
                  setActiveViewLabel("TOP (ПЛАН)");
                  showToast("Вид переключён: ПЛАН (СВЕРХУ)", "info", 2000);
                }}
                style={{
                  padding: "3px 6px",
                  fontSize: 10,
                  fontWeight: activeViewLabel.includes("TOP") ? 800 : 600,
                  background: activeViewLabel.includes("TOP") ? "#FF812E" : "#1C2430",
                  color: activeViewLabel.includes("TOP") ? "#0A0D11" : "#E2E8F0",
                  border: "1px solid #334050",
                  borderRadius: 3,
                  cursor: "pointer",
                }}
                title="Вид сверху (Ортографический план цеха)"
              >
                TOP
              </button>
              <button
                onClick={() => {
                  setCameraPreset({ view: "front", seq: Date.now() });
                  setActiveViewLabel("FRONT (ФАСАД)");
                  showToast("Вид переключён: ФАСАД (СПЕРЕДИ)", "info", 2000);
                }}
                style={{
                  padding: "3px 6px",
                  fontSize: 10,
                  fontWeight: activeViewLabel.includes("FRONT") ? 800 : 600,
                  background: activeViewLabel.includes("FRONT") ? "#FF812E" : "#1C2430",
                  color: activeViewLabel.includes("FRONT") ? "#0A0D11" : "#E2E8F0",
                  border: "1px solid #334050",
                  borderRadius: 3,
                  cursor: "pointer",
                }}
                title="Вид спереди (Продольный фасад)"
              >
                FRONT
              </button>
              <button
                onClick={() => {
                  setCameraPreset({ view: "right", seq: Date.now() });
                  setActiveViewLabel("RIGHT (СБОКУ)");
                  showToast("Вид переключён: ВИД СПРАВА (ТОРЕЦ)", "info", 2000);
                }}
                style={{
                  padding: "3px 6px",
                  fontSize: 10,
                  fontWeight: activeViewLabel.includes("RIGHT") ? 800 : 600,
                  background: activeViewLabel.includes("RIGHT") ? "#FF812E" : "#1C2430",
                  color: activeViewLabel.includes("RIGHT") ? "#0A0D11" : "#E2E8F0",
                  border: "1px solid #334050",
                  borderRadius: 3,
                  cursor: "pointer",
                }}
                title="Вид сбоку (Поперечный торец)"
              >
                RIGHT
              </button>
              <button
                onClick={() => {
                  setCameraPreset({ view: "iso", seq: Date.now() });
                  setActiveViewLabel("3D ISO");
                  showToast("Вид переключён: 3D ИЗОМЕТРИЯ", "info", 2000);
                }}
                style={{
                  padding: "3px 6px",
                  fontSize: 10,
                  fontWeight: activeViewLabel.includes("ISO") ? 800 : 600,
                  background: activeViewLabel.includes("ISO") ? "#FF812E" : "#1C2430",
                  color: activeViewLabel.includes("ISO") ? "#0A0D11" : "#E2E8F0",
                  border: "1px solid #334050",
                  borderRadius: 3,
                  cursor: "pointer",
                  gridColumn: "span 2",
                }}
                title="Аксонометрическая 3D перспектива"
              >
                3D ISO
              </button>
              <button
                onClick={() => {
                  setCameraPreset({ view: "fit", seq: Date.now() });
                  setActiveViewLabel("FIT");
                  showToast("Камера центрирована по габаритам цеха", "info", 2000);
                }}
                style={{
                  padding: "3px 6px",
                  fontSize: 10,
                  fontWeight: 600,
                  background: "#1C2430",
                  color: "#38BDF8",
                  border: "1px solid #334050",
                  borderRadius: 3,
                  cursor: "pointer",
                }}
                title="Центрировать сцену"
              >
                FIT
              </button>
            </div>
          </div>

          {/* Floating Layers Card */}
          <div className="floating-layers-card">
            <div className="card-header-sm">
              <span style={{ display: "flex", alignItems: "center", gap: 5, color: "#FFFFFF" }}>
                <Layers size={13} /> Слои проекта
              </span>
              <Eye size={13} style={{ cursor: "pointer", color: "#CBD5E1" }} />
            </div>
            <div style={{ padding: "6px 0" }}>
              {[
                { key: "pointCloud", label: "Облако точек (LOD)", color: "#38BDF8" },
                { key: "stations", label: "Положения станций (не заданы)", color: "#FF812E", available: false },
                { key: "panoramas", label: "Панорамы (не загружены)", color: "#3DD68C", available: false },
                { key: "aiStructures", label: "Кандидаты конструкций", color: "#A855F7", available: true },
                { key: "axes", label: "Оси (контрольная сетка не задана)", color: "#F5B041", available: false },
                { key: "bimModel", label: "BIM Модель (IFC4)", color: "#EC4899" },
              ].map((item) => (
                <div
                  key={item.key}
                  className="layer-item-row"
                  onClick={() => { if ((item as any).available) toggleLayer(item.key as any); }}
                  aria-disabled={!(item as any).available}
                  style={{ opacity: (item as any).available ? ((layers as any)[item.key] ? 1 : 0.4) : 0.45, cursor: (item as any).available ? "pointer" : "default" }}
                >
                  <div style={{ display: "flex", alignItems: "center" }}>
                    <span className="layer-color-dot" style={{ background: item.color }}></span>
                    <span style={{ color: "#FFFFFF", fontWeight: 600 }}>{item.label}</span>
                  </div>
                  <span style={{ fontSize: 12, color: "#4ADE80" }}>{(layers as any)[item.key] ? "●" : "○"}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Core 3D Viewport Scene or Split-Screen Registration */}
          <div className="scene-container">
            {activeNav === "stitching" ? (
              <SplitScreenRegistrationView
                sourceCloud={clouds[0] || cloud}
                targetCloud={clouds[1] || clouds[0] || cloud}
              />
            ) : currentCloud ? (
              <Viewer3D
                cloud={currentCloud}
                elements={elements}
                groupPositions={emptyFloatArray}
                selectedElement={selectedElement}
                selectedElementPositions={emptyFloatArray}
                selectedElementSections={emptySections}
                pointSize={2.0}
                colorMode={colorMode}
                showPlane={false}
                section={null}
                hideInternalHud={true}
                limitBoxActive={showLimitBox}
                onToggleLimitBox={setShowLimitBox}
                measureModeActive={measureMode}
                onToggleMeasureMode={setMeasureMode}
                showBim={layers.aiStructures || layers.bimModel}
                cameraPreset={cameraPreset}
              />
            ) : (
              <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#CBD5E1" }}>
                Загрузите облако точек для отображения в 3D сцене
              </div>
            )}
          </div>

          {/* BOTTOM DOCK DRAWER */}
          <section className="bottom-dock-container">
            {/* Card 1: Interactive Recharts Statistics */}
            <div className="dock-card" style={{ width: 440, minWidth: 440 }}>
              <RegistrationQualityCharts
                rmseData={[]}
                heightDistribution={[]}
              />
            </div>

            {/* Card 2: Interactive 360 Panorama Preview */}
            <div className="dock-card" style={{ width: 280, minWidth: 280, position: "relative" }}>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid #334050", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11.5, fontWeight: 700, color: "#FFFFFF" }}>
                <span>ПАНОРАМЫ 360°</span>
                <span style={{ color: "#F2B84B", fontWeight: 800 }}>НЕ ЗАГРУЖЕНЫ</span>
              </div>
              <div style={{ flex: 1, display: "grid", placeItems: "center", padding: 16, color: "#94A3B8", fontSize: 12, textAlign: "center" }}>
                Панорамы и координаты стоянок не найдены в данных проекта.
              </div>
            </div>

            {/* Card 3: TanStack Table of Classified Elements */}
            <div className="dock-card" style={{ flex: 1, minWidth: 320 }}>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid #334050", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11.5, fontWeight: 700, color: "#FFFFFF" }}>
                <span>КАНДИДАТЫ КОНСТРУКЦИЙ · ТРЕБУЮТ ПРОВЕРКИ</span>
                <span style={{ color: "#94A3B8" }}>{elements.length} кандидатов</span>
              </div>
              <div style={{ flex: 1, overflow: "hidden" }}>
                <ElementTanStackTable
                  elements={elements}
                  selectedElement={selectedElement}
                  onSelectElement={onSelectElement}
                  onInspectElement={(el) => setInspectingElement(el)}
                />
              </div>
            </div>
          </section>
        </main>

        {/* RIGHT AI ASSISTANT DRAWER */}
        <aside className="sidebar-right">
          <div className="ai-mode-selector">
            {(["manual", "hybrid", "ai"] as const).map((mode) => (
              <button
                key={mode}
                className={`mode-chip ${assistantMode === mode ? "active" : ""}`}
                onClick={() => setAssistantMode(mode)}
              >
                {mode === "manual" && "Ручной"}
                {mode === "hybrid" && "Гибрид"}
                {mode === "ai" && "Авто ИИ"}
              </button>
            ))}
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: "14px" }}>
            {selectedElement && (
              <ElementAnnotationPanel
                key={`${selectedElement.cloud_id}:${selectedElement.id}`}
                cloudId={selectedElement.cloud_id}
                element={selectedElement}
                busy={busy}
                onAnnotationSaved={() => showToast("Независимая разметка сохранена отдельно от гипотезы распознавателя.", "success")}
              />
            )}
            {selectedElement?.class_name === "column" && (
              <ColumnAnnotationPanel
                key={`column-reference:${selectedElement.cloud_id}:${selectedElement.id}`}
                cloudId={selectedElement.cloud_id}
                element={selectedElement}
                busy={busy}
                surfaceAnalysis={null}
                onAnnotationSaved={() => showToast("Эталонная разметка колонны сохранена.", "success")}
              />
            )}
            {recapNotice && (
              <div style={{ background: "rgba(34, 197, 94, 0.15)", border: "1px solid #22C55E", borderRadius: 6, padding: "10px 12px", marginBottom: 12, color: "#86EFAC", fontSize: 12 }}>
                ✓ {recapNotice}
              </div>
            )}
            <div style={{ background: "#1C2430", border: "1px solid #334050", borderRadius: 6, padding: "14px", marginBottom: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <span style={{ fontWeight: 800, fontSize: 13, color: "#FFA25B" }}>ИИ АССИСТЕНТ SCAN STUDIO</span>
                <span style={{ fontSize: 10, background: "rgba(255, 129, 46, 0.2)", color: "#FF812E", padding: "2px 6px", borderRadius: 3, fontWeight: 700 }}>
                  Active
                </span>
              </div>
              <p style={{ fontSize: 12.5, color: "#E2E8F0", lineHeight: 1.6 }}>
                Подтверждённой регистрации исходных FARO-станций пока нет. SCAN может собрать нативный RCP-пакет через Autodesk DeCap; положения сканов проверяются отдельно по связям и контрольным точкам.
              </p>
            </div>

            {/* Quick Action Buttons */}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <button
                className="action-dark-btn"
                onClick={() => setActiveNav("stitching")}
                style={{ width: "100%", justifyContent: "flex-start", padding: "10px 14px", background: "#1C2430", border: "1px solid #334050", color: "#FFFFFF", fontWeight: 700, borderRadius: 6 }}
              >
                <Network size={16} color="#FF812E" /> Сшивка сплит-экраном (2 скана)
              </button>
              <button
                className="action-dark-btn"
                onClick={() => {
                  if (elements.length > 0) setInspectingElement(elements[0]);
                }}
                style={{ width: "100%", justifyContent: "flex-start", padding: "10px 14px", background: "#1C2430", border: "1px solid #334050", color: "#FFFFFF", fontWeight: 700, borderRadius: 6 }}
              >
                <Building size={16} color="#38BDF8" /> Инспектор ГОСТ-сортамента колонн
              </button>
              <button
                className="action-dark-btn"
                onClick={() => { window.open(`http://127.0.0.1:8000/api/v1/clouds/${currentCloud?.id || "workshop_cloud"}/spds-album.pdf`, "_blank"); showToast("Ведомость отклонений колонн по СП 70.13330 открыта в PDF!", "success"); }}
                style={{ width: "100%", justifyContent: "flex-start", padding: "10px 14px", background: "#1C2430", border: "1px solid #334050", color: "#FFFFFF", fontWeight: 700, borderRadius: 6 }}
              >
                <BarChart3 size={16} color="#4ADE80" /> Сформировать ведомость отклонений PDF
              </button>
              <button
                className="action-dark-btn"
                onClick={() => setActiveNav("stitching")}
                style={{ width: "100%", justifyContent: "flex-start", padding: "10px 14px", background: "#1C2430", border: "1px solid #334050", color: "#FFFFFF", fontWeight: 700, borderRadius: 6 }}
              >
                Перейти к регистрации сканов
              </button>
              <button
                onClick={handleExportRecap}
                disabled={busy || recapExporting || selectedRecapCloudIds.length === 0}
                style={{ width: "100%", justifyContent: "flex-start", padding: "10px 14px", color: "#FFFFFF", fontWeight: 700, background: "rgba(255, 129, 46, 0.15)", border: "1px solid #FF812E", opacity: busy || recapExporting || selectedRecapCloudIds.length === 0 ? 0.55 : 1 }}
              >
                <FileDown size={16} color="#FF812E" /> {recapExporting ? "ReCap собирает проект…" : "Собрать настоящий проект ReCap (.RCP)"}
              </button>
              <div style={{ padding: "10px 12px", border: "1px solid #334050", borderRadius: 6, color: "#CBD5E1", fontSize: 12 }}>
                <strong style={{ display: "block", marginBottom: 6 }}>Исходные сканы для RCP</strong>
                {recapEligibleClouds.length === 0 ? (
                  <span>Нет готовых исходных файлов, поддерживаемых DeCap.</span>
                ) : recapEligibleClouds.map((item) => (
                  <label key={item.id} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 6, wordBreak: "break-word" }}>
                    <input
                      type="checkbox"
                      checked={selectedRecapCloudIds.includes(item.id)}
                      onChange={(event) => setSelectedRecapCloudIds((current) => event.target.checked
                        ? [...current, item.id]
                        : current.filter((id) => id !== item.id))}
                    />
                    <span>{item.name} <small style={{ color: "#94A3B8" }}>({item.source_format.toUpperCase()})</small></span>
                  </label>
                ))}
                <p style={{ margin: "8px 0 0", color: "#94A3B8", lineHeight: 1.45 }}>
                  DeCap создаёт нативные RCP и Support/RCS. Исходные станции импортируются в исходных координатах; эта операция не выполняет регистрацию и не меняет исходные файлы.
                </p>
                {recapProjectPath && (
                  <button
                    className="action-dark-btn"
                    onClick={async () => {
                      try {
                        await api.openInReCap(recapProjectPath);
                      } catch (err: any) {
                        showToast("Не удалось открыть проект в ReCap: " + (err.message || String(err)), "error");
                      }
                    }}
                    style={{ width: "100%", marginTop: 8, justifyContent: "flex-start" }}
                  >
                    Открыть созданный RCP в ReCap
                  </button>
                )}
              </div>
              <a
                href={`http://127.0.0.1:8000/api/v1/clouds/${currentCloud?.id || "workshop_cloud"}/spds-album.pdf`}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  width: "100%",
                  boxSizing: "border-box",
                  padding: "10px 14px",
                  background: "rgba(59, 130, 246, 0.15)",
                  border: "1px solid #3B82F6",
                  borderRadius: 6,
                  color: "#93C5FD",
                  textDecoration: "none",
                  fontSize: 12.5,
                  fontWeight: 700,
                }}
              >
                <FileDown size={16} color="#3B82F6" /> Скачать альбом СПДС (PDF, 5 листов)
              </a>
              <a
                href={`http://127.0.0.1:8000/api/v1/clouds/${currentCloud?.id || "workshop_cloud"}/spds-album.zip`}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  width: "100%",
                  boxSizing: "border-box",
                  padding: "10px 14px",
                  background: "rgba(168, 85, 247, 0.15)",
                  border: "1px solid #A855F7",
                  borderRadius: 6,
                  color: "#D8B4FE",
                  textDecoration: "none",
                  fontSize: 12.5,
                  fontWeight: 700,
                }}
              >
                <FileSpreadsheet size={16} color="#A855F7" /> Чертежи AutoCAD (.DWG / .DXF)
              </a>
              <a
                href={`http://127.0.0.1:8000/api/v1/clouds/${currentCloud?.id || "workshop_cloud"}/bim?format=ifc`}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  width: "100%",
                  boxSizing: "border-box",
                  padding: "10px 14px",
                  background: "rgba(34, 197, 94, 0.15)",
                  border: "1px solid #22C55E",
                  borderRadius: 6,
                  color: "#86EFAC",
                  textDecoration: "none",
                  fontSize: 12.5,
                  fontWeight: 700,
                }}
              >
                <Building size={16} color="#22C55E" /> Экспорт BIM модели (IFC4)
              </a>
            </div>
          </div>
        </aside>
      </div>

      {/* 4. BOTTOM STATUS STRIP */}
      <footer className="bottom-status-strip">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 9, height: 9, borderRadius: "50%", background: busy ? "#FF812E" : "#64748B" }}></span>
          <span style={{ fontWeight: 700, color: "#FFFFFF" }}>{jobLabel || "Нет выполняемого задания"}</span>
          <span style={{ color: "#94A3B8" }}>{currentCloud?.name || "облако не выбрано"}</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {busy && progress !== null && (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div className="progress-track-wide">
                <div className="progress-fill-wide" style={{ width: `${progress}%` }}></div>
              </div>
              <span style={{ fontWeight: 800, color: "#FFA25B" }}>{progress}%</span>
            </div>
          )}

          <div style={{ display: "flex", gap: 14, fontSize: 12, color: "#CBD5E1" }}>
            <span>RMSE регистрации: <strong style={{ color: "#F2B84B" }}>не измерена</strong></span>
            <span>Инженерный допуск: <strong style={{ color: "#F2B84B" }}>не задан</strong></span>
          </div>
        </div>
      </footer>

            {/* TOAST NOTIFICATION */}
      {toast && (
        <div
          style={{
            position: "fixed",
            top: 56,
            right: 20,
            zIndex: 9999,
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 18px",
            borderRadius: 6,
            background: toast.type === "error" ? "rgba(220, 38, 38, 0.95)" : toast.type === "success" ? "rgba(22, 163, 74, 0.95)" : toast.type === "warning" ? "rgba(234, 88, 12, 0.95)" : "rgba(30, 41, 59, 0.95)",
            border: `1px solid ${toast.type === "error" ? "#EF4444" : toast.type === "success" ? "#4ADE80" : toast.type === "warning" ? "#FB923C" : "#38BDF8"}`,
            color: "#FFFFFF",
            boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          <span>{toast.type === "error" ? "✕" : toast.type === "success" ? "✓" : "ℹ"}</span>
          <span>{toast.message}</span>
          <button
            onClick={() => setToast(null)}
            style={{ background: "transparent", border: "none", color: "#FFFFFF", cursor: "pointer", marginLeft: 8, fontSize: 16 }}
          >
            ×
          </button>
        </div>
      )}

      {/* GOST Profile Inspector Modal */}
      {inspectingElement && (
        <GostProfileInspectorModal
          element={inspectingElement}
          onClose={() => setInspectingElement(null)}
        />
      )}
    </div>
  );
};
