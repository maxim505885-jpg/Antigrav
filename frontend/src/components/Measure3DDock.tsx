import React from "react";

export interface MeasureResult {
  dist3d: number;
  dx: number;
  dy: number;
  dz: number;
  dxy: number;
  angleDeg: number;
}

interface Measure3DDockProps {
  active: boolean;
  onToggle: () => void;
  result: MeasureResult | null;
  pointCount: number;
  onClear: () => void;
}

export const Measure3DDock: React.FC<Measure3DDockProps> = ({
  active,
  onToggle,
  result,
  pointCount,
  onClear,
}) => {
  if (!active && !result) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: "60px",
        left: "16px",
        width: "300px",
        background: "rgba(15, 23, 42, 0.94)",
        backdropFilter: "blur(14px)",
        border: "1px solid #38BDF8",
        borderRadius: "8px",
        padding: "14px 16px",
        boxShadow: "0 10px 30px rgba(0, 0, 0, 0.4)",
        color: "#FFFFFF",
        zIndex: 50,
        fontSize: "12px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: "13px", color: "#38BDF8" }}>
          <span>📐</span>
          <span>Лазерные 3D замеры (ReCap)</span>
        </div>
        <button
          onClick={onToggle}
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

      {pointCount === 0 && (
        <div style={{ color: "#CBD5E1", fontSize: "11px", lineHeight: "1.4" }}>
          Кликните по <b>первой точке</b> в облаке точек или на строительной конструкции...
        </div>
      )}

      {pointCount === 1 && (
        <div style={{ color: "#FBBF24", fontSize: "11px", lineHeight: "1.4" }}>
          Точка 1 зафиксирована. Кликните по <b>второй точке</b> для измерения...
        </div>
      )}

      {result && (
        <div style={{ marginTop: "6px" }}>
          <div style={{ background: "#0F172A", padding: "8px 10px", borderRadius: "6px", border: "1px solid #1E293B", marginBottom: "8px" }}>
            <div style={{ fontSize: "11px", color: "#94A3B8", marginBottom: "2px" }}>Прямое расстояние (3D):</div>
            <div style={{ fontSize: "18px", fontWeight: 700, color: "#38BDF8", fontFamily: "var(--font-mono, monospace)" }}>
              {(result.dist3d * 1000).toFixed(1)} мм
              <span style={{ fontSize: "12px", color: "#94A3B8", marginLeft: "6px", fontWeight: 400 }}>
                ({result.dist3d.toFixed(3)} м)
              </span>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", fontSize: "11px", color: "#CBD5E1", marginBottom: "10px" }}>
            <div>
              <span style={{ color: "#94A3B8" }}>Горизонт (ΔXY): </span>
              <strong style={{ color: "#F8FAFC" }}>{(result.dxy * 1000).toFixed(1)} мм</strong>
            </div>
            <div>
              <span style={{ color: "#94A3B8" }}>Высота (ΔZ): </span>
              <strong style={{ color: result.dz >= 0 ? "#4ADE80" : "#F87171" }}>
                {result.dz >= 0 ? "+" : ""}{(result.dz * 1000).toFixed(1)} мм
              </strong>
            </div>
            <div>
              <span style={{ color: "#94A3B8" }}>По оси X (ΔX): </span>
              <strong style={{ color: "#F8FAFC" }}>{(result.dx * 1000).toFixed(1)} мм</strong>
            </div>
            <div>
              <span style={{ color: "#94A3B8" }}>Уклон / угол: </span>
              <strong style={{ color: "#FBBF24" }}>{result.angleDeg.toFixed(1)}°</strong>
            </div>
          </div>

          <div style={{ display: "flex", gap: "8px" }}>
            <button
              type="button"
              onClick={onClear}
              style={{
                flex: 1,
                background: "#1E293B",
                border: "1px solid #475569",
                color: "#F8FAFC",
                padding: "4px 8px",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "11px",
                fontWeight: 600,
              }}
            >
              Сбросить замер
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
