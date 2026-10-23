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
  rmseData = [],
  heightDistribution = [],
}) => {
  if (!rmseData.length && !heightDistribution.length) {
    return <p role="status">Измерения регистрации и распределение точек пока отсутствуют.</p>;
  }
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
            Невязки регистрации (RMSE)
          </span>
          <span style={{ fontSize: 11, color: "var(--success)", fontWeight: 700 }}>Допуск не задан</span>
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
          <span style={{ fontSize: 11, color: "#38BDF8", fontFamily: "var(--font-mono)", fontWeight: 700 }}>Переданные данные</span>
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
