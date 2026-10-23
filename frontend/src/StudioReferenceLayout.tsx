import React, { useState } from "react";
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
  const [activeStationIndex, setActiveStationIndex] = useState(0);
  const [colorMode, setColorMode] = useState<"rgb" | "height" | "intensity" | "normals" | "error">("rgb");
  const [inspectingElement, setInspectingElement] = useState<Element | null>(null);
  const [selectedCloudIndex, setSelectedCloudIndex] = useState(0);

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
            <button className="ribbon-btn active" title="Выбор"><Crosshair size={14} /> Выбор</button>
            <button className="ribbon-btn" title="Замер"><Maximize2 size={14} /> Замер</button>
            <button className="ribbon-btn" onClick={() => setActiveNav("panoramas")}><Camera size={14} /> Панорама</button>
            <button
              className="ribbon-btn"
              onClick={() => {
                if (elements.length > 0) {
                  setInspectingElement(selectedElement || elements[0]);
                }
              }}
              style={{ color: "#FFA25B" }}
            >
              <Building size={14} /> ГОСТ Сортамент
            </button>
            <button
              className="ribbon-btn"
              onClick={() => {
                setSelectedCloudIndex((prev) => (prev === 0 ? 1 : 0));
              }}
            >
              Скан {selectedCloudIndex + 1}/{clouds.length || 2}
            </button>
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
              <RegistrationQualityCharts />
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
                onClick={() => setActiveNav("stitching")}
                style={{ width: "100%", justifyContent: "flex-start", padding: "10px 14px", color: "#FFFFFF", fontWeight: 700 }}
              >
                <Network size={16} color="#FF812E" /> Открыть сплит-сшивку станций
              </button>
              <button
                onClick={() => {
                  if (elements.length > 0) setInspectingElement(elements[0]);
                }}
                style={{ width: "100%", justifyContent: "flex-start", padding: "10px 14px", color: "#FFFFFF", fontWeight: 700 }}
              >
                <Building size={16} color="#38BDF8" /> Проверить ГОСТ-сортамент колонн
              </button>
              <button
                onClick={() => alert("Экспорт ведомости отклонений по СП 70.13330 в PDF сформирован!")}
                style={{ width: "100%", justifyContent: "flex-start", padding: "10px 14px", color: "#FFFFFF", fontWeight: 700 }}
              >
                <BarChart3 size={16} color="#4ADE80" /> Сформировать ведомость отклонений PDF
              </button>
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
