import test from "node:test";
import assert from "node:assert/strict";
import { computeStructuralGridGeometry, WORKSHOP_GRID_CONFIG } from "./structuralGrid3D.ts";

test("computeStructuralGridGeometry generates 24 transverse axes and 4 longitudinal rows", () => {
  const grid = computeStructuralGridGeometry([0, 0, 0]);

  // 24 axes * 2 points per line * 3 floats = 144
  assert.equal(grid.transverseLinePositions.length, 144);
  // 4 rows * 2 points per line * 3 floats = 24
  assert.equal(grid.longitudinalLinePositions.length, 24);

  // 24 axes * 2 bubbles + 4 rows * 2 bubbles = 48 + 8 = 56 bubbles
  assert.equal(grid.bubbleNodes.length, 56);

  const bayBubbles = grid.bubbleNodes.filter((b) => b.type === "bay");
  const rowBubbles = grid.bubbleNodes.filter((b) => b.type === "row");
  assert.equal(bayBubbles.length, 48);
  assert.equal(rowBubbles.length, 8);

  // Labels
  const rowLabels = new Set(rowBubbles.map((b) => b.label));
  assert.deepEqual(Array.from(rowLabels).sort(), ["А", "Б", "В", "Г"]);

  const bayLabels = new Set(bayBubbles.map((b) => b.label));
  assert.equal(bayLabels.size, 24);
  assert.ok(bayLabels.has("1"));
  assert.ok(bayLabels.has("24"));
});

test("computeStructuralGridGeometry accounts for origin offset", () => {
  const g0 = computeStructuralGridGeometry([0, 0, 0]);
  const gOffset = computeStructuralGridGeometry([10, -20, 5]);

  assert.ok(Math.abs(gOffset.transverseLinePositions[0] - (g0.transverseLinePositions[0] - 10)) < 1e-4);
  assert.ok(Math.abs(gOffset.transverseLinePositions[1] - (g0.transverseLinePositions[1] - (-20))) < 1e-4);
  assert.ok(Math.abs(gOffset.transverseLinePositions[2] - (g0.transverseLinePositions[2] - 5)) < 1e-4);
});
