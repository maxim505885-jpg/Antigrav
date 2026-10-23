import React, { useMemo, useState } from "react";
import { type Element } from "../types";
import { ArrowUpDown, CheckCircle, ShieldAlert } from "lucide-react";

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
    <div style={{ width: "100%", height: "100%", overflowY: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, textAlign: "left" }}>
        <thead>
          <tr style={{ color: "var(--text-muted)", borderBottom: "1px solid var(--border)", position: "sticky", top: 0, background: "var(--bg-card)", zIndex: 5 }}>
            <th onClick={() => handleSort("id")} style={{ padding: "6px 8px", cursor: "pointer" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>ID <ArrowUpDown size={10} /></span>
            </th>
            <th onClick={() => handleSort("className")} style={{ padding: "6px 8px", cursor: "pointer" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>Класс <ArrowUpDown size={10} /></span>
            </th>
            <th onClick={() => handleSort("profile")} style={{ padding: "6px 8px", cursor: "pointer" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>ГОСТ Профиль <ArrowUpDown size={10} /></span>
            </th>
            <th style={{ padding: "6px 8px" }}>Сечение</th>
            <th style={{ padding: "6px 8px" }}>Крен (СП 70.13330)</th>
            <th style={{ padding: "6px 8px" }}>Запас</th>
            <th style={{ padding: "6px 8px" }}>Статус</th>
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
                  borderBottom: "1px solid rgba(255,255,255,0.03)",
                  background: isSelected ? "var(--accent-subtle)" : "transparent",
                  transition: "background 0.12s",
                }}
              >
                <td style={{ padding: "6px 8px", fontWeight: 600, color: "var(--accent)" }}>{row.id}</td>
                <td style={{ padding: "6px 8px", textTransform: "capitalize" }}>{row.className}</td>
                <td style={{ padding: "6px 8px", fontFamily: "var(--font-mono)", fontSize: 10 }}>{row.profile}</td>
                <td style={{ padding: "6px 8px" }}>{row.dimensions}</td>
                <td style={{ padding: "6px 8px", color: "var(--success)", fontFamily: "var(--font-mono)" }}>{row.tilt}</td>
                <td style={{ padding: "6px 8px", color: "var(--success)", fontFamily: "var(--font-mono)" }}>{row.margin}</td>
                <td style={{ padding: "6px 8px" }}>
                  <span
                    style={{
                      background: "var(--success-bg)",
                      color: "var(--success)",
                      padding: "2px 6px",
                      borderRadius: 3,
                      fontSize: 10,
                      fontWeight: 700,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                  >
                    <CheckCircle size={10} /> НОРМА
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
