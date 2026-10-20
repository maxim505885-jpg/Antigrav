import { useMemo, useState } from "react";
import { CLASSES, type Element } from "../types";

interface Props {
  elements: Element[];
  busy: boolean;
  onFeedback: (id: string, payload: Record<string, unknown>) => Promise<void>;
  onSelect: (element: Element | null) => void;
  selected: Element | null;
}

function dimensionSummary(element: Element): string {
  const dims = element.dimensions || {};
  if (dims.length_m) {
    return `${dims.length_m} × ${dims.thickness_m} × ${dims.height_m} m`;
  }
  if (dims.area_m2) return `${dims.area_m2} m² footprint`;
  return "—";
}

export default function ElementTable({ elements, busy, onFeedback, onSelect, selected }: Props) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    elements.forEach((element) => {
      map[element.class_name] = (map[element.class_name] || 0) + 1;
    });
    return map;
  }, [elements]);

  if (!elements.length) {
    return (
      <div className="empty-note">
        No recognised elements yet. Run recognition to extract a geometric baseline
        (walls, columns, slab footprints). Beams, trusses, stairs and MEP require the ML stage.
      </div>
    );
  }

  return (
    <div className="element-list">
      <div className="counts">
        {Object.entries(counts).map(([name, value]) => (
          <span key={name} className="count-chip">
            {name} <b>{value}</b>
          </span>
        ))}
      </div>
      <table className="element-table">
        <thead>
          <tr>
            <th>class</th>
            <th>confidence</th>
            <th>dimensions</th>
            <th>flags</th>
            <th>review</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {elements.map((element) => {
            const draft = drafts[element.id] ?? element.class_name;
            return (
              <tr
                key={element.id}
                className={selected?.id === element.id ? "selected" : ""}
                onClick={() => onSelect(element)}
              >
                <td>
                  <select
                    value={draft}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => setDrafts({ ...drafts, [element.id]: event.target.value })}
                  >
                    {CLASSES.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <div className="conf">
                    <div className="conf-bar" style={{ width: `${Math.round(element.confidence * 100)}%` }} />
                    <span>{(element.confidence * 100).toFixed(0)}%</span>
                  </div>
                </td>
                <td>{dimensionSummary(element)}</td>
                <td className="flags">
                  {element.measured && <span className="badge measured">measured</span>}
                  {element.inferred && <span className="badge inferred">inferred</span>}
                </td>
                <td>
                  <span className={`status ${element.review_status}`}>{element.review_status}</span>
                </td>
                <td className="actions" onClick={(event) => event.stopPropagation()}>
                  {draft !== element.class_name && (
                    <button
                      disabled={busy}
                      onClick={() =>
                        onFeedback(element.id, {
                          action: "reclassify",
                          class_name: draft,
                          note: "class corrected in engineer editor",
                        })
                      }
                    >
                      Apply class
                    </button>
                  )}
                  {element.review_status !== "confirmed" && (
                    <button
                      disabled={busy}
                      className="primary"
                      onClick={() => onFeedback(element.id, { action: "confirm", note: "confirmed in editor" })}
                    >
                      Confirm
                    </button>
                  )}
                  {element.review_status !== "rejected" && (
                    <button
                      disabled={busy}
                      className="danger"
                      onClick={() => onFeedback(element.id, { action: "reject", note: "rejected in editor" })}
                    >
                      Reject
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="hint">
        Confirmed and corrected elements become labelled training samples together with their source points.
        Confidence is a heuristic score, not a calibrated probability.
      </p>
    </div>
  );
}
