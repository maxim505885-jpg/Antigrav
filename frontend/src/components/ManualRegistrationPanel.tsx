import React, { useState } from "react";
import type { Cloud } from "../types";
import { api, type PairAlignResponse, type RegistrationPointPair } from "../api";

interface Props {
  clouds: Cloud[];
  onAligned?: (result: PairAlignResponse) => void;
}

export const ManualRegistrationPanel: React.FC<Props> = ({ clouds, onAligned }) => {
  const [sourceId, setSourceId] = useState<string>(clouds[0]?.id || "");
  const [targetId, setTargetId] = useState<string>(clouds[1]?.id || "");
  const [pairs, setPairs] = useState<RegistrationPointPair[]>([
    { source_point: [0, 0, 0], target_point: [0, 0, 0], label: "Репер 1" },
    { source_point: [0, 0, 0], target_point: [0, 0, 0], label: "Репер 2" },
    { source_point: [0, 0, 0], target_point: [0, 0, 0], label: "Репер 3" },
  ]);
  const [applyIcp, setApplyIcp] = useState<boolean>(true);
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<PairAlignResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const addPair = () => {
    setPairs([
      ...pairs,
      {
        source_point: [0, 0, 0],
        target_point: [0, 0, 0],
        label: `Репер ${pairs.length + 1}`,
      },
    ]);
  };

  const removePair = (index: number) => {
    if (pairs.length <= 3) return;
    setPairs(pairs.filter((_, i) => i !== index));
  };

  const updateCoord = (
    pairIndex: number,
    cloudType: "source_point" | "target_point",
    coordIndex: number,
    val: number
  ) => {
    const next = [...pairs];
    const pt = [...next[pairIndex][cloudType]] as [number, number, number];
    pt[coordIndex] = val;
    next[pairIndex] = { ...next[pairIndex], [cloudType]: pt };
    setPairs(next);
  };

  const updateLabel = (pairIndex: number, label: string) => {
    const next = [...pairs];
    next[pairIndex] = { ...next[pairIndex], label };
    setPairs(next);
  };

  const handleAlign = async () => {
    if (!sourceId || !targetId) {
      setError("Выберите исходное и целевое облако");
      return;
    }
    if (sourceId === targetId) {
      setError("Исходное и целевое облака должны отличаться");
      return;
    }
    if (pairs.length < 3) {
      setError("Для 3D совмещения необходимо минимум 3 пары реперов");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await api.pairAlign(sourceId, targetId, pairs, applyIcp);
      setResult(res);
      if (onAligned) {
        onAligned(res);
      }
    } catch (err: any) {
      setError(err?.message || "Ошибка совмещения по реперам");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="manual-registration-panel card" style={{ padding: "16px", marginTop: "16px" }}>
      <h3>Ручная сшивка по реперам (SVD / Kabsch 6-DOF)</h3>
      <p className="text-secondary" style={{ fontSize: "13px", marginBottom: "12px" }}>
        Задайте соответствие 3+ реперных точек (марок) между двумя станциями сканирования для расчёта матрицы взаимного положения SE(3).
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "16px" }}>
        <div>
          <label style={{ display: "block", fontSize: "12px", fontWeight: "bold" }}>Подвижное облако (Scan A):</label>
          <select
            value={sourceId}
            onChange={(e) => setSourceId(e.target.value)}
            style={{ width: "100%", padding: "6px", borderRadius: "4px" }}
          >
            {clouds.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.point_count ? `${c.point_count.toLocaleString()} т.` : "гоresp..."})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label style={{ display: "block", fontSize: "12px", fontWeight: "bold" }}>Базовое облако (Scan B):</label>
          <select
            value={targetId}
            onChange={(e) => setTargetId(e.target.value)}
            style={{ width: "100%", padding: "6px", borderRadius: "4px" }}
          >
            {clouds.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.point_count ? `${c.point_count.toLocaleString()} т.` : "гоresp..."})
              </option>
            ))}
          </select>
        </div>
      </div>

      <div style={{ marginBottom: "12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
          <strong style={{ fontSize: "13px" }}>Соответствующие реперы (X, Y, Z в метрах):</strong>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={addPair}
            style={{ fontSize: "12px", padding: "4px 8px" }}
          >
            + Добавить пару реперов
          </button>
        </div>

        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
            <thead>
              <tr style={{ background: "rgba(255,255,255,0.05)", textAlign: "left" }}>
                <th style={{ padding: "6px" }}>Имя</th>
                <th style={{ padding: "6px" }}>Scan A (X, Y, Z) [м]</th>
                <th style={{ padding: "6px" }}>Scan B (X, Y, Z) [м]</th>
                <th style={{ padding: "6px", width: "40px" }}></th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((p, idx) => (
                <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
                  <td style={{ padding: "6px" }}>
                    <input
                      type="text"
                      value={p.label || ""}
                      onChange={(e) => updateLabel(idx, e.target.value)}
                      style={{ width: "80px", padding: "4px" }}
                    />
                  </td>
                  <td style={{ padding: "6px" }}>
                    <div style={{ display: "flex", gap: "4px" }}>
                      <input
                        type="number"
                        step="0.001"
                        value={p.source_point[0]}
                        onChange={(e) => updateCoord(idx, "source_point", 0, parseFloat(e.target.value) || 0)}
                        style={{ width: "65px", padding: "4px" }}
                        title="X"
                      />
                      <input
                        type="number"
                        step="0.001"
                        value={p.source_point[1]}
                        onChange={(e) => updateCoord(idx, "source_point", 1, parseFloat(e.target.value) || 0)}
                        style={{ width: "65px", padding: "4px" }}
                        title="Y"
                      />
                      <input
                        type="number"
                        step="0.001"
                        value={p.source_point[2]}
                        onChange={(e) => updateCoord(idx, "source_point", 2, parseFloat(e.target.value) || 0)}
                        style={{ width: "65px", padding: "4px" }}
                        title="Z"
                      />
                    </div>
                  </td>
                  <td style={{ padding: "6px" }}>
                    <div style={{ display: "flex", gap: "4px" }}>
                      <input
                        type="number"
                        step="0.001"
                        value={p.target_point[0]}
                        onChange={(e) => updateCoord(idx, "target_point", 0, parseFloat(e.target.value) || 0)}
                        style={{ width: "65px", padding: "4px" }}
                        title="X"
                      />
                      <input
                        type="number"
                        step="0.001"
                        value={p.target_point[1]}
                        onChange={(e) => updateCoord(idx, "target_point", 1, parseFloat(e.target.value) || 0)}
                        style={{ width: "65px", padding: "4px" }}
                        title="Y"
                      />
                      <input
                        type="number"
                        step="0.001"
                        value={p.target_point[2]}
                        onChange={(e) => updateCoord(idx, "target_point", 2, parseFloat(e.target.value) || 0)}
                        style={{ width: "65px", padding: "4px" }}
                        title="Z"
                      />
                    </div>
                  </td>
                  <td style={{ padding: "6px" }}>
                    {pairs.length > 3 && (
                      <button
                        type="button"
                        onClick={() => removePair(idx)}
                        style={{ background: "transparent", border: "none", color: "#f87171", cursor: "pointer" }}
                        title="Удалить пару"
                      >
                        ✕
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ marginBottom: "16px", display: "flex", alignItems: "center", gap: "8px" }}>
        <input
          type="checkbox"
          id="applyIcp"
          checked={applyIcp}
          onChange={(e) => setApplyIcp(e.target.checked)}
        />
        <label htmlFor="applyIcp" style={{ fontSize: "13px", cursor: "pointer" }}>
          Уточнить совмещение локальным Point-to-Plane / Rigid ICP после SVD-выравнивания
        </label>
      </div>

      {error && (
        <div style={{ padding: "8px 12px", background: "rgba(239, 68, 68, 0.15)", color: "#f87171", borderRadius: "4px", marginBottom: "12px", fontSize: "13px" }}>
          {error}
        </div>
      )}

      <button
        type="button"
        className="btn btn-primary"
        onClick={handleAlign}
        disabled={loading}
        style={{ width: "100%", padding: "8px", fontWeight: "bold" }}
      >
        {loading ? "Выполняется расчёт SVD..." : "Рассчитать совмещение (SVD / Kabsch)"}
      </button>

      {result && (
        <div style={{ marginTop: "16px", padding: "12px", background: "rgba(16, 185, 129, 0.1)", border: "1px solid rgba(16, 185, 129, 0.3)", borderRadius: "4px" }}>
          <h4 style={{ color: "#34d399", margin: "0 0 8px 0" }}>Результат сшивки</h4>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "13px", marginBottom: "8px" }}>
            <div>
              <strong>RMSE невязка:</strong> {result.rmse_mm} мм
            </div>
            <div>
              <strong>Макс. ошибка:</strong> {result.max_error_mm} мм
            </div>
            {result.refined_with_icp && (
              <div>
                <strong>ICP RMSE:</strong> {result.icp_rmse_mm} мм
              </div>
            )}
            <div>
              <strong>Смещение (dX, dY, dZ):</strong>{" "}
              {result.translation.map((t) => t.toFixed(3)).join(", ")} м
            </div>
          </div>

          <details style={{ fontSize: "12px", marginTop: "8px" }}>
            <summary style={{ cursor: "pointer", color: "#60a5fa" }}>Детализация невязок по маркам</summary>
            <table style={{ width: "100%", borderCollapse: "collapse", marginTop: "6px" }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
                  <th style={{ padding: "4px" }}>Репер</th>
                  <th style={{ padding: "4px" }}>Невязка (мм)</th>
                </tr>
              </thead>
              <tbody>
                {result.pair_details.map((pd, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                    <td style={{ padding: "4px" }}>{pd.label}</td>
                    <td style={{ padding: "4px", color: pd.residual_mm > 10 ? "#fbbf24" : "#34d399" }}>
                      {pd.residual_mm} мм
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>

          <details style={{ fontSize: "12px", marginTop: "8px" }}>
            <summary style={{ cursor: "pointer", color: "#60a5fa" }}>Матрица трансформации 4×4</summary>
            <pre style={{ background: "rgba(0,0,0,0.3)", padding: "8px", borderRadius: "4px", overflowX: "auto" }}>
              {JSON.stringify(result.matrix_4x4, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
};
