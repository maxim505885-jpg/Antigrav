import React from "react";

export interface LimitBoxRange {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  minZ: number;
  maxZ: number;
  invert: boolean;
}

interface LimitBoxDockProps {
  visible: boolean;
  onClose: () => void;
  box: LimitBoxRange;
  onChange: (newBox: LimitBoxRange) => void;
  onPreset: (preset: "all" | "floor" | "crane" | "roof") => void;
}

export const LimitBoxDock: React.FC<LimitBoxDockProps> = ({
  visible,
  onClose,
  box,
  onChange,
  onPreset,
}) => {
  if (!visible) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: "60px",
        right: "16px",
        width: "320px",
        background: "rgba(16, 21, 27, 0.95)",
        backdropFilter: "blur(14px)",
        border: "1px solid #FF812E",
        borderRadius: "8px",
        padding: "14px 16px",
        boxShadow: "0 12px 32px rgba(0, 0, 0, 0.5)",
        color: "#FFFFFF",
        zIndex: 50,
        fontSize: "12px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: "13px", color: "#FF812E" }}>
          <span>📦</span>
          <span>Limit Box (Клиппинг-куб ReCap)</span>
        </div>
        <button
          onClick={onClose}
          style={{
            background: "transparent",
            border: "none",
            color: "#94A3B8",
            cursor: "pointer",
            fontSize: "14px",
            fontWeight: 700,
          }}
        >
          ✕
        </button>
      </div>

      {/* Quick Presets */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginBottom: "12px" }}>
        <button
          type="button"
          onClick={() => onPreset("all")}
          style={{
            background: "#1E293B",
            border: "1px solid #334155",
            color: "#F8FAFC",
            padding: "4px 8px",
            borderRadius: "4px",
            cursor: "pointer",
            fontSize: "11px",
            fontWeight: 600,
          }}
        >
          Весь цех (Сброс)
        </button>
        <button
          type="button"
          onClick={() => onPreset("floor")}
          style={{
            background: "#1E293B",
            border: "1px solid #334155",
            color: "#38BDF8",
            padding: "4px 8px",
            borderRadius: "4px",
            cursor: "pointer",
            fontSize: "11px",
            fontWeight: 600,
          }}
        >
          Пол (0 — 2 м)
        </button>
        <button
          type="button"
          onClick={() => onPreset("crane")}
          style={{
            background: "#1E293B",
            border: "1px solid #334155",
            color: "#FBBF24",
            padding: "4px 8px",
            borderRadius: "4px",
            cursor: "pointer",
            fontSize: "11px",
            fontWeight: 600,
          }}
        >
          Краны (+5 — 9 м)
        </button>
        <button
          type="button"
          onClick={() => onPreset("roof")}
          style={{
            background: "#1E293B",
            border: "1px solid #334155",
            color: "#4ADE80",
            padding: "4px 8px",
            borderRadius: "4px",
            cursor: "pointer",
            fontSize: "11px",
            fontWeight: 600,
          }}
        >
          Кровля (+9 — 16 м)
        </button>
      </div>

      {/* Sliders for Z (Elevation) */}
      <div style={{ marginBottom: "10px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", color: "#CBD5E1", fontSize: "11px", marginBottom: "2px" }}>
          <span style={{ fontWeight: 600, color: "#38BDF8" }}>Высота Z (отметка):</span>
          <span>{box.minZ.toFixed(1)} м ... {box.maxZ.toFixed(1)} м</span>
        </div>
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          <input
            type="range"
            min="-10"
            max="30"
            step="0.5"
            value={box.minZ}
            onChange={(e) => onChange({ ...box, minZ: parseFloat(e.target.value) })}
            style={{ width: "50%", accentColor: "#FF812E" }}
          />
          <input
            type="range"
            min="-10"
            max="30"
            step="0.5"
            value={box.maxZ}
            onChange={(e) => onChange({ ...box, maxZ: parseFloat(e.target.value) })}
            style={{ width: "50%", accentColor: "#FF812E" }}
          />
        </div>
      </div>

      {/* Sliders for X */}
      <div style={{ marginBottom: "10px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", color: "#CBD5E1", fontSize: "11px", marginBottom: "2px" }}>
          <span style={{ fontWeight: 600, color: "#F87171" }}>Продольная ось X:</span>
          <span>{box.minX.toFixed(1)} м ... {box.maxX.toFixed(1)} м</span>
        </div>
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          <input
            type="range"
            min="-100"
            max="100"
            step="1"
            value={box.minX}
            onChange={(e) => onChange({ ...box, minX: parseFloat(e.target.value) })}
            style={{ width: "50%", accentColor: "#F87171" }}
          />
          <input
            type="range"
            min="-100"
            max="100"
            step="1"
            value={box.maxX}
            onChange={(e) => onChange({ ...box, maxX: parseFloat(e.target.value) })}
            style={{ width: "50%", accentColor: "#F87171" }}
          />
        </div>
      </div>

      {/* Sliders for Y */}
      <div style={{ marginBottom: "12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", color: "#CBD5E1", fontSize: "11px", marginBottom: "2px" }}>
          <span style={{ fontWeight: 600, color: "#4ADE80" }}>Поперечная ось Y:</span>
          <span>{box.minY.toFixed(1)} м ... {box.maxY.toFixed(1)} м</span>
        </div>
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          <input
            type="range"
            min="-100"
            max="100"
            step="1"
            value={box.minY}
            onChange={(e) => onChange({ ...box, minY: parseFloat(e.target.value) })}
            style={{ width: "50%", accentColor: "#4ADE80" }}
          />
          <input
            type="range"
            min="-100"
            max="100"
            step="1"
            value={box.maxY}
            onChange={(e) => onChange({ ...box, maxY: parseFloat(e.target.value) })}
            style={{ width: "50%", accentColor: "#4ADE80" }}
          />
        </div>
      </div>

      {/* Invert check */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: "6px", borderTop: "1px solid #1E293B" }}>
        <label style={{ display: "flex", alignItems: "center", gap: "6px", cursor: "pointer", color: "#CBD5E1" }}>
          <input
            type="checkbox"
            checked={box.invert}
            onChange={(e) => onChange({ ...box, invert: e.target.checked })}
            style={{ accentColor: "#FF812E" }}
          />
          <span>Инвертировать отсечение</span>
        </label>
        <span style={{ color: "#64748B", fontSize: "10px" }}>GPU WebGL Clip</span>
      </div>
    </div>
  );
};
