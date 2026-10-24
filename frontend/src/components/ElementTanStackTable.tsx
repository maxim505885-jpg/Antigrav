import React, { useMemo, useState } from "react";
import { type Element } from "../types";
import { ArrowUpDown, CircleHelp } from "lucide-react";
import { elementTableEvidenceBadges } from "../elementEvidence";
import { elementPlanDimensionSummary } from "../elementTablePresentation";
import { elementClassLabels, filterElementCandidates } from "../elementCandidateFilter";

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
  status: "unverified";
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
  const [search, setSearch] = useState("");
  const [classFilter, setClassFilter] = useState("all");

  const rows: TableRowItem[] = useMemo(() => {
    return elements.map((el) => {
      return {
        id: el.id,
        className: el.class_name,
        profile: el.dimensions?.profile || "не определён",
        dimensions: elementPlanDimensionSummary(el),
        tilt: "не измерен",
        margin: "не определён",
        status: "unverified",
        raw: el,
      };
    });
  }, [elements]);

  const classOptions = useMemo(() => [...new Set(elements.map((element) => element.class_name))].sort(), [elements]);
  const filteredElements = useMemo(
    () => filterElementCandidates(elements, search, classFilter),
    [elements, search, classFilter],
  );
  const filteredIds = useMemo(() => new Set(filteredElements.map((element) => element.id)), [filteredElements]);

  const sortedRows = useMemo(() => {
    return rows.filter((row) => filteredIds.has(row.id)).sort((a, b) => {
      const valA = a[sortField];
      const valB = b[sortField];
      if (valA < valB) return sortAsc ? -1 : 1;
      if (valA > valB) return sortAsc ? 1 : -1;
      return 0;
    });
  }, [rows, filteredIds, sortField, sortAsc]);

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
      <div className="candidate-table-filters" aria-label="Поиск и фильтр кандидатов">
        <label>
          <span>Поиск по ID или роли</span>
          <input
            type="search"
            aria-label="Поиск кандидатов по ID или роли"
            placeholder="Например, truss или ферма"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label>
          <span>Класс</span>
          <select aria-label="Фильтр кандидатов по классу" value={classFilter} onChange={(event) => setClassFilter(event.target.value)}>
            <option value="all">Все классы</option>
            {classOptions.map((className) => <option key={className} value={className}>{elementClassLabels[className] || className}</option>)}
          </select>
        </label>
        <output aria-live="polite">Показано {sortedRows.length.toLocaleString("ru-RU")} из {elements.length.toLocaleString("ru-RU")}</output>
      </div>
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
            <th style={{ padding: "8px 10px", fontWeight: 700 }}>Габариты</th>
            <th style={{ padding: "8px 10px", fontWeight: 700 }}>Крен (СП)</th>
            <th style={{ padding: "8px 10px", fontWeight: 700 }}>Запас</th>
            <th style={{ padding: "8px 10px", fontWeight: 700 }}>Статус</th>
          </tr>
        </thead>
        <tbody>
          {sortedRows.length === 0 && <tr><td colSpan={7} className="candidate-table-empty">По заданным условиям кандидатов нет.</td></tr>}
          {sortedRows.map((row) => {
            const isSelected = selectedElement?.id === row.id;
            return (
              <tr
                key={row.id}
                onClick={() => onSelectElement(row.raw)}
                style={{
                  cursor: "pointer",
                  borderBottom: "1px solid #2D3748",
                  background: isSelected ? "rgba(255, 129, 46, 0.25)" : "transparent",
                  color: "#FFFFFF",
                }}
              >
                <td style={{ padding: "8px 10px", fontWeight: 700, color: "#FFA25B", whiteSpace: "nowrap" }}>
                  {row.id}
                  <button type="button" aria-label={`Открыть инспектор элемента ${row.id}`}
                    onClick={(event) => { event.stopPropagation(); onSelectElement(row.raw); onInspectElement(row.raw); }}
                    style={{ display: "block", marginTop: 4, padding: "2px 6px", border: "1px solid #475569", borderRadius: 4, background: "#1F2937", color: "#CBD5E1", fontSize: 10, cursor: "pointer" }}>
                    Инспектор
                  </button>
                </td>
                <td style={{ padding: "8px 10px", fontWeight: 600 }}>
                  {row.raw.dimensions?.role_label || (row.className === "column" ? "Колонна" : row.className === "beam" ? "Балка" : row.className)}
                  {elementTableEvidenceBadges(row.raw).map((badge) => (
                    <div key={badge.text} title={badge.title} style={{fontSize: 11, color: "#FCD34D", marginTop: 4}}>
                      {badge.text}<details><summary>Основание</summary>{badge.title}</details>
                    </div>
                  ))}
                </td>
                <td style={{ padding: "8px 10px", fontFamily: "var(--font-mono)", fontSize: 11, color: "#CBD5E1" }}>{row.profile}</td>
                <td style={{ padding: "8px 10px", color: "#F1F5F9" }}>{row.dimensions}</td>
                <td style={{ padding: "8px 10px", color: "#4ADE80", fontFamily: "var(--font-mono)", fontWeight: 700 }}>{row.tilt}</td>
                <td style={{ padding: "8px 10px", color: "#4ADE80", fontFamily: "var(--font-mono)", fontWeight: 700 }}>{row.margin}</td>
                <td style={{ padding: "8px 10px" }}>
                  <span
                    style={{
                      background: "rgba(252, 211, 77, 0.1)",
                      border: "1px solid #FCD34D",
                      color: "#FCD34D",
                      padding: "3px 8px",
                      borderRadius: 4,
                      fontSize: 11,
                      fontWeight: 800,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                  >
                    <CircleHelp size={11} /> ТРЕБУЕТ ПРОВЕРКИ
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
