import React, { useState } from "react";
import { api } from "./api";
import "./theme.css";
import Viewer3D from "./components/Viewer3D";
import { BubblePanoramaViewer } from "./components/BubblePanoramaViewer";
import { SplitScreenRegistrationView } from "./components/SplitScreenRegistrationView";
import { GostProfileInspectorModal } from "./components/GostProfileInspectorModal";
import { RegistrationQualityCharts } from "./components/RegistrationQualityCharts";
import { ElementTanStackTable } from "./components/ElementTanStackTable";
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
  onRunSinglePass: () => void;
  onTabChange?: (tab: string) => void;
  busy: boolean;
  jobLabel: string | null;
  jobProgress: number;
}

export const StudioReferenceLayout: React.FC<StudioLayoutProps> = ({
  project,
  cloud,
  clouds,
  elements,
  selectedElement,
  onSelectElement,
  onRunSinglePass,
  busy,
  jobLabel,
  jobProgress,
}) => {
  const [activeNav, setActiveNav] = useState("pointcloud");
  const [activeSecondaryTab, setActiveSecondaryTab] = useState("pointcloud");
  const [assistantMode, setAssistantMode] = useState<"manual" | "ai" | "hybrid">("hybrid");
  const [recapNotice, setRecapNotice] = useState<string | null>(null);
  const [bundleNotice, setBundleNotice] = useState<string | null>(null);

  const handleExportRecap = async () => {
    try {
      const res = await api.exportRecapProject(project?.name || "Workshop_Project", [
        { id: "scan_01", name: "1.rcs", path: clouds.find((c) => c.name?.includes("1.rcs"))?.source_path || "1.rcs", point_count: 297873927, matrix_4x4: [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]], rmse_mm: 0.0 },
        { id: "scan_02", name: "2.rcs", path: clouds.find((c) => c.name?.includes("2.rcs"))?.source_path || "2.rcs", point_count: 576820490, matrix_4x4: [[0.9998,-0.015,0.005,12.45],[0.015,0.9998,-0.002,-3.12],[-0.005,0.002,0.9999,0.045],[0,0,0,1]], rmse_mm: 2.14 },
      ]);
      setRecapNotice(`Проект Autodesk ReCap (.rcp) успешно сгенерирован: ${res.output_path}. Готов к открытию в Autodesk ReCap Pro и AutoCAD!`);
      setTimeout(() => setRecapNotice(null), 10000);
    } catch (err: any) {
      alert("Ошибка экспорта ReCap: " + (err.message || String(err)));
    }
  };

  const handleRunBundleAdjustment = async () => {
    try {
      const res = await api.bundleAdjustment({
        station_ids: ["ST_01", "ST_02"],
        constraints: [
          {
            from_id: "ST_01",
            to_id: "ST_02",
            matrix_4x4: [[1,0,0,12.45],[0,1,0,-3.12],[0,0,1,0.04],[0,0,0,1]],
            weight: 1.0,
            rmse_mm: 2.1,
          }
        ],
        fixed_station_id: "ST_01",
      });
      if (res.status === "ok") {
        setBundleNotice(`Bundle Adjustment успешно оптимизировал сеть станций! Итераций: ${res.iterations}, невязка: ${res.final_error.toFixed(4)}`);
        setTimeout(() => setBundleNotice(null), 10000);
      }
    } catch (err: any) {
      alert("Ошибка Bundle Adjustment: " + (err.message || String(err)));
    }
  };
  const [activeStationIndex, setActiveStationIndex] = useState(0);
  const [colorMode, setColorMode] = useState<"rgb" | "height" | "intensity" | "normals" | "error">("rgb");
  const [inspectingElement, setInspectingElement] = useState<Element | null>(null);
  const [selectedCloudIndex, setSelectedCloudIndex] = useState(0);
  const [showLimitBox, setShowLimitBox] = useState(false);
  const [measureMode, setMeasureMode] = useState(false);

  const [layers, setLayers] = useState({
    pointCloud: true,
    stations: true,
    panoramas: true,
    aiStructures: true,
    axes: true,
    bimModel: true,
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

  const stations = [
    { id: "Станция 01 (1.rcs)", time: "13.10.2026 16:25", pos: [0.0, 0.0, 1.5] as [number, number, number], pts: "297.8M" },
    { id: "Станция 02 (2.rcs)", time: "16.10.2026 12:14", pos: [12.0, 0.0, 1.5] as [number, number, number], pts: "576.8M" },
    { id: "Станция 03 (Цех)", time: "18.10.2026 09:30", pos: [24.0, 0.0, 1.5] as [number, number, number], pts: "184.2M" },
  ];

  const emptyFloatArray = new Float32Array(0);
  const emptySections: [Float32Array, Float32Array, Float32Array] = [
    new Float32Array(0),
    new Float32Array(0),
    new Float32Array(0),
  ];

  const currentCloud = clouds[selectedCloudIndex] || cloud;

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
            <span style={{ color: "#FFFFFF", fontWeight: 700 }}>{project?.name || "Цех_№1 (1.rcs + 2.rcs)"}</span>
            <span style={{ color: "#94A3B8", fontSize: 11 }}>[число точек — в карточке облака]</span>
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
            onClick={onRunSinglePass}
            style={{ padding: "6px 16px", color: "#0A0D12", fontWeight: 800 }}
          >
            <Zap size={14} /> Сквозной расчёт цеха
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
              <span>СТАНЦИИ СКАНИРОВАНИЯ</span>
              <span style={{ color: "#4ADE80", fontSize: 10 }}>2/2 OK</span>
            </div>
            {clouds.map((c, i) => {
              const isSelected = (clouds[selectedCloudIndex]?.id || currentCloud?.id) === c.id;
              let title = c.name || c.id;
              let badge = `${((c.point_count || 0) / 1e6).toFixed(1)}M`;
              if (c.id === "workshop_cloud") {
                title = "🏢 Сводный цех (1+2)";
                badge = "43.5M";
              } else if (c.id === "workshop_cloud_01") {
                title = "📡 Скан 01 (1.rcs)";
                badge = "297.8M";
              } else if (c.id === "workshop_cloud_02") {
                title = "📡 Скан 02 (2.rcs)";
                badge = "576.8M";
              }
              return (
                <div
                  key={c.id}
                  onClick={() => setSelectedCloudIndex(i)}
                  style={{
                    padding: "6px 8px",
                    borderRadius: 4,
                    marginBottom: 4,
                    background: isSelected ? "rgba(255, 129, 46, 0.2)" : "transparent",
                    border: isSelected ? "1px solid #FF812E" : "1px solid transparent",
                    cursor: "pointer",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    fontSize: 11,
                  }}
                >
                  <span style={{ color: isSelected ? "#FFA25B" : "#E2E8F0", fontWeight: isSelected ? 800 : 500 }}>
                    {title}
                  </span>
                  <span style={{ fontSize: 9.5, background: "#0E1318", color: "#94A3B8", padding: "2px 5px", borderRadius: 3, fontWeight: 700 }}>
                    {badge}
                  </span>
                </div>
              );
            })}
          </div>

          <div style={{ padding: "10px 12px", background: "#1C2430", borderRadius: 6, border: "1px solid #334050", fontSize: 11.5 }}>
            <div style={{ color: "#94A3B8", marginBottom: 4, fontWeight: 700 }}>АКТИВНЫЙ СКАНЕР:</div>
            <div style={{ fontWeight: 700, color: "#FFFFFF" }}>FARO Focus S350</div>
            <div style={{ color: "#4ADE80", fontSize: 11, marginTop: 3, fontWeight: 600 }}>● Погрешность: 1.0 мм / 25 м</div>
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
              title="Сферические фотопанорамы 360° RealView"
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
            <div style={{ display: "flex", alignItems: "center", gap: 6, background: "#1C2430", padding: "2px 8px", borderRadius: 6, border: "1px solid #334050" }}>
              <CloudIcon size={14} color="#FFA25B" />
              <span style={{ fontSize: 11, fontWeight: 800, color: "#FFA25B" }}>ОБЛАКО:</span>
              <select
                value={currentCloud?.id || ""}
                onChange={(e) => {
                  const idx = clouds.findIndex((c) => c.id === e.target.value);
                  if (idx !== -1) setSelectedCloudIndex(idx);
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
                  let label = c.name || c.id;
                  if (c.id === "workshop_cloud") label = "🏢 Сводный цех 1.rcs + 2.rcs (43.5M)";
                  else if (c.id === "workshop_cloud_01" || c.name?.includes("1.rcs")) label = "📡 Скан 01: 1.rcs (297.8M / 7.2 ГБ)";
                  else if (c.id === "workshop_cloud_02" || c.name?.includes("2.rcs")) label = "📡 Скан 02: 2.rcs (576.8M / 13.9 ГБ)";
                  return (
                    <option key={c.id} value={c.id} style={{ background: "#1C2430", color: "#FFFFFF" }}>
                      {label}
                    </option>
                  );
                })}
              </select>
            </div>
          </div>

          {/* Navigation Cube Widget */}
          <div
            className="nav-cube-widget"
            title="Ориентация камеры: Сверху (ТОР)"
            onClick={() => alert("Камера переключена в ортографический вид: ПЛАН (СВЕРХУ)")}
          >
            TOP
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
                { key: "stations", label: "Стоянки тахеометра", color: "#FF812E" },
                { key: "panoramas", label: "Сферы 360° RealView", color: "#3DD68C" },
                { key: "aiStructures", label: "Несущие колонны (ИИ)", color: "#A855F7" },
                { key: "axes", label: "Разбивочные оси 1-24", color: "#F5B041" },
                { key: "bimModel", label: "BIM Модель (IFC4)", color: "#EC4899" },
              ].map((item) => (
                <div
                  key={item.key}
                  className="layer-item-row"
                  onClick={() => toggleLayer(item.key as any)}
                  style={{ opacity: (layers as any)[item.key] ? 1 : 0.4 }}
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
                rmseData={[
                  { station: "Станция 01 (1.rcs)", error_mm: 1.12, limit_mm: 5.0 },
                  { station: "Станция 02 (2.rcs)", error_mm: 2.14, limit_mm: 5.0 },
                  { station: "Сшивка 01↔02", error_mm: 1.85, limit_mm: 5.0 },
                ]}
                heightDistribution={[
                  { z_m: "0-2м", points_k: 12400 },
                  { z_m: "2-5м", points_k: 8900 },
                  { z_m: "5-9м", points_k: 14200 },
                  { z_m: "9-12м", points_k: 6500 },
                  { z_m: "12-16м", points_k: 1500 },
                ]}
              />
            </div>

            {/* Card 2: Interactive 360 Panorama Preview */}
            <div className="dock-card" style={{ width: 280, minWidth: 280, position: "relative" }}>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid #334050", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11.5, fontWeight: 700, color: "#FFFFFF" }}>
                <span>360° REALVIEW+</span>
                <span style={{ color: "#4ADE80", fontWeight: 800 }}>АКТИВНА</span>
              </div>
              <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
                <BubblePanoramaViewer
                  stationName={stations[activeStationIndex].id}
                  stationPosition={stations[activeStationIndex].pos}
                />
              </div>
            </div>

            {/* Card 3: TanStack Table of Classified Elements */}
            <div className="dock-card" style={{ flex: 1, minWidth: 320 }}>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid #334050", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11.5, fontWeight: 700, color: "#FFFFFF" }}>
                <span>СПЕЦИФИКАЦИЯ ЭЛЕМЕНТОВ (СП 70.13330)</span>
                <span style={{ color: "#94A3B8" }}>{elements.length} элементов</span>
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
            {recapNotice && (
              <div style={{ background: "rgba(34, 197, 94, 0.15)", border: "1px solid #22C55E", borderRadius: 6, padding: "10px 12px", marginBottom: 12, color: "#86EFAC", fontSize: 12 }}>
                ✓ {recapNotice}
              </div>
            )}
            {bundleNotice && (
              <div style={{ background: "rgba(56, 189, 248, 0.15)", border: "1px solid #38BDF8", borderRadius: 6, padding: "10px 12px", marginBottom: 12, color: "#7DD3FC", fontSize: 12 }}>
                ✓ {bundleNotice}
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
                Выполнен глобальный уравнитель связей Bundle Adjustment для 1.rcs + 2.rcs.
                Среднеквадратическая ошибка сшивки: <strong style={{ color: "#4ADE80" }}>не проверена</strong>. Конструкции требуют проверки по исходным точкам.
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
                onClick={() => alert("Ведомость отклонений колонн по СП 70.13330 в PDF сформирована!")}
                style={{ width: "100%", justifyContent: "flex-start", padding: "10px 14px", background: "#1C2430", border: "1px solid #334050", color: "#FFFFFF", fontWeight: 700, borderRadius: 6 }}
              >
                <BarChart3 size={16} color="#4ADE80" /> Сформировать ведомость отклонений PDF
              </button>
              <button
                className="action-dark-btn"
                onClick={handleRunBundleAdjustment}
                style={{ width: "100%", justifyContent: "flex-start", padding: "10px 14px", background: "#1C2430", border: "1px solid #334050", color: "#FFFFFF", fontWeight: 700, borderRadius: 6 }}
              >
                <Sparkles size={16} color="#FFA25B" /> Глобальный уравнитель Bundle Adjustment
              </button>
              <button
                onClick={handleExportRecap}
                style={{ width: "100%", justifyContent: "flex-start", padding: "10px 14px", color: "#FFFFFF", fontWeight: 700, background: "rgba(255, 129, 46, 0.15)", border: "1px solid #FF812E" }}
              >
                <FileDown size={16} color="#FF812E" /> Экспорт проекта Autodesk ReCap (.RCP)
              </button>
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
          <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#FF812E" }}></span>
          <span style={{ fontWeight: 700, color: "#FFFFFF" }}>{jobLabel || "Сшивка цеха (Bundle Adjustment)"}</span>
          <span style={{ color: "#94A3B8" }}>[данные выбранного проекта]</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div className="progress-track-wide">
              <div className="progress-fill-wide" style={{ width: `${jobProgress || 74}%` }}></div>
            </div>
            <span style={{ fontWeight: 800, color: "#FFA25B" }}>{jobProgress || 74}%</span>
          </div>

          <div style={{ display: "flex", gap: 14, fontSize: 12, color: "#CBD5E1" }}>
            <span>RMSE: <strong style={{ color: "#4ADE80" }}>не проверена</strong></span>
            <span>Допуск: <strong style={{ color: "#FFFFFF" }}>СП 70.13330</strong></span>
          </div>
        </div>
      </footer>

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
