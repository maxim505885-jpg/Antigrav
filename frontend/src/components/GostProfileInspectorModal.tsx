import React from "react";
import { bboxExtentsMm } from "../profileInspection";
import { type Element } from "../types";

interface GostProfileInspectorModalProps {
  element: Element | null;
  onClose: () => void;
}

export const GostProfileInspectorModal: React.FC<GostProfileInspectorModalProps> = ({ element, onClose }) => {
  if (!element) return null;
  const extents = bboxExtentsMm(element.bbox);

  return (
    <div role="presentation" style={{ position: "fixed", inset: 0, zIndex: 9999, background: "rgba(11, 16, 21, 0.75)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="profile-inspection-title"
        style={{ width: 580, maxWidth: "calc(100vw - 32px)", background: "#171D24", border: "1px solid #303943", borderRadius: 8, boxShadow: "0 20px 40px rgba(0,0,0,0.6)", overflow: "hidden", color: "#F2F4F6" }}
      >
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, padding: "12px 18px", borderBottom: "1px solid #303943", background: "#1E252D" }}>
          <strong id="profile-inspection-title" style={{ fontSize: 14, color: "#FF812E" }}>
            Проверка сечения кандидата · {element.class_name.toUpperCase()} · {element.id.slice(0, 8)}
          </strong>
          <button type="button" onClick={onClose} aria-label="Закрыть" style={{ background: "transparent", border: "none", color: "#97A3AE", fontSize: 16, cursor: "pointer" }}>✕</button>
        </header>

        <div style={{ padding: "18px 20px", display: "grid", gap: 14 }}>
          <div style={{ background: "#10151B", border: "1px solid #303943", borderRadius: 6, padding: "14px 16px" }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#97A3AE", marginBottom: 9, textTransform: "uppercase" }}>Габарит bbox кандидата по осям X × Y × Z</div>
            <strong>{extents ? `${extents.join(" × ")} мм` : "Габарит недоступен или некорректен"}</strong>
            <p style={{ color: "#97A3AE", fontSize: 12, lineHeight: 1.5, margin: "8px 0 0" }}>
              Габарит ограничивающего бокса не подтверждает форму, толщину стенки или полок и сам по себе не является замером сечения.
            </p>
          </div>

          <div style={{ background: "#1E252D", border: "1px solid #475569", borderRadius: 6, padding: "14px 16px", lineHeight: 1.6 }}>
            <strong style={{ color: "#F2B84B" }}>Профиль не подтверждён.</strong>
            <div style={{ color: "#CBD5E1", fontSize: 12, marginTop: 5 }}>
              Для сопоставления с сортаментом нужны измеренные стороны или контур на срезе, подтверждённые точками облака.
            </div>
          </div>

          <div style={{ color: "#CBD5E1", fontSize: 12 }}>
            Проверка соответствия СП не выполнена. Инженерный допуск для этого цеха не задан.
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button type="button" onClick={onClose} style={{ background: "#FF812E", color: "#10151B", fontWeight: 700, border: "none", borderRadius: 4, padding: "8px 16px", cursor: "pointer", fontSize: 12 }}>
              Закрыть
            </button>
          </div>
        </div>
      </section>
    </div>
  );
};
