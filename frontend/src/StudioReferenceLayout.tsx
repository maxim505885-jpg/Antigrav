import React, { useState } from "react";
import Viewer3D, { type CameraPreset } from "./components/Viewer3D";
import { BubblePanoramaViewer } from "./components/BubblePanoramaViewer";
import { GostProfileInspectorModal } from "./components/GostProfileInspectorModal";
import { type Cloud, type Element, type Project } from "./types";
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
  selectedElement: Element | null;
  onSelectElement: (el: Element | null) => void;
  onRunSinglePass: (cloudId: string | null) => void;
  onCloudChange: (cloudId: string) => void;
  onProjectChange: (projectId: string) => void;
  onCreateProject?: (name: string) => Promise<void>;
  onUploadScan?: (file: File) => Promise<void>;
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
  selectedElement,
  onSelectElement,
  onRunSinglePass,
  onCloudChange,
  onProjectChange,
  busy,
  jobLabel,
  jobProgress,
}) => {
  // Navigation & Viewport State
  const [activeTopTab, setActiveTopTab] = useState("processing");
  const [activeSideNav, setActiveSideNav] = useState("processing");
  const [activeStepper, setActiveStepper] = useState(4); // 4 = Распознавание
  const [viewportTab, setViewportTab] = useState<"cloud" | "rgb" | "classes" | "mesh">("cloud");
  const [colorMode, setColorMode] = useState<"rgb" | "height" | "intensity" | "classes">("rgb");
  const [measureMode, setMeasureMode] = useState(false);
  const [showLimitBox, setShowLimitBox] = useState(false);
  const [inspectingElement, setInspectingElement] = useState<Element | null>(null);

  // Stations & Panorama State
  const workshopStations = [
    { id: "FARO_001", name: "FARO_001", position: [-13.25, -20.0, 1.6] as [number, number, number] },
    { id: "FARO_002", name: "FARO_002", position: [-6.5, -10.0, 1.6] as [number, number, number] },
    { id: "FARO_003", name: "FARO_003", position: [0.0, 0.0, 1.6] as [number, number, number] },
    { id: "FARO_004", name: "FARO_004", position: [6.5, 10.0, 1.6] as [number, number, number] },
    { id: "FARO_005", name: "FARO_005", position: [13.25, 20.0, 1.6] as [number, number, number] },
  ];
  const [selectedStation, setSelectedStation] = useState(workshopStations[2]);
  const [panoramaOpen, setPanoramaOpen] = useState(false);

  // Object Properties Tab State
  const [objTab, setObjTab] = useState<"general" | "geometry" | "classes" | "attributes">("general");

  // Element Counts
  const beamsCount = elements.filter(e => e.class_name === "beam" || e.class_name === "crane_girder").length || 124;
  const columnsCount = elements.filter(e => e.class_name === "column").length || 36;
  const slabsCount = elements.filter(e => e.class_name === "slab").length || 28;
  const pipesCount = elements.filter(e => e.class_name === "pipe").length || 52;
  const wallsCount = elements.filter(e => e.class_name === "wall").length || 18;
  const equipCount = 16;
  const totalObjectsCount = elements.length > 0 ? elements.length : 256;

  // Selected Object Details
  const activeObjName = selectedElement ? `Элемент ${selectedElement.id.slice(0, 7)}` : "Резервуар Р-1";
  const activeObjClass = selectedElement?.class_name ? selectedElement.class_name.toUpperCase() : "Оборудование";

  return (
    <div style={{ display: "flex", flexDirection: "column", width: "100vw", height: "100vh", background: "#0c0a1a", color: "#f8fafc", fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", overflow: "hidden", userSelect: "none" }}>
      
      {/* 1. TOP HEADER */}
      <header style={{ height: 48, background: "#121026", borderBottom: "1px solid #231f47", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 14px", flexShrink: 0 }}>
        {/* Left: Brand Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", width: 28, height: 28 }}>
            <Hexagon size={28} color="#8b5cf6" fill="#6d28d9" style={{ opacity: 0.85 }} />
            <Sparkles size={14} color="#ffffff" style={{ position: "absolute" }} />
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: 13.5, fontWeight: 900, letterSpacing: 0.8, color: "#ffffff", lineHeight: 1.1 }}>SCAN STUDIO 4.0</span>
            <span style={{ fontSize: 8.5, fontWeight: 700, color: "#a78bfa", letterSpacing: 0.6 }}>ОТ ОБЛАКА ТОЧЕК К ЧЕРТЕЖУ</span>
          </div>
        </div>

        {/* Center: Main Navigation Tabs (Pills) */}
        <div style={{ display: "flex", alignItems: "center", gap: 4, background: "#0c0a1a", padding: "3px 5px", borderRadius: 20, border: "1px solid #231f47" }}>
          {[
            { id: "projects", label: "Проекты", icon: <Folder size={13} /> },
            { id: "processing", label: "Обработка", icon: <Network size={13} /> },
            { id: "recognition", label: "Распознавание", icon: <Scan size={13} /> },
            { id: "drafting", label: "Чертежи", icon: <Sliders size={13} /> },
            { id: "bim", label: "BIM", icon: <Box size={13} /> },
            { id: "reports", label: "Отчёты", icon: <FileText size={13} /> },
          ].map((tab) => {
            const isActive = activeTopTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTopTab(tab.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 16,
                  background: isActive ? "linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)" : "transparent",
                  color: isActive ? "#ffffff" : "#94a3b8", border: "none", fontSize: 11.5, fontWeight: isActive ? 700 : 500,
                  cursor: "pointer", boxShadow: isActive ? "0 0 10px rgba(124, 58, 237, 0.45)" : "none", transition: "all 0.15s ease"
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
          <div style={{ display: "flex", alignItems: "center", gap: 7, background: "#1c183b", border: "1px solid #2e285a", borderRadius: 18, padding: "4px 12px", width: 220 }}>
            <Search size={13} color="#8b5cf6" />
            <input
              type="text"
              placeholder="Поиск по проекту, объектам..."
              style={{ background: "transparent", border: "none", color: "#f8fafc", fontSize: 11, outline: "none", width: "100%" }}
            />
          </div>
          <button style={{ background: "transparent", border: "none", color: "#94a3b8", cursor: "pointer", display: "grid", placeItems: "center" }}><Bell size={15} /></button>
          <button style={{ background: "transparent", border: "none", color: "#94a3b8", cursor: "pointer", display: "grid", placeItems: "center" }}><Settings size={15} /></button>
          <div style={{ width: 1, height: 16, background: "#2e285a" }} />
          <div style={{ display: "flex", gap: 6, alignItems: "center", color: "#64748b" }}>
            <span style={{ fontSize: 12, cursor: "pointer" }}>—</span>
            <span style={{ fontSize: 11, cursor: "pointer" }}>□</span>
            <span style={{ fontSize: 12, cursor: "pointer" }}>✕</span>
          </div>
          <div style={{ width: 26, height: 26, borderRadius: "50%", background: "#6d28d9", display: "grid", placeItems: "center", border: "1px solid #8b5cf6", marginLeft: 4 }}>
            <User size={14} color="#ffffff" />
          </div>
        </div>
      </header>

      {/* 2. MAIN WORKSPACE ROW */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        
        {/* LEFT SIDEBAR */}
        <aside style={{ width: 195, background: "#100e22", borderRight: "1px solid #231f47", display: "flex", flexDirection: "column", padding: "10px 8px", flexShrink: 0, gap: 10 }}>
          
          {/* Project Header Card */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: 8, background: "#191535", borderRadius: 8, border: "1px solid #2e285a" }}>
            <div style={{ height: 48, borderRadius: 5, background: "linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)", display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", position: "relative" }}>
              <Building size={28} color="#818cf8" style={{ opacity: 0.6 }} />
              <div style={{ position: "absolute", bottom: 4, left: 6, fontSize: 8.5, background: "rgba(15, 23, 42, 0.75)", padding: "1px 5px", borderRadius: 3, color: "#c7d2fe" }}>
                138 × 38.2 м
              </div>
            </div>
            <div>
              <select
                value={project?.id || ""}
                onChange={(e) => onProjectChange(e.target.value)}
                style={{ width: "100%", background: "transparent", color: "#ffffff", border: "none", fontSize: 12.5, fontWeight: 800, outline: "none", cursor: "pointer" }}
              >
                {projects.map(p => <option key={p.id} value={p.id} style={{ background: "#100e22", color: "#fff" }}>{p.name}</option>)}
              </select>
              <div style={{ fontSize: 9.5, color: "#818cf8", marginTop: 1 }}>Производственный корпус</div>
            </div>
          </div>

          {/* Navigation Links */}
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {[
              { id: "data", label: "Данные", icon: <Database size={13} /> },
              { id: "processing", label: "Обработка", icon: <Network size={13} /> },
              { id: "results", label: "Результаты", icon: <BarChart3 size={13} /> },
              { id: "drawings", label: "Чертежи", icon: <Sliders size={13} /> },
              { id: "bim_model", label: "BIM модель", icon: <Box size={13} /> },
              { id: "reports_side", label: "Отчёты", icon: <FileText size={13} /> },
              { id: "settings_side", label: "Настройки", icon: <Settings size={13} /> },
            ].map(item => {
              const active = activeSideNav === item.id;
              return (
                <div
                  key={item.id}
                  onClick={() => setActiveSideNav(item.id)}
                  style={{
                    display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", borderRadius: 6,
                    background: active ? "linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)" : "transparent",
                    color: active ? "#ffffff" : "#94a3b8", cursor: "pointer", fontSize: 11, fontWeight: active ? 700 : 500,
                    boxShadow: active ? "0 0 10px rgba(124, 58, 237, 0.45)" : "none", transition: "all 0.12s ease"
                  }}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </div>
              );
            })}
          </div>

          {/* Sources Section */}
          <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ fontSize: 10, fontWeight: 800, color: "#6b7280", letterSpacing: 0.5, padding: "0 6px" }}>ИСТОЧНИКИ ДАННЫХ</div>
            {[
              { label: "FARO сканы", count: 48, active: true },
              { label: "Лазерные сканы", count: 12 },
              { label: "Фото (360°)", count: 320 },
              { label: "Планы / CAD", count: 8 },
              { label: "Документы", count: 24 },
            ].map(s => (
              <div
                key={s.label}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between", padding: "4px 8px", borderRadius: 4,
                  background: s.active ? "rgba(124, 58, 237, 0.2)" : "transparent", border: s.active ? "1px solid rgba(139, 92, 246, 0.4)" : "1px solid transparent",
                  fontSize: 10.5, color: s.active ? "#c4b5fd" : "#94a3b8", cursor: "pointer"
                }}
              >
                <span>{s.label}</span>
                <span style={{ fontSize: 9.5, background: "#1e1b4b", color: "#a78bfa", padding: "1px 5px", borderRadius: 8, fontWeight: 700 }}>{s.count}</span>
              </div>
            ))}
          </div>

          {/* Storage Meter */}
          <div style={{ marginTop: "auto", padding: "8px 6px", background: "#151329", borderRadius: 6, border: "1px solid #231f47", fontSize: 9.5 }}>
            <div style={{ display: "flex", justifyContent: "space-between", color: "#94a3b8", marginBottom: 4 }}>
              <span>Хранилище</span>
              <strong style={{ color: "#ffffff" }}>327 ГБ из 1 ТБ</strong>
            </div>
            <div style={{ width: "100%", height: 5, background: "#26214d", borderRadius: 3, overflow: "hidden" }}>
              <div style={{ width: "32.7%", height: "100%", background: "linear-gradient(90deg, #8b5cf6 0%, #ec4899 100%)" }} />
            </div>
          </div>
        </aside>

        {/* WORKSPACE CONTENT AREA (TOP & BOTTOM) */}
        <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
          
          {/* TOP SECTION: PIPELINE + 3D VIEWPORT */}
          <div style={{ display: "flex", flex: 1.25, minHeight: 0, borderBottom: "1px solid #231f47" }}>
            
            {/* LEFT: ИИ-КОНВЕЙЕР ОБРАБОТКИ (NODE GRAPH) */}
            <div style={{ flex: 1.2, background: "#110f24", padding: "10px 14px", display: "flex", flexDirection: "column", gap: 8, overflow: "hidden", borderRight: "1px solid #231f47" }}>
              
              {/* Stepper Header Bar */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "#161331", padding: "5px 12px", borderRadius: 20, border: "1px solid #2e285a" }}>
                {[
                  { step: 1, label: "Импорт", done: true },
                  { step: 2, label: "Сшивка", done: true },
                  { step: 3, label: "Очистка", done: true },
                  { step: 4, label: "Распознавание", active: true },
                  { step: 5, label: "Моделирование" },
                  { step: 6, label: "Чертежи" },
                ].map(st => (
                  <div
                    key={st.step}
                    onClick={() => setActiveStepper(st.step)}
                    style={{
                      display: "flex", alignItems: "center", gap: 5, padding: "3px 9px", borderRadius: 14,
                      background: st.active ? "linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)" : "transparent",
                      boxShadow: st.active ? "0 0 10px rgba(124, 58, 237, 0.5)" : "none",
                      color: st.active ? "#ffffff" : st.done ? "#10b981" : "#64748b",
                      fontSize: 10.5, fontWeight: st.active ? 800 : 600, cursor: "pointer"
                    }}
                  >
                    <span style={{ width: 15, height: 15, borderRadius: "50%", background: st.active ? "#ffffff" : st.done ? "#10b981" : "#334155", color: st.active ? "#6d28d9" : "#0c0a1a", display: "grid", placeItems: "center", fontSize: 8.5, fontWeight: 900 }}>
                      {st.done ? "✓" : st.step}
                    </span>
                    <span>{st.label}</span>
                  </div>
                ))}
              </div>

              {/* Sub-toolbar */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 4px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <Sparkles size={14} color="#a78bfa" />
                  <span style={{ fontSize: 12, fontWeight: 800, color: "#ffffff" }}>ИИ-Конвейер обработки</span>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button style={{ background: "#1c183b", border: "1px solid #2e285a", color: "#c4b5fd", padding: "3px 8px", borderRadius: 5, fontSize: 10, cursor: "pointer" }}>⚙ Настройки конвейера</button>
                  <button style={{ background: "#1c183b", border: "1px solid #2e285a", color: "#c4b5fd", padding: "3px 8px", borderRadius: 5, fontSize: 10, cursor: "pointer" }}>💾 Сохранить как шаблон</button>
                </div>
              </div>

              {/* Visual Node Graph Cards */}
              <div style={{ flex: 1, display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8, alignItems: "stretch", overflow: "hidden", position: "relative" }}>
                
                {/* Node 1: Импорт данных */}
                <div style={{ background: "#171434", borderRadius: 8, border: "1px solid #2e285a", padding: 8, display: "flex", flexDirection: "column", gap: 6, fontSize: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #26214d", paddingBottom: 4 }}>
                    <span style={{ fontWeight: 800, color: "#ffffff" }}>Импорт данных</span>
                    <CheckCircle2 size={13} color="#10b981" />
                  </div>
                  <div style={{ height: 46, borderRadius: 4, background: "#211c47", display: "grid", placeItems: "center", color: "#a78bfa" }}>
                    <Database size={20} />
                  </div>
                  <div style={{ color: "#a78bfa", fontWeight: 700 }}>48 станций</div>
                  <div style={{ fontSize: 9, color: "#94a3b8" }}>Тип: FARO, E57, LAS</div>
                  <div style={{ marginTop: "auto", fontSize: 8.5, background: "#10b98122", color: "#10b981", padding: "2px 4px", borderRadius: 3, fontWeight: 700, textAlign: "center" }}>
                    324 ГБ · Загружено
                  </div>
                </div>

                {/* Node 2: Регистрация / Сшивка */}
                <div style={{ background: "#171434", borderRadius: 8, border: "1px solid #2e285a", padding: 8, display: "flex", flexDirection: "column", gap: 5, fontSize: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #26214d", paddingBottom: 4 }}>
                    <span style={{ fontWeight: 800, color: "#ffffff" }}>Сшивка</span>
                    <CheckCircle2 size={13} color="#10b981" />
                  </div>
                  <div style={{ height: 46, borderRadius: 4, background: "#211c47", display: "grid", placeItems: "center", color: "#38bdf8" }}>
                    <Activity size={20} />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <span style={{ fontSize: 8.5, color: "#94a3b8" }}>Точность:</span>
                    <div style={{ background: "#211c47", padding: "2px 4px", borderRadius: 3, color: "#e2e8f0", fontSize: 9 }}>Высокая</div>
                  </div>
                  <div style={{ marginTop: "auto", fontSize: 8.5, color: "#10b981", fontWeight: 700 }}>
                    СКО: 2.8 мм · 2 мин 14 с
                  </div>
                </div>

                {/* Node 3: Очистка облака */}
                <div style={{ background: "#171434", borderRadius: 8, border: "1px solid #2e285a", padding: 8, display: "flex", flexDirection: "column", gap: 5, fontSize: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #26214d", paddingBottom: 4 }}>
                    <span style={{ fontWeight: 800, color: "#ffffff" }}>Очистка</span>
                    <CheckCircle2 size={13} color="#10b981" />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3, margin: "auto 0" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, color: "#e2e8f0", fontSize: 9 }}>
                      <CheckSquare size={10} color="#8b5cf6" /> Удаление шума
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, color: "#e2e8f0", fontSize: 9 }}>
                      <CheckSquare size={10} color="#8b5cf6" /> Классификация
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, color: "#e2e8f0", fontSize: 9 }}>
                      <CheckSquare size={10} color="#8b5cf6" /> Фильтр выбросов
                    </div>
                  </div>
                  <div style={{ marginTop: "auto", fontSize: 8.5, color: "#38bdf8", fontWeight: 700 }}>
                    Удалено 12.4M · 1 мин 02 с
                  </div>
                </div>

                {/* Node 4: Распознавание конструкций */}
                <div style={{ background: "#1a163a", borderRadius: 8, border: "1px solid #8b5cf6", padding: 8, display: "flex", flexDirection: "column", gap: 4, fontSize: 9.5, boxShadow: "0 0 12px rgba(139, 92, 246, 0.25)" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #3b3564", paddingBottom: 3 }}>
                    <span style={{ fontWeight: 800, color: "#c4b5fd" }}>Распознавание</span>
                    <CheckCircle2 size={13} color="#10b981" />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}><span>Балки:</span> <strong>{beamsCount}</strong></div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}><span>Колонны:</span> <strong>{columnsCount}</strong></div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}><span>Плиты:</span> <strong>{slabsCount}</strong></div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}><span>Трубы:</span> <strong>{pipesCount}</strong></div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}><span>Стены:</span> <strong>{wallsCount}</strong></div>
                  </div>
                  <div style={{ marginTop: "auto", fontSize: 8.5, color: "#10b981", fontWeight: 700 }}>
                    {totalObjectsCount} объектов · 2 мин 36 с
                  </div>
                </div>

                {/* Node 5: Создание чертежей */}
                <div style={{ background: "#171434", borderRadius: 8, border: "1px solid #2e285a", padding: 8, display: "flex", flexDirection: "column", gap: 5, fontSize: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #26214d", paddingBottom: 4 }}>
                    <span style={{ fontWeight: 800, color: "#ffffff" }}>Чертежи</span>
                    <CheckCircle2 size={13} color="#10b981" />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3, margin: "auto 0", fontSize: 9 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><CheckSquare size={10} color="#8b5cf6" /> План этажа</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><CheckSquare size={10} color="#8b5cf6" /> Разрезы</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><CheckSquare size={10} color="#8b5cf6" /> Узлы</div>
                  </div>
                  <button
                    onClick={() => onRunSinglePass(cloud?.id || null)}
                    disabled={busy}
                    style={{
                      background: "linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)",
                      color: "#ffffff", border: "none", borderRadius: 5, padding: "5px 0",
                      fontWeight: 800, fontSize: 10.5, cursor: busy ? "wait" : "pointer",
                      display: "flex", alignItems: "center", justifyContent: "center", gap: 4,
                      boxShadow: "0 0 10px rgba(124, 58, 237, 0.45)"
                    }}
                  >
                    <Play size={11} fill="#ffffff" />
                    <span>{busy ? "Обработка..." : "Запустить"}</span>
                  </button>
                </div>

              </div>
            </div>

            {/* RIGHT: 3D VIEWPORT */}
            <div style={{ flex: 1, background: "#0c0a1a", display: "flex", flexDirection: "column", position: "relative", overflow: "hidden" }}>
              
              {/* Viewport Top Bar */}
              <div style={{ height: 32, background: "#14112b", borderBottom: "1px solid #231f47", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 10px" }}>
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
                        background: viewportTab === tab.id ? "#7c3aed" : "transparent",
                        color: viewportTab === tab.id ? "#ffffff" : "#94a3b8",
                        border: "none", borderRadius: 12, padding: "2px 8px", fontSize: 10, fontWeight: 700, cursor: "pointer"
                      }}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#94a3b8" }}>
                  <Eye size={13} style={{ cursor: "pointer" }} />
                  <Layers size={13} style={{ cursor: "pointer" }} />
                  <Settings size={13} style={{ cursor: "pointer" }} />
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
                  measureModeActive={measureMode}
                  onToggleMeasureMode={setMeasureMode}
                  limitBoxActive={showLimitBox}
                  onToggleLimitBox={setShowLimitBox}
                />

                {/* Floating Left 3D Tools Toolbar */}
                <div style={{ position: "absolute", left: 10, top: 10, display: "flex", flexDirection: "column", gap: 5, background: "rgba(18, 16, 38, 0.85)", backdropFilter: "blur(6px)", padding: 4, borderRadius: 6, border: "1px solid #2e285a", zIndex: 10 }}>
                  <button title="Выбор" style={{ background: "transparent", border: "none", color: "#8b5cf6", cursor: "pointer", padding: 4 }}><Crosshair size={14} /></button>
                  <button title="3D Замер" onClick={() => setMeasureMode(!measureMode)} style={{ background: measureMode ? "#7c3aed" : "transparent", border: "none", color: "#ffffff", borderRadius: 4, cursor: "pointer", padding: 4 }}><Maximize2 size={14} /></button>
                  <button title="Limit Box" onClick={() => setShowLimitBox(!showLimitBox)} style={{ background: showLimitBox ? "#7c3aed" : "transparent", border: "none", color: "#ffffff", borderRadius: 4, cursor: "pointer", padding: 4 }}><Layers size={14} /></button>
                  <button title="Панорама 360" onClick={() => setPanoramaOpen(true)} style={{ background: "transparent", border: "none", color: "#c4b5fd", cursor: "pointer", padding: 4 }}><Camera size={14} /></button>
                </div>
              </div>

              {/* Viewport Bottom Colormap Toolbar */}
              <div style={{ height: 28, background: "#14112b", borderTop: "1px solid #231f47", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 8px" }}>
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
                        background: colorMode === mode.id ? "#7c3aed" : "#1c183b",
                        color: colorMode === mode.id ? "#ffffff" : "#94a3b8",
                        border: "1px solid #2e285a", borderRadius: 10, padding: "1px 7px", fontSize: 9.5, cursor: "pointer"
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
          <div style={{ display: "flex", flex: 1, minHeight: 0, background: "#0c0a1a", padding: "8px 12px", gap: 10 }}>
            
            {/* CARD 1: ЖУРНАЛ ВЫПОЛНЕНИЯ */}
            <div style={{ flex: 1, background: "#131028", borderRadius: 8, border: "1px solid #231f47", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #211c47", paddingBottom: 4 }}>
                <span style={{ fontSize: 11.5, fontWeight: 800, color: "#ffffff" }}>Журнал выполнения</span>
                <div style={{ display: "flex", gap: 3 }}>
                  <span style={{ background: "#7c3aed", color: "#ffffff", padding: "1px 6px", borderRadius: 8, fontSize: 9, fontWeight: 700 }}>Все 12</span>
                  <span style={{ background: "#1c183b", color: "#10b981", padding: "1px 6px", borderRadius: 8, fontSize: 9 }}>Успехи</span>
                </div>
              </div>
              <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6, fontSize: 9.5 }}>
                {[
                  { time: "14:32", title: "Импорт данных — 48 станций", status: "Успешно завершено", dur: "8 с" },
                  { time: "14:34", title: "Регистрация облаков", status: "Совмещение 0.8 мм", dur: "2 мин 14 с" },
                  { time: "14:37", title: "Очистка облака", status: "Удалено 12.4 млн точек", dur: "1 мин 02 с" },
                  { time: "14:38", title: "Классификация объектов", status: "Выделено 256 элементов", dur: "2 мин 36 с" },
                  { time: "14:41", title: "Построение чертежей", status: "План этажа готов", dur: "32 с" },
                ].map((item, idx) => (
                  <div key={idx} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "#171434", padding: "4px 6px", borderRadius: 4 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ color: "#6b7280" }}>{item.time}</span>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#10b981" }} />
                      <div>
                        <div style={{ fontWeight: 700, color: "#f8fafc" }}>{item.title}</div>
                        <div style={{ color: "#94a3b8", fontSize: 8.5 }}>{item.status}</div>
                      </div>
                    </div>
                    <span style={{ color: "#818cf8", fontSize: 9 }}>{item.dur}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* CARD 2: СТАНЦИИ + ПЛАН ЭТАЖА CAD */}
            <div style={{ flex: 1.5, display: "flex", flexDirection: "column", gap: 8 }}>
              
              {/* Top subcard: Миниатюры станций (48) */}
              <div style={{ flex: 1, background: "#131028", borderRadius: 8, border: "1px solid #231f47", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 11, fontWeight: 800, color: "#ffffff" }}>Миниатюры станций (48)</span>
                  <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <span style={{ fontSize: 9.5, color: "#94a3b8" }}>Все станции ▾</span>
                    <button style={{ background: "#1c183b", border: "none", color: "#c4b5fd", borderRadius: 3, padding: "1px 5px", cursor: "pointer" }}>‹</button>
                    <button style={{ background: "#1c183b", border: "none", color: "#c4b5fd", borderRadius: 3, padding: "1px 5px", cursor: "pointer" }}>›</button>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flex: 1, overflowX: "auto", alignItems: "center" }}>
                  {workshopStations.map(st => {
                    const sel = selectedStation.id === st.id;
                    return (
                      <div
                        key={st.id}
                        onClick={() => { setSelectedStation(st); setPanoramaOpen(true); }}
                        style={{
                          flex: 1, minWidth: 68, height: 42, background: sel ? "rgba(124, 58, 237, 0.25)" : "#181538",
                          border: sel ? "1px solid #8b5cf6" : "1px solid #2e285a", borderRadius: 4,
                          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                          cursor: "pointer", fontSize: 9, color: sel ? "#c4b5fd" : "#94a3b8"
                        }}
                      >
                        <Camera size={13} color={sel ? "#8b5cf6" : "#64748b"} />
                        <span>{st.name}</span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Bottom subcard: План этажа (результат) */}
              <div style={{ flex: 1.3, background: "#131028", borderRadius: 8, border: "1px solid #231f47", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 11, fontWeight: 800, color: "#ffffff" }}>План этажа (результат)</span>
                  <button
                    onClick={() => {
                      if (cloud?.id) window.open(`/api/v1/clouds/${cloud.id}/elements.dxf`, "_blank");
                    }}
                    style={{ background: "#7c3aed", color: "#ffffff", border: "none", borderRadius: 4, padding: "2px 8px", fontSize: 9.5, fontWeight: 700, cursor: "pointer" }}
                  >
                    📐 Открыть в CAD
                  </button>
                </div>
                <div style={{ flex: 1, display: "flex", gap: 6, alignItems: "center" }}>
                  {/* Schematic Vector Drawing */}
                  <div style={{ flex: 1, height: "100%", background: "#0a0817", borderRadius: 4, border: "1px solid #211c47", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
                    <svg width="100%" height="100%" viewBox="0 0 200 60" style={{ padding: 4 }}>
                      <rect x="5" y="5" width="190" height="50" fill="none" stroke="#3b3564" strokeWidth="1" strokeDasharray="2,2" />
                      <line x1="5" y1="20" x2="195" y2="20" stroke="#4c4482" strokeWidth="1" />
                      <line x1="5" y1="38" x2="195" y2="38" stroke="#4c4482" strokeWidth="1" />
                      {/* Columns */}
                      {[15, 45, 75, 105, 135, 165, 185].map(x => (
                        <g key={x}>
                          <rect x={x-2} y={3} width="4" height="4" fill="#10b981" />
                          <rect x={x-2} y={18} width="4" height="4" fill="#10b981" />
                          <rect x={x-2} y={36} width="4" height="4" fill="#10b981" />
                          <rect x={x-2} y={51} width="4" height="4" fill="#10b981" />
                        </g>
                      ))}
                    </svg>
                  </div>
                  {/* Legend */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 8.5, color: "#94a3b8" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: "#f59e0b" }}>■</span> Стены</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: "#10b981" }}>■</span> Колонны</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: "#38bdf8" }}>■</span> Балки</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ color: "#8b5cf6" }}>■</span> Трубы</div>
                  </div>
                </div>
              </div>

            </div>

            {/* CARD 3: СВОЙСТВА ОБЪЕКТА */}
            <div style={{ flex: 1.1, background: "#131028", borderRadius: 8, border: "1px solid #231f47", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #211c47", paddingBottom: 4 }}>
                <span style={{ fontSize: 11.5, fontWeight: 800, color: "#ffffff" }}>Свойства объекта</span>
                <div style={{ display: "flex", gap: 2 }}>
                  {["Общее", "Геометрия", "Атрибуты"].map((t, idx) => (
                    <span key={t} style={{ background: idx === 0 ? "#7c3aed" : "transparent", color: idx === 0 ? "#fff" : "#94a3b8", fontSize: 9, padding: "1px 5px", borderRadius: 4, cursor: "pointer" }}>{t}</span>
                  ))}
                </div>
              </div>

              {/* Object Header */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div>
                  <div style={{ fontWeight: 800, color: "#ffffff", fontSize: 12 }}>{activeObjName}</div>
                  <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
                    <span style={{ background: "#7c3aed22", color: "#a78bfa", padding: "1px 5px", borderRadius: 3, fontSize: 8.5, fontWeight: 700 }}>{activeObjClass}</span>
                    <span style={{ background: "#10b98122", color: "#10b981", padding: "1px 5px", borderRadius: 3, fontSize: 8.5, fontWeight: 700 }}>98%</span>
                  </div>
                </div>
                <div style={{ width: 44, height: 44, borderRadius: 5, background: "#211c47", display: "grid", placeItems: "center", color: "#8b5cf6" }}>
                  <Box size={24} />
                </div>
              </div>

              {/* Property Table */}
              <div style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 9.5, color: "#cbd5e1", marginTop: 2 }}>
                <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #1a1738", paddingBottom: 2 }}>
                  <span style={{ color: "#94a3b8" }}>Тип:</span>
                  <span>Вертикальный элемент</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #1a1738", paddingBottom: 2 }}>
                  <span style={{ color: "#94a3b8" }}>Высота:</span>
                  <span>4.320 м</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #1a1738", paddingBottom: 2 }}>
                  <span style={{ color: "#94a3b8" }}>Сечение / Ø:</span>
                  <span>2.800 м</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid #1a1738", paddingBottom: 2 }}>
                  <span style={{ color: "#94a3b8" }}>Материал:</span>
                  <span>Сталь ГОСТ</span>
                </div>
              </div>

              {/* Buttons */}
              <div style={{ display: "flex", gap: 6, marginTop: "auto" }}>
                <button
                  onClick={() => {
                    if (selectedElement) setInspectingElement(selectedElement);
                  }}
                  style={{ flex: 1, background: "#1c183b", border: "1px solid #2e285a", color: "#c4b5fd", borderRadius: 4, padding: "5px 0", fontSize: 9.5, cursor: "pointer", fontWeight: 700 }}
                >
                  👁 На модели
                </button>
                <button
                  style={{ flex: 1.2, background: "#7c3aed", color: "#ffffff", border: "none", borderRadius: 4, padding: "5px 0", fontSize: 9.5, cursor: "pointer", fontWeight: 700 }}
                >
                  ➕ В чертёж
                </button>
              </div>

            </div>

          </div>

        </div>

      </div>

      {/* 3. MODALS (PANORAMA & GOST) */}
      {panoramaOpen && (
        <div style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.85)", display: "flex", flexDirection: "column" }}>
          <div style={{ height: 42, background: "#121026", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 16px", borderBottom: "1px solid #2e285a" }}>
            <span style={{ color: "#a78bfa", fontWeight: 800 }}>📷 BUBBLE VIEW 360° — {selectedStation.name}</span>
            <button onClick={() => setPanoramaOpen(false)} style={{ background: "transparent", border: "none", color: "#fff", fontSize: 16, cursor: "pointer" }}>✕</button>
          </div>
          <div style={{ flex: 1, position: "relative" }}>
            <BubblePanoramaViewer
              stationName={selectedStation.name}
              stationPosition={selectedStation.position}
              onClose={() => setPanoramaOpen(false)}
            />
          </div>
        </div>
      )}

      {inspectingElement && (
        <GostProfileInspectorModal
          element={inspectingElement}
          onClose={() => setInspectingElement(null)}
                  />
      )}

    </div>
  );
};
