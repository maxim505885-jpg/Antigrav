import React, { useState } from "react";
import "./theme.css";
import Viewer3D from "./components/Viewer3D";
import { BubblePanoramaViewer } from "./components/BubblePanoramaViewer";
import ElementTable from "./components/ElementTable";
import ColumnTypesPanel from "./components/ColumnTypesPanel";
import ColumnSectionFitPanel from "./components/ColumnSectionFitPanel";
import { ManualRegistrationPanel } from "./components/ManualRegistrationPanel";
import { SplitScreenRegistrationView } from "./components/SplitScreenRegistrationView";
import { GostProfileInspectorModal } from "./components/GostProfileInspectorModal";
import { type Cloud, type Element, type Project } from "./types";

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
  const [activeNav, setActiveNav] = useState("stitching");
  const [activeSecondaryTab, setActiveSecondaryTab] = useState("overview");
  const [assistantMode, setAssistantMode] = useState<"manual" | "ai" | "hybrid">("hybrid");
  const [activeStationIndex, setActiveStationIndex] = useState(0);
  const [colorMode, setColorMode] = useState<"rgb" | "height" | "intensity" | "normals" | "error">("rgb");
  const [inspectingElement, setInspectingElement] = useState<Element | null>(null);
  const [selectedCloudIndex, setSelectedCloudIndex] = useState(0);

  // Layers visibility state
  const [layers, setLayers] = useState({
    pointCloud: true,
    stations: true,
    panoramas: true,
    aiStructures: true,
    axes: true,
    dimensions: true,
    drawings: true,
    bimModel: true,
  });

  const toggleLayer = (layerKey: keyof typeof layers) => {
    setLayers((prev) => ({ ...prev, [layerKey]: !prev[layerKey] }));
  };

  const navItems = [
    { id: "home", label: "Главная", icon: "⌂" },
    { id: "projects", label: "Проекты", icon: "📁" },
    { id: "import", label: "Импорт сканов", icon: "📥" },
    { id: "stitching", label: "Сшивка станций", icon: "☍" },
    { id: "pointcloud", label: "Облако точек", icon: "☁" },
    { id: "panoramas", label: "Панорамы 360°", icon: "📷" },
    { id: "recognition", label: "ИИ Распознавание", icon: "🧠" },
    { id: "cad", label: "Чертежи (СПДС)", icon: "📐" },
    { id: "bim", label: "BIM Модель IFC", icon: "🏛" },
    { id: "reports", label: "Паспорта и Отчёты", icon: "📋" },
    { id: "export", label: "Экспорт CAD/DWG", icon: "📤" },
    { id: "settings", label: "Настройки СП", icon: "⚙" },
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
    { id: "Станция 04 (Кровля)", time: "18.10.2026 11:45", pos: [36.0, 0.0, 7.8] as [number, number, number], pts: "142.5M" },
  ];

  const emptyFloatArray = new Float32Array(0);
  const emptySections: [Float32Array, Float32Array, Float32Array] = [
    new Float32Array(0),
    new Float32Array(0),
    new Float32Array(0),
  ];

  const currentCloud = clouds[selectedCloudIndex] || cloud;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", width: "100vw", background: "var(--bg-deep)" }}>
      {/* 1. TOP APPLICATION BAR */}
      <header className="app-header">
        <div className="app-brand">
          <div className="app-logo">S</div>
          <div className="app-title">
            SCAN AI <span className="sub">STUDIO</span>
          </div>

          <div className="project-title-badge">
            <span style={{ color: "var(--accent)" }}>●</span>
            <span>{project?.name || "Цех_№1 (1.rcs + 2.rcs)"}</span>
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>[mmap 6-LOD]</span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {/* Scientific Colormap Switcher */}
          <div style={{ display: "flex", background: "var(--bg-surface)", padding: 2, borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
            {(["rgb", "height", "intensity", "normals", "error"] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setColorMode(mode)}
                style={{
                  background: colorMode === mode ? "var(--accent)" : "transparent",
                  color: colorMode === mode ? "#0A0D11" : "var(--text-secondary)",
                  border: "none",
                  padding: "4px 8px",
                  fontSize: 11,
                  fontWeight: colorMode === mode ? 700 : 500,
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
            <span>GPU / WebGPU: 60 FPS</span>
          </div>

          <button
            className="primary"
            onClick={onRunSinglePass}
            style={{ padding: "5px 14px" }}
          >
            ⚡ Сквозной расчёт цеха
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
                  if (item.id === "panoramas") setActiveSecondaryTab("panoramas");
                }}
              >
                <span className="nav-icon">{item.icon}</span>
                <span>{item.label}</span>
              </div>
            ))}
          </div>

          <div style={{ padding: "8px 12px", background: "var(--bg-surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", fontSize: 11 }}>
            <div style={{ color: "var(--text-muted)", marginBottom: 4 }}>АКТИВНЫЙ СКАНЕР:</div>
            <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>FARO Focus S350</div>
            <div style={{ color: "var(--success)", fontSize: 10, marginTop: 2 }}>● Погрешность: 1.0 мм / 25 м</div>
          </div>
        </aside>

        {/* CENTER 3D VIEWPORT */}
        <main className="viewport-center">
          {/* Floating 3D Tools Ribbon */}
          <div className="viewport-tools-ribbon">
            <button className="ribbon-btn active" title="Выбор"><span>↖</span> Выбор</button>
            <button className="ribbon-btn" title="Измерение"><span>📏</span> Замер</button>
            <button className="ribbon-btn" title="Сечение"><span>✂</span> Разрез</button>
            <button className="ribbon-btn" title="Обрезка"><span>◩</span> Фильтр</button>
            <button className="ribbon-btn" onClick={() => setActiveNav("panoramas")}><span>📷</span> Панорама</button>
            <button
              className="ribbon-btn"
              onClick={() => {
                if (elements.length > 0) {
                  setInspectingElement(selectedElement || elements[0]);
                }
              }}
              style={{ color: "var(--accent)" }}
            >
              <span>🏛</span> ГОСТ Сортамент
            </button>
            <button
              className="ribbon-btn"
              onClick={() => {
                setSelectedCloudIndex((prev) => (prev === 0 ? 1 : 0));
              }}
            >
              <span>🔄</span> Скан {selectedCloudIndex + 1}/{clouds.length || 2}
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
              <span>Слои проекта</span>
              <span style={{ cursor: "pointer" }}>👁</span>
            </div>
            <div style={{ padding: "4px 0" }}>
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
                    <span>{item.label}</span>
                  </div>
                  <span style={{ fontSize: 11 }}>{(layers as any)[item.key] ? "●" : "○"}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Core 3D Viewport Scene or Split-Screen Registration */}
          <div className="scene-container">
            {activeNav === "stitching" || activeSecondaryTab === "stitching" ? (
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
              <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
                Загрузите облако точек для отображения в 3D сцене
              </div>
            )}
          </div>

          {/* BOTTOM DOCK DRAWER */}
          <section className="bottom-dock-container">
            {/* Card 1: Stations */}
            <div className="dock-card" style={{ width: 260, minWidth: 260 }}>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11, fontWeight: 700, color: "var(--text-secondary)" }}>
                <span>СТАНЦИИ СКАНИРОВАНИЯ ({stations.length})</span>
                <span style={{ color: "var(--accent)" }}>● 2.1 мм RMSE</span>
              </div>
              <div style={{ flex: 1, overflowY: "auto", padding: "4px" }}>
                {stations.map((st, idx) => (
                  <div
                    key={st.id}
                    onClick={() => setActiveStationIndex(idx)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "5px 8px",
                      borderRadius: "var(--radius-xs)",
                      background: activeStationIndex === idx ? "var(--accent-subtle)" : "transparent",
                      border: activeStationIndex === idx ? "1px solid var(--accent)" : "1px solid transparent",
                      cursor: "pointer",
                      marginBottom: 2,
                      fontSize: 11,
                    }}
                  >
                    <span style={{ fontWeight: 600, color: activeStationIndex === idx ? "var(--accent)" : "inherit" }}>
                      {st.id}
                    </span>
                    <span style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 10 }}>{st.pts}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Card 2: Interactive 360 Panorama Preview */}
            <div className="dock-card" style={{ width: 340, minWidth: 340, position: "relative" }}>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11, fontWeight: 700, color: "var(--text-secondary)" }}>
                <span>360° REALVIEW+ ПАНОРАМА</span>
                <span style={{ color: "var(--success)" }}>АКТИВНА</span>
              </div>
              <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
                <BubblePanoramaViewer
                  stationName={stations[activeStationIndex].id}
                  stationPosition={stations[activeStationIndex].pos}
                />
              </div>
            </div>

            {/* Card 3: Recognized Elements Schedule */}
            <div className="dock-card" style={{ flex: 1, minWidth: 300 }}>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11, fontWeight: 700, color: "var(--text-secondary)" }}>
                <span>СПЕЦИФИКАЦИЯ ЭЛЕМЕНТОВ (СП 70.13330)</span>
                <span style={{ color: "var(--text-muted)" }}>{elements.length} проверено</span>
              </div>
              <div style={{ flex: 1, overflowY: "auto", padding: "6px" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, textAlign: "left" }}>
                  <thead>
                    <tr style={{ color: "var(--text-muted)", borderBottom: "1px solid var(--border)" }}>
                      <th style={{ padding: "4px 8px" }}>ID</th>
                      <th>Класс</th>
                      <th>ГОСТ Профиль</th>
                      <th>Сечение</th>
                      <th>Крен</th>
                      <th>Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {elements.map((el) => (
                      <tr
                        key={el.id}
                        onClick={() => {
                          onSelectElement(el);
                          setInspectingElement(el);
                        }}
                        style={{
                          cursor: "pointer",
                          borderBottom: "1px solid rgba(255,255,255,0.03)",
                          background: selectedElement?.id === el.id ? "var(--accent-subtle)" : "transparent",
                        }}
                      >
                        <td style={{ padding: "6px 8px", fontWeight: 600, color: "var(--accent)" }}>{el.id}</td>
                        <td>{el.class_name}</td>
                        <td>{el.dimensions?.profile || "Двутавр 30К2"}</td>
                        <td>300 × 300 мм</td>
                        <td style={{ color: "var(--success)" }}>ΔX: +3.2 мм</td>
                        <td>
                          <span style={{ background: "var(--success-bg)", color: "var(--success)", padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 700 }}>
                            НОРМА
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
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

          <div style={{ flex: 1, overflowY: "auto", padding: "12px" }}>
            <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "12px", marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <span style={{ fontWeight: 700, fontSize: 12, color: "var(--accent)" }}>ИИ АССИСТЕНТ SCAN STUDIO</span>
                <span style={{ fontSize: 10, background: "var(--accent-subtle)", color: "var(--accent)", padding: "2px 6px", borderRadius: 3 }}>
                  Active
                </span>
              </div>
              <p style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                Выполнен глобальный уравнитель связей Bundle Adjustment для 1.rcs + 2.rcs.
                Среднеквадратическая ошибка сшивки: <strong>2.1 мм</strong>. Найдено 18 колонн цеха, соответствующих ГОСТ 35087.
              </p>
            </div>

            {/* Quick Action Buttons */}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <button
                onClick={() => setActiveNav("stitching")}
                style={{ width: "100%", justifyContent: "flex-start", padding: "8px 12px" }}
              >
                <span>☍</span> Открыть сплит-сшивку станций
              </button>
              <button
                onClick={() => {
                  if (elements.length > 0) setInspectingElement(elements[0]);
                }}
                style={{ width: "100%", justifyContent: "flex-start", padding: "8px 12px" }}
              >
                <span>🏛</span> Проверить ГОСТ-сортамент колонн
              </button>
              <button
                onClick={() => alert("Экспорт ведомости отклонений по СП 70.13330 в PDF сформирован!")}
                style={{ width: "100%", justifyContent: "flex-start", padding: "8px 12px" }}
              >
                <span>📋</span> Сформировать ведомость отклонений PDF
              </button>
            </div>
          </div>
        </aside>
      </div>

      {/* 4. BOTTOM STATUS STRIP */}
      <footer className="bottom-status-strip">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--accent)" }}></span>
          <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{jobLabel || "Сшивка цеха (Bundle Adjustment)"}</span>
          <span style={{ color: "var(--text-muted)" }}>[Сканов в проекте: 2 | 874.6M точек]</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div className="progress-track-wide">
              <div className="progress-fill-wide" style={{ width: `${jobProgress || 74}%` }}></div>
            </div>
            <span style={{ fontWeight: 700, color: "var(--accent)" }}>{jobProgress || 74}%</span>
          </div>

          <div style={{ display: "flex", gap: 12, fontSize: 11, color: "var(--text-muted)" }}>
            <span>RMSE: <strong style={{ color: "var(--success)" }}>2.1 мм</strong></span>
            <span>Допуск: <strong>СП 70.13330</strong></span>
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
