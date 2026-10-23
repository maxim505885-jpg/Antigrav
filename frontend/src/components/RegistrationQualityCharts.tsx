import React from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
} from "recharts";

interface InspectionChartProps {
  rmseData?: Array<{ station: string; error_mm: number; limit_mm: number }>;
  heightDistribution?: Array<{ z_m: string; points_k: number }>;
}

export const RegistrationQualityCharts: React.FC<InspectionChartProps> = ({
  rmseData = [
    { station: "ST_01", error_mm: 1.2, limit_mm: 5.0 },
    { station: "ST_02", error_mm: 2.1, limit_mm: 5.0 },
    { station: "ST_03", error_mm: 1.8, limit_mm: 5.0 },
    { station: "ST_04", error_mm: 3.4, limit_mm: 5.0 },
    { station: "ST_05", error_mm: 2.6, limit_mm: 5.0 },
    { station: "ST_06", error_mm: 1.9, limit_mm: 5.0 },
    { station: "ST_07", error_mm: 2.3, limit_mm: 5.0 },
  ],
  heightDistribution = [
    { z_m: "0-2м", points_k: 840 },
    { z_m: "2-4м", points_k: 620 },
    { z_m: "4-6м", points_k: 410 },
    { z_m: "6-8м", points_k: 780 },
    { z_m: "8-10м", points_k: 320 },
    { z_m: "10-12м", points_k: 560 },
  ],
}) => {
  return (
    <div style={{ display: "flex", gap: 12, width: "100%", height: "100%" }}>
      {/* 1. RMSE Station Bar Chart */}
      <div
        style={{
          flex: 1,
          background: "var(--bg-card)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-sm)",
          padding: "10px 12px",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: "#FFFFFF", textTransform: "uppercase" }}>
            Погрешность станций (RMSE)
          </span>
          <span style={{ fontSize: 11, color: "var(--success)", fontWeight: 700 }}>Допуск 5.0 мм</span>
        </div>

        <div style={{ flex: 1, minHeight: 90 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rmseData} margin={{ top: 4, right: 4, left: -25, bottom: 0 }}>
              <XAxis dataKey="station" stroke="#CBD5E1" fontSize={11} tickLine={false} />
              <YAxis stroke="#CBD5E1" fontSize={11} tickLine={false} domain={[0, 6]} />
              <Tooltip
                contentStyle={{ background: "#1F2937", border: "1px solid #4B5563", borderRadius: 4, fontSize: 12, color: "#fff" }}
                itemStyle={{ color: "#FFA25B", fontWeight: 700 }}
                formatter={(val: any) => [`${val} мм`, "Невязка"]}
              />
              <Bar dataKey="error_mm" fill="#FF812E" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 2. Height Density Area Chart */}
      <div
        style={{
          flex: 1,
          background: "var(--bg-card)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-sm)",
          padding: "10px 12px",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: "#FFFFFF", textTransform: "uppercase" }}>
            Плотность точек (Z-высота)
          </span>
          <span style={{ fontSize: 11, color: "#38BDF8", fontFamily: "var(--font-mono)", fontWeight: 700 }}>Σ 874.6M</span>
        </div>

        <div style={{ flex: 1, minHeight: 90 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={heightDistribution} margin={{ top: 4, right: 4, left: -25, bottom: 0 }}>
              <defs>
                <linearGradient id="densityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#38BDF8" stopOpacity={0.6} />
                  <stop offset="95%" stopColor="#38BDF8" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="z_m" stroke="#CBD5E1" fontSize={11} tickLine={false} />
              <YAxis stroke="#CBD5E1" fontSize={11} tickLine={false} />
              <Tooltip
                contentStyle={{ background: "#1F2937", border: "1px solid #4B5563", borderRadius: 4, fontSize: 12, color: "#fff" }}
                itemStyle={{ color: "#38BDF8", fontWeight: 700 }}
                formatter={(val: any) => [`${val} тыс. точек`, "Плотность"]}
              />
              <Area type="monotone" dataKey="points_k" stroke="#38BDF8" strokeWidth={2} fillOpacity={1} fill="url(#densityGrad)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};
