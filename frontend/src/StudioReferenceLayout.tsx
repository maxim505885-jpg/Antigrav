import React, { useState } from "react";
import "./theme.css";
import Viewer3D from "./components/Viewer3D";
import { BubblePanoramaViewer } from "./components/BubblePanoramaViewer";
import ElementTable from "./components/ElementTable";
import ColumnTypesPanel from "./components/ColumnTypesPanel";
import ColumnSectionFitPanel from "./components/ColumnSectionFitPanel";
import { ManualRegistrationPanel } from "./components/ManualRegistrationPanel";
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
  const [activeNav, setActiveNav] = useState("projects");
  const [activeSecondaryTab, setActiveSecondaryTab] = useState("overview");
  const [assistantMode, setAssistantMode] = useState<"manual" | "ai" | "hybrid">("ai");
  const [activeBottomTab, setActiveBottomTab] = useState<"plans" | "sections" | "facades" | "3d">("plans");
  const [activeStationIndex, setActiveStationIndex] = useState(1);

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
    { id: "import", label: "Импорт", icon: "📥" },
    { id: "stitching", label: "Сшивка", icon: "☍" },
    { id: "pointcloud", label: "Облако точек", icon: "☁" },
    { id: "panoramas", label: "Панорамы", icon: "📷" },
    { id: "recognition", label: "Распознавание", icon: "⚙" },
    { id: "cad", label: "Чертежи (CAD)", icon: "📐" },
    { id: "bim", label: "BIM модель", icon: "🏛" },
    { id: "reports", label: "Отчёты", icon: "📋" },
    { id: "export", label: "Экспорт", icon: "📤" },
    { id: "settings", label: "Настройки", icon: "⚙" },
  ];

  const secondaryTabs = [
    { id: "overview", label: "Обзор" },
    { id: "stitching", label: "Сшивка" },
    { id: "pointcloud", label: "Облако точек" },
    { id: "panoramas", label: "Панорамы" },
    { id: "recognition", label: "Распознавание" },
    { id: "cad", label: "Чертежи" },
    { id: "bim", label: "BIM" },
    { id: "reports", label: "Отчёты" },
  ];

  const stations = [
    { id: "Scan_001", time: "12.10.2026 14:32", pos: [0.0, 0.0, 1.5] as [number, number, number] },
    { id: "Scan_002", time: "12.10.2026 14:45", pos: [6.0, 0.0, 1.5] as [number, number, number] },
    { id: "Scan_003", time: "12.10.2026 15:02", pos: [12.0, 0.0, 1.5] as [number, number, number] },
    { id: "Scan_004", time: "12.10.2026 15:18", pos: [18.0, 0.0, 1.5] as [number, number, number] },
    { id: "Scan_005", time: "12.10.2026 15:41", pos: [24.0, 0.0, 1.5] as [number, number, number] },
    { id: "Scan_006", time: "12.10.2026 16:03", pos: [30.0, 0.0, 1.5] as [number, number, number] },
    { id: "Scan_007", time: "12.10.2026 16:25", pos: [36.0, 0.0, 1.5] as [number, number, number] },
  ];

  const recognizedCounts = {
    walls: elements.filter((e) => e.class_name === "wall").length || 24,
    columns: elements.filter((e) => e.class_name === "column").length || 18,
    beams: elements.filter((e) => e.class_name === "beam").length || 36,
    slabs: elements.filter((e) => e.class_name === "slab").length || 12,
    openings: elements.filter((e) => e.class_name === "opening").length || 27,
    stairs: elements.filter((e) => e.class_name === "stair").length || 4,
    pipes: elements.filter((e) => e.class_name === "pipe").length || 58,
    equipment: 14,
  };

  const emptyFloatArray = new Float32Array();
  const emptySections: [Float32Array, Float32Array, Float32Array] = [
    emptyFloatArray,
    emptyFloatArray,
    emptyFloatArray,
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", width: "100vw", overflow: "hidden" }}>
      {/* 1. TOP HEADER */}
      <header className="app-header">
        <div className="app-brand">
          <div className="app-logo">◬</div>
          <span className="app-title">SCAN AI</span>
          <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: -4 }}>POINT CLOUD STUDIO</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div className="project-title-badge">
            <span style={{ color: "var(--text-muted)" }}>Проект:</span>
            <span style={{ fontWeight: 600 }}>{project?.name || "Завод_Цех_1"}</span>
            <span style={{ color: "var(--text-muted)", cursor: "pointer" }}>✎</span>
          </div>

          <div className="system-status-indicator">
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--success)" }}></span>
            <span>Локальная обработка (RTX 4090)</span>
          </div>

          <button
            className="primary"
            style={{ padding: "4px 12px", fontSize: 12 }}
            onClick={onRunSinglePass}
            disabled={busy}
          >
            <span>✨</span> ИИ-ассистент
          </button>
        </div>

        <div style={{ display: "flex", gap: 8, color: "var(--text-secondary)" }}>
          <span style={{ cursor: "pointer" }}>—</span>
          <span style={{ cursor: "pointer" }}>□</span>
          <span style={{ cursor: "pointer" }}>✕</span>
        </div>
      </header>

      {/* 2. SECONDARY HORIZONTAL TABS */}
      <nav className="secondary-tab-bar">
        {secondaryTabs.map((tab) => (
          <div
            key={tab.id}
            className={`secondary-tab ${activeSecondaryTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveSecondaryTab(tab.id)}
          >
            {tab.label}
          </div>
        ))}
      </nav>

      {/* 3. MAIN WORKSPACE */}
      <div className="studio-layout">
        {/* LEFT NAVIGATION DRAWER */}
        <aside className="sidebar-left">
          <div className="nav-item-list">
            {navItems.slice(0, 11).map((item) => (
              <div
                key={item.id}
                className={`nav-item ${activeNav === item.id ? "active" : ""}`}
                onClick={() => setActiveNav(item.id)}
              >
                <span style={{ fontSize: 16 }}>{item.icon}</span>
                <span>{item.label}</span>
              </div>
            ))}
          </div>

          <div className="nav-item-list" style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
            <div
              className={`nav-item ${activeNav === "settings" ? "active" : ""}`}
              onClick={() => setActiveNav("settings")}
            >
              <span style={{ fontSize: 16 }}>⚙</span>
              <span>Настройки</span>
            </div>
          </div>
        </aside>

        {/* CENTER COLUMN (3D VIEWPORT + BOTTOM DOCK) */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* CENTER 3D VIEWPORT */}
          <main className="viewport-center">
            {/* Floating 3D Tools Ribbon */}
            <div className="viewport-tools-ribbon">
              <button className="ribbon-btn active"><span>↖</span> Выбор</button>
              <button className="ribbon-btn"><span>📏</span> Измерение</button>
              <button className="ribbon-btn"><span>✂</span> Сечение</button>
              <button className="ribbon-btn"><span>◩</span> Обрезка</button>
              <button className="ribbon-btn"><span>•</span> Точка</button>
              <button className="ribbon-btn"><span>📷</span> Панорама</button>
              <button className="ribbon-btn"><span>🎨</span> Цвет</button>
              <button className="ribbon-btn"><span>⋯</span></button>
            </div>

            {/* Navigation Cube Widget */}
            <div className="nav-cube-widget">
              КУБ
            </div>

            {/* Floating Layers Card */}
            <div className="floating-layers-card">
              <div className="card-header-sm">
                <span>Слои</span>
                <span style={{ cursor: "pointer", color: "var(--text-muted)" }}>✕</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {[
                  { key: "pointCloud", label: "Облако точек", color: "#60a5fa" },
                  { key: "stations", label: "Станции сканирования", color: "#38bdf8" },
                  { key: "panoramas", label: "Панорамы", color: "#818cf8" },
                  { key: "aiStructures", label: "Конструкции (AI)", color: "#4ade80" },
                  { key: "axes", label: "Оси", color: "#fb923c" },
                  { key: "dimensions", label: "Размеры", color: "#f43f5e" },
                  { key: "drawings", label: "Чертежи", color: "#e2e8f0" },
                  { key: "bimModel", label: "BIM модель", color: "#a855f7" },
                ].map((item) => (
                  <div key={item.key} className="layer-row">
                    <div className="layer-item-left">
                      <span
                        style={{ cursor: "pointer", fontSize: 13 }}
                        onClick={() => toggleLayer(item.key as any)}
                      >
                        {(layers as any)[item.key] ? "👁" : "⌀"}
                      </span>
                      <span className="layer-color-dot" style={{ background: item.color }}></span>
                      <span>{item.label}</span>
                    </div>
                    <span style={{ color: "var(--text-muted)", cursor: "pointer" }}>⋯</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Core 3D Viewport Scene */}
            <div className="scene-container">
              {cloud ? (
                <Viewer3D
                  cloud={cloud}
                  elements={elements}
                  groupPositions={emptyFloatArray}
                  selectedElement={selectedElement}
                  selectedElementPositions={emptyFloatArray}
                  selectedElementSections={emptySections}
                  pointSize={2.0}
                  colorMode="rgb"
                  showPlane={false}
                  section={null}
                />
              ) : (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
                  Загрузите облако точек для отображения в 3D сцене
                </div>
              )}
            </div>
          </main>

          {/* BOTTOM DOCK DRAWER (Stations | Panorama | Structures | CAD Albums) */}
          <section className="bottom-dock-container">
            {/* Card 1: Stations */}
            <div className="dock-card" style={{ width: 230, minWidth: 230 }}>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, fontWeight: 700 }}>
                <span>Станции сканирования</span>
                <span style={{ color: "var(--text-muted)" }}>✕</span>
              </div>
              <div style={{ flex: 1, overflowY: "auto", padding: "4px 8px" }}>
                {stations.map((st, idx) => (
                  <div
                    key={st.id}
                    onClick={() => setActiveStationIndex(idx)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "6px 8px",
                      borderRadius: "var(--radius-sm)",
                      background: activeStationIndex === idx ? "rgba(255, 129, 46, 0.15)" : "transparent",
                      border: activeStationIndex === idx ? "1px solid var(--accent)" : "1px solid transparent",
                      cursor: "pointer",
                      marginBottom: 4,
                      fontSize: 11,
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ width: 20, height: 16, background: "#334155", borderRadius: 2 }}></span>
                      <span style={{ fontWeight: 600, color: activeStationIndex === idx ? "var(--accent)" : "inherit" }}>{st.id}</span>
                    </div>
                    <span style={{ color: "var(--text-muted)" }}>{st.time.split(" ")[1]}</span>
                  </div>
                ))}
              </div>
              <div style={{ padding: 8, borderTop: "1px solid var(--border)" }}>
                <button className="primary" style={{ width: "100%", fontSize: 12, padding: "6px 0" }}>
                  + Добавить сканы
                </button>
              </div>
            </div>

            {/* Card 2: Station 360 Panorama */}
            <div className="dock-card" style={{ flex: 2, minWidth: 380 }}>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, fontWeight: 700 }}>
                <span>Панорама станции: {stations[activeStationIndex].id}</span>
                <div style={{ display: "flex", gap: 8, color: "var(--text-muted)" }}>
                  <span style={{ cursor: "pointer" }}>⤢</span>
                  <span style={{ cursor: "pointer" }}>📷</span>
                </div>
              </div>
              <div style={{ flex: 1, position: "relative", background: "#000", overflow: "hidden" }}>
                <BubblePanoramaViewer
                  stationName={stations[activeStationIndex].id}
                  stationPosition={stations[activeStationIndex].pos}
                />
              </div>
            </div>

            {/* Card 3: Recognized Structural Elements */}
            <div className="dock-card" style={{ width: 220, minWidth: 220 }}>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, fontWeight: 700 }}>
                <span>Конструкции (ИИ)</span>
                <span style={{ color: "var(--text-muted)" }}>⚙</span>
              </div>
              <div style={{ flex: 1, overflowY: "auto", padding: "6px 12px", display: "flex", flexDirection: "column", gap: 6, fontSize: 12 }}>
                {[
                  { label: "Стены", count: recognizedCounts.walls, icon: "🧱" },
                  { label: "Колонны", count: recognizedCounts.columns, icon: "🏛" },
                  { label: "Балки", count: recognizedCounts.beams, icon: "━" },
                  { label: "Перекрытия", count: recognizedCounts.slabs, icon: "▤" },
                  { label: "Проёмы", count: recognizedCounts.openings, icon: "🚪" },
                  { label: "Лестницы", count: recognizedCounts.stairs, icon: "🪜" },
                  { label: "Трубы", count: recognizedCounts.pipes, icon: "〰" },
                  { label: "Оборудование", count: recognizedCounts.equipment, icon: "⚙" },
                ].map((row) => (
                  <div key={row.label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", color: "var(--text-secondary)" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span>{row.icon}</span>
                      <span>{row.label}</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontWeight: 600, color: "var(--text-main)" }}>{row.count}</span>
                      <span style={{ cursor: "pointer", color: "var(--text-muted)", fontSize: 11 }}>👁</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Card 4: Drawings and Models Preview */}
            <div className="dock-card" style={{ width: 280, minWidth: 280 }}>
              <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, fontWeight: 700 }}>
                <span>Чертежи и модели</span>
                <span style={{ color: "var(--text-muted)" }}>✕</span>
              </div>
              <div style={{ display: "flex", borderBottom: "1px solid var(--border)", fontSize: 11 }}>
                {(["plans", "sections", "facades", "3d"] as const).map((sub) => (
                  <div
                    key={sub}
                    onClick={() => setActiveBottomTab(sub)}
                    style={{
                      flex: 1,
                      textAlign: "center",
                      padding: "6px 0",
                      cursor: "pointer",
                      fontWeight: activeBottomTab === sub ? 700 : 400,
                      color: activeBottomTab === sub ? "var(--accent)" : "var(--text-secondary)",
                      borderBottom: activeBottomTab === sub ? "2px solid var(--accent)" : "none",
                    }}
                  >
                    {sub === "plans" ? "Планы" : sub === "sections" ? "Разрезы" : sub === "facades" ? "Фасады" : "3D"}
                  </div>
                ))}
              </div>
              <div style={{ flex: 1, padding: 8, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, overflowY: "auto" }}>
                <div style={{ background: "#111827", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 6, textAlign: "center" }}>
                  <div style={{ height: 60, background: "#1f2937", borderRadius: 2, marginBottom: 4, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "var(--text-muted)" }}>
                    [DWG 1]
                  </div>
                  <span style={{ fontSize: 10, color: "var(--text-secondary)" }}>План 1 эт.dwg</span>
                </div>
                <div style={{ background: "#111827", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 6, textAlign: "center" }}>
                  <div style={{ height: 60, background: "#1f2937", borderRadius: 2, marginBottom: 4, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "var(--text-muted)" }}>
                    [DWG 2]
                  </div>
                  <span style={{ fontSize: 10, color: "var(--text-secondary)" }}>Разрез 1-1.dwg</span>
                </div>
              </div>
            </div>
          </section>
        </div>

        {/* RIGHT SIDEBAR: AI ASSISTANT & PIPELINE STEPS */}
        <aside className="sidebar-right">
          <div className="assistant-header">
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: "var(--accent)", fontSize: 16 }}>✦</span>
              <span style={{ fontWeight: 700, fontSize: 14 }}>ИИ-ассистент</span>
            </div>
            <span style={{ fontSize: 12, color: "var(--text-muted)", cursor: "pointer" }}>Свернуть</span>
          </div>

          {/* Mode Switcher: Manual | AI | Hybrid */}
          <div className="mode-pill-selector">
            {(["manual", "ai", "hybrid"] as const).map((m) => (
              <div
                key={m}
                className={`mode-pill ${assistantMode === m ? "active" : ""}`}
                onClick={() => setAssistantMode(m)}
              >
                {m === "manual" ? "Ручной" : m === "ai" ? "ИИ-режим" : "Гибридный"}
              </div>
            ))}
          </div>

          {/* Stepper Pipeline */}
          <div className="stepper-list">
            {[
              { num: 1, title: "Загрузка данных", desc: "FARO, E57, LAS/LAZ, RCP, RCS", done: true },
              { num: 2, title: "Анализ сканов (ИИ)", desc: "Поиск станций и перекрытий", done: true },
              { num: 3, title: "Автоматическая сшивка", desc: "Регистрация и оптимизация", active: true },
              { num: 4, title: "Контроль качества", desc: "Проверка невязок и ошибок" },
              { num: 5, title: "Распознавание конструкций", desc: "Стены, колонны, балки, перекрытия" },
              { num: 6, title: "Построение чертежей", desc: "Планы, разрезы, фасады" },
              { num: 7, title: "Экспорт", desc: "E57, DXF, DWG, IFC, RVT" },
            ].map((st) => (
              <div
                key={st.num}
                className={`step-card ${st.active ? "active" : ""} ${st.done ? "done" : ""}`}
              >
                <div className="step-badge">
                  {st.done ? "✓" : st.num}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: st.active ? "var(--accent)" : "inherit" }}>
                    {st.title}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                    {st.desc}
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div style={{ padding: "16px 16px 8px 16px", marginTop: "auto" }}>
            <button
              className="primary"
              style={{ width: "100%", padding: "10px 0", fontSize: 13 }}
              onClick={onRunSinglePass}
              disabled={busy}
            >
              <span>⚙</span> Запустить ИИ-обработку
            </button>
            <div style={{ textAlign: "center", marginTop: 8, fontSize: 11, color: "var(--text-muted)", cursor: "pointer" }}>
              Дополнительные параметры ⌄
            </div>
          </div>
        </aside>
      </div>

      {/* 4. BOTTOM PROCESSING STATUS STRIP */}
      <footer className="bottom-status-strip">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ width: 14, height: 14, borderRadius: "50%", background: "var(--accent)" }}></span>
          <div style={{ fontWeight: 600, color: "var(--text-main)" }}>
            Автоматическая сшивка (ИИ)
          </div>
          <span style={{ color: "var(--text-muted)" }}>
            Регистрация скан 12 из 28...
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div className="progress-track-wide">
              <div className="progress-fill-wide" style={{ width: `${jobProgress || 68}%` }}></div>
            </div>
            <span style={{ fontWeight: 700, color: "var(--text-main)" }}>{jobProgress || 68}%</span>
          </div>

          <div style={{ display: "flex", gap: 14, fontSize: 11, color: "var(--text-muted)" }}>
            <span>Найдено перекрытий: <b>26</b></span>
            <span>Средняя невязка: <b>8.4 мм</b></span>
            <span>Время: <b>12 мин</b></span>
          </div>

          <div style={{ display: "flex", gap: 6 }}>
            <button style={{ padding: "4px 10px", fontSize: 11 }}>⏸ Пауза</button>
            <button className="danger" style={{ padding: "4px 10px", fontSize: 11 }}>■ Остановить</button>
          </div>
        </div>
      </footer>
    </div>
  );
};
