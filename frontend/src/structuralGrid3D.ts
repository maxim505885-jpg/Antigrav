/**
 * Structural Coordination Grid (Координационная сетка СПДС цеха)
 * 3 Spans (4 rows: А, Б, В, Г), 24 Transverse Axes (1..24, step 6000 mm).
 */

export interface GridAxisNode {
  label: string;
  position: [number, number, number];
  type: "bay" | "row";
}

export interface StructuralGridData {
  transverseLinePositions: Float32Array;
  longitudinalLinePositions: Float32Array;
  bubbleNodes: GridAxisNode[];
}

export const WORKSHOP_GRID_CONFIG = {
  angleDeg: 10.260,
  floorZ: -11.55,
  rowAxes: [
    { label: "А", v: -29.80 },
    { label: "Б", v: -16.55 },
    { label: "В", v: -4.85 },
    { label: "Г", v: 8.40 },
  ],
  uBase: 0.14,
  bayStepM: 6.0,
  bayIndices: Array.from({ length: 24 }, (_, i) => i - 16), // -16 .. 7 -> 24 axes
};

export function computeStructuralGridGeometry(
  origin: readonly number[] = [0, 0, 0],
  config = WORKSHOP_GRID_CONFIG,
): StructuralGridData {
  const rad = (config.angleDeg * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  const ox = origin[0] ?? 0;
  const oy = origin[1] ?? 0;
  const oz = origin[2] ?? 0;
  const z = config.floorZ - oz;

  const toWorld = (u: number, v: number): [number, number, number] => {
    const x = u * cos - v * sin - ox;
    const y = u * sin + v * cos - oy;
    return [x, y, z];
  };

  const rows = config.rowAxes;
  const vMin = rows[0].v;
  const vMax = rows[rows.length - 1].v;
  const vMargin = 4.0;
  const vStart = vMin - vMargin;
  const vEnd = vMax + vMargin;

  const uCoords = config.bayIndices.map((k) => config.uBase + k * config.bayStepM);
  const uMin = uCoords[0];
  const uMax = uCoords[uCoords.length - 1];
  const uMargin = 4.0;
  const uStart = uMin - uMargin;
  const uEnd = uMax + uMargin;

  // 1. Transverse lines (Axes 1..24)
  const transversePositions: number[] = [];
  const bubbleNodes: GridAxisNode[] = [];

  uCoords.forEach((u, idx) => {
    const bayNum = String(idx + 1);
    const p1 = toWorld(u, vStart);
    const p2 = toWorld(u, vEnd);
    transversePositions.push(p1[0], p1[1], p1[2], p2[0], p2[1], p2[2]);

    // Bubble markers at both ends of each transverse axis
    const bSouth = toWorld(u, vStart - 1.5);
    const bNorth = toWorld(u, vEnd + 1.5);
    bubbleNodes.push({ label: bayNum, position: bSouth, type: "bay" });
    bubbleNodes.push({ label: bayNum, position: bNorth, type: "bay" });
  });

  // 2. Longitudinal lines (Rows А, Б, В, Г)
  const longitudinalPositions: number[] = [];
  rows.forEach((row) => {
    const p1 = toWorld(uStart, row.v);
    const p2 = toWorld(uEnd, row.v);
    longitudinalPositions.push(p1[0], p1[1], p1[2], p2[0], p2[1], p2[2]);

    // Bubble markers at both ends of each row
    const bWest = toWorld(uStart - 1.8, row.v);
    const bEast = toWorld(uEnd + 1.8, row.v);
    bubbleNodes.push({ label: row.label, position: bWest, type: "row" });
    bubbleNodes.push({ label: row.label, position: bEast, type: "row" });
  });

  return {
    transverseLinePositions: new Float32Array(transversePositions),
    longitudinalLinePositions: new Float32Array(longitudinalPositions),
    bubbleNodes,
  };
}
