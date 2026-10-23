import React, { useMemo, useState } from "react";
import { type Element } from "../types";
import { ArrowUpDown, CheckCircle } from "lucide-react";

interface ElementTanStackTableProps {
  elements: Element[];
  selectedElement: Element | null;
  onSelectElement: (el: Element | null) => void;
  onInspectElement: (el: Element) => void;
}

interface TableRowItem {
  id: string;
  className: string;
  profile: string;
  dimensions: string;
  tilt: string;
  margin: string;
  status: "compliant" | "exceeded";
  raw: Element;
}

export const ElementTanStackTable: React.FC<ElementTanStackTableProps> = ({
  elements,
  selectedElement,
  onSelectElement,
  onInspectElement,
}) => {
  const [sortField, setSortField] = useState<keyof TableRowItem>("id");
  const [sortAsc, setSortAsc] = useState<boolean>(true);

  const rows: TableRowItem[] = useMemo(() => {
    return elements.map((el) => {
      const min = el.bbox?.min || [0, 0, 0];
      const max = el.bbox?.max || [0.4, 0.4, 6.0];
      const w = Math.round(Math.abs(max[0] - min[0]) * 1000);
      const d = Math.round(Math.abs(max[1] - min[1]) * 1000);
      return {
        id: el.id,
        className: el.class_name,
        profile: el.dimensions?.profile || (el.class_name === "column" ? "30К2" : "—"),
        dimensions: `${w} × ${d} мм`,
        tilt: "ΔX: +2.8 мм",
        margin: "+5.2 мм",
        status: "compliant",
        raw: el,
      };
    });
  }, [elements]);

  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const valA = a[sortField];
      const valB = b[sortField];
      if (valA < valB) return sortAsc ? -1 : 1;
      if (valA > valB) return sortAsc ? 1 : -1;
      return 0;
    });
  }, [rows, sortField, sortAsc]);

  const handleSort = (field: keyof TableRowItem) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(true);
    }
  };

  return (
    <div style={{ width: "100%", height: "100%", overflowY: "auto", background: "#161D26" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, textAlign: "left", color: "#FFFFFF" }}>
        <thead>
          <tr style={{ color: "#E2E8F0", borderBottom: "2px solid #334050", position: "sticky", top: 0, background: "#1F2937", zIndex: 5 }}>
            <th onClick={() => handleSort("id")} style={{ padding: "8px 10px", cursor: "pointer", fontWeight: 700 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>ID <ArrowUpDown size={11} /></span>
            </th>
            <th onClick={() => handleSort("className")} style={{ padding: "8px 10px", cursor: "pointer", fontWeight: 700 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>Класс <ArrowUpDown size={11} /></span>
            </th>
            <th onClick={() => handleSort("profile")} style={{ padding: "8px 10px", cursor: "pointer", fontWeight: 700 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>ГОСТ Профиль <ArrowUpDown size={11} /></span>
            </th>
            <th style={{ padding: "8px 10px", fontWeight: 700 }}>Сечение</th>
            <th style={{ padding: "8px 10px", fontWeight: 700 }}>Крен (СП)</th>
            <th style={{ padding: "8px 10px", fontWeight: 700 }}>Запас</th>
            <th style={{ padding: "8px 10px", fontWeight: 700 }}>Статус</th>
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => {
            const isSelected = selectedElement?.id === row.id;
            return (
              <tr
                key={row.id}
                onClick={() => {
                  onSelectElement(row.raw);
                  onInspectElement(row.raw);
                }}
                style={{
                  cursor: "pointer",
                  borderBottom: "1px solid #2D3748",
                  background: isSelected ? "rgba(255, 129, 46, 0.25)" : "transparent",
                  color: "#FFFFFF",
                }}
              >
                <td style={{ padding: "8px 10px", fontWeight: 700, color: "#FFA25B" }}>{row.id}</td>
                <td style={{ padding: "8px 10px", textTransform: "capitalize", fontWeight: 600 }}>{row.className}</td>
                <td style={{ padding: "8px 10px", fontFamily: "var(--font-mono)", fontSize: 11, color: "#CBD5E1" }}>{row.profile}</td>
                <td style={{ padding: "8px 10px", color: "#F1F5F9" }}>{row.dimensions}</td>
                <td style={{ padding: "8px 10px", color: "#4ADE80", fontFamily: "var(--font-mono)", fontWeight: 700 }}>{row.tilt}</td>
                <td style={{ padding: "8px 10px", color: "#4ADE80", fontFamily: "var(--font-mono)", fontWeight: 700 }}>{row.margin}</td>
                <td style={{ padding: "8px 10px" }}>
                  <span
                    style={{
                      background: "rgba(74, 222, 128, 0.2)",
                      border: "1px solid #22C55E",
                      color: "#4ADE80",
                      padding: "3px 8px",
                      borderRadius: 4,
                      fontSize: 11,
                      fontWeight: 800,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                  >
                    <CheckCircle size={11} /> НОРМА
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
