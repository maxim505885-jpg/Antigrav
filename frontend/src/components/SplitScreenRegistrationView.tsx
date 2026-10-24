import React, { useState } from "react";
import Viewer3D from "./Viewer3D";
import { type Cloud } from "../types";
import { api } from "../api";

interface SplitScreenRegistrationViewProps {
  sourceCloud: Cloud | null;
  targetCloud: Cloud | null;
}

export const SplitScreenRegistrationView: React.FC<SplitScreenRegistrationViewProps> = ({
  sourceCloud,
  targetCloud,
}) => {
  const [detectedTargets, setDetectedTargets] = useState(0);
  const [targetDiameterMm, setTargetDiameterMm] = useState("");
  const [isDetecting, setIsDetecting] = useState(false);
  const [isMatching, setIsMatching] = useState(false);
  const [alignStatus, setAlignStatus] = useState<string | null>(null);

  const handleAutoMatchICP = async () => {
    if (!sourceCloud || !targetCloud) return;
    setIsMatching(true);
    setAlignStatus("Выполняется глобальное и локальное Point-to-Plane ICP уравнивание...");
    try {
      const res = await api.matchCloudsIcp(sourceCloud.id, targetCloud.id);
      const rmseStr = res.rmse_mm != null ? `${res.rmse_mm.toFixed(2)} мм` : "расчёт выполнен";
      setAlignStatus(`Уравнивание ICP успешно завершено: RMSE = ${rmseStr}, итераций: ${res.iterations}, сошлось: ${res.converged ? "Да" : "Нет"}. Матрица жесткой трансформации 4x4 вычислена.`);
    } catch (e: any) {
      setAlignStatus(`Ошибка автосшивки: ${e.message || String(e)}`);
    } finally {
      setIsMatching(false);
    }
  };
  const emptySections: [Float32Array, Float32Array, Float32Array] = [
    new Float32Array(0),
    new Float32Array(0),
    new Float32Array(0),
  ];

  const handleDetectTargets = async (cloudId: string) => {
    const diameterMm = Number(targetDiameterMm.replace(",", "."));
    if (!Number.isFinite(diameterMm) || diameterMm <= 0) {
      setAlignStatus("Введите фактический диаметр установленной сферы в миллиметрах.");
      return;
    }
    setIsDetecting(true);
    try {
      const resp = await fetch("/api/v1/registration/detect-targets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cloud_id: cloudId, expected_radius_m: diameterMm / 2000, sample_points: 50000 }),
      });
      const data = await resp.json();
      if (data.status === "ok" && data.targets) {
        setDetectedTargets(data.targets_found || data.targets.length);
        setAlignStatus(`Найдено кандидатов-сфер: ${data.targets_found || data.targets.length}. Это не подтверждает общие цели или регистрацию станций.`);
      } else {
        throw new Error(data.detail || data.message || `HTTP ${resp.status}`);
      }
    } catch (e: any) {
      setAlignStatus(`Поиск целей не выполнен: ${e.message || String(e)}`);
    } finally {
      setIsDetecting(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", width: "100%", height: "100%", background: "#0B1015" }}>
      {/* Top Split-Screen Control Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 16px",
          background: "#171D24",
          borderBottom: "1px solid #303943",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ color: "#FF812E", fontWeight: 700, fontSize: 13, textTransform: "uppercase" }}>
            Сравнение исходных облаков
          </span>
          <span style={{ color: "#97A3AE", fontSize: 12 }}>
            Положение и невязка не считаются проверенными без общих контрольных точек.
          </span>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 5, color: "#CBD5E1", fontSize: 11 }}>
            Ø сферы, мм
            <input aria-label="Диаметр сферы в миллиметрах" type="number" min="0.1" step="0.1" value={targetDiameterMm} onChange={(event) => setTargetDiameterMm(event.target.value)} style={{ width: 82, background: "#0E1318", color: "#FFFFFF", border: "1px solid #475569", borderRadius: 4, padding: "5px 7px" }} />
          </label>
          <button
            onClick={() => sourceCloud && handleDetectTargets(sourceCloud.id)}
            disabled={isDetecting || !sourceCloud || !targetDiameterMm}
            style={{
              background: "#1E252D",
              color: "#F2F4F6",
              border: "1px solid #303943",
              borderRadius: 6,
              padding: "6px 12px",
              cursor: "pointer",
              fontSize: 12,
            }}
          >
            {isDetecting ? "Поиск целей…" : "Найти сферы в первом облаке"}
          </button>

          <button
            onClick={handleAutoMatchICP}
            disabled={isMatching || !sourceCloud || !targetCloud}
            title="Автоматическое Point-to-Plane ICP уравнивание двух облаков точек без использования марок"
            style={{
              background: "#FF812E",
              color: "#10151B",
              fontWeight: 700,
              border: "none",
              borderRadius: 6,
              padding: "6px 14px",
              cursor: isMatching || !sourceCloud || !targetCloud ? "not-allowed" : "pointer",
              opacity: isMatching || !sourceCloud || !targetCloud ? 0.6 : 1,
              fontSize: 12,
            }}
          >
            {isMatching ? "Расчёт автосшивки (ICP)..." : "⚡ Автосшивка (ICP)"}
          </button>
        </div>
      </div>

      {alignStatus && (
        <div
          style={{
            background: "#1E252D",
            padding: "6px 16px",
            borderBottom: "1px solid #303943",
            fontSize: 12,
            color: alignStatus.startsWith("Ошибка") || alignStatus.includes("не выполнен") ? "#F2B84B" : "#CBD5E1",
            display: "flex",
            justifyContent: "space-between",
          }}
        >
          <span>{alignStatus}</span>
          {detectedTargets > 0 && <span>Кандидатов-сфер: {detectedTargets} · регистрации не выполнена</span>}
        </div>
      )}

      {/* Side-by-side Viewports */}
      <div style={{ display: "flex", flex: 1, position: "relative", overflow: "hidden" }}>
        {/* Left Viewport: Station A */}
        <div style={{ flex: 1, borderRight: "1px solid #303943", position: "relative" }}>
          <div
            style={{
              position: "absolute",
              top: 10,
              left: 10,
              zIndex: 10,
              background: "rgba(23, 29, 36, 0.85)",
              padding: "4px 10px",
              borderRadius: 4,
              border: "1px solid #303943",
              color: "#FF812E",
              fontWeight: 600,
              fontSize: 12,
            }}
          >
            Исходное облако: {sourceCloud?.name || "не выбрано"}
          </div>
          <Viewer3D
            cloud={sourceCloud}
            elements={[]}
            groupPositions={new Float32Array(0)}
            selectedElement={null}
            selectedElementPositions={new Float32Array(0)}
            selectedElementSections={emptySections}
            pointSize={2.0}
            colorMode="rgb"
            showPlane={false}
            section={null}
          />
        </div>

        {/* Right Viewport: Station B */}
        <div style={{ flex: 1, position: "relative" }}>
          <div
            style={{
              position: "absolute",
              top: 10,
              left: 10,
              zIndex: 10,
              background: "rgba(23, 29, 36, 0.85)",
              padding: "4px 10px",
              borderRadius: 4,
              border: "1px solid #303943",
              color: "#49C980",
              fontWeight: 600,
              fontSize: 12,
            }}
          >
            Сравниваемое облако: {targetCloud?.name || "не выбрано"}
          </div>
          <Viewer3D
            cloud={targetCloud || sourceCloud}
            elements={[]}
            groupPositions={new Float32Array(0)}
            selectedElement={null}
            selectedElementPositions={new Float32Array(0)}
            selectedElementSections={emptySections}
            pointSize={2.0}
            colorMode="rgb"
            showPlane={false}
            section={null}
          />
        </div>
      </div>
    </div>
  );
};
