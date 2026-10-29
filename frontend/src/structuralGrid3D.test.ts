import test from "node:test";
import assert from "node:assert/strict";
import { computeStructuralGridGeometry, type StructuralGridConfig } from "./structuralGrid3D.ts";

test("nominal 6 m pitch alone does not invent a project grid", () => {
  assert.equal(computeStructuralGridGeometry([0, 0, 0]), null);
});

test("grid geometry is generated only from an explicitly supplied layout", () => {
  const measuredLayout: StructuralGridConfig = {
    angleDeg: 0,
    floorZ: 0,
    rowAxes: [
      { label: "A", v: 0 },
      { label: "B", v: 12 },
    ],
    uBase: 0,
    bayStepM: 6,
    bayIndices: [0, 1],
  };
  const grid = computeStructuralGridGeometry([0, 0, 0], measuredLayout);

  assert.ok(grid);
  assert.equal(grid.transverseLinePositions.length, 12);
  assert.equal(grid.longitudinalLinePositions.length, 12);
  assert.equal(grid.bubbleNodes.length, 8);
  assert.deepEqual(
    grid.bubbleNodes.filter((node) => node.type === "row").map((node) => node.label).sort(),
    ["A", "A", "B", "B"],
  );
});

test("explicit grid geometry accounts for cloud origin offset", () => {
  const measuredLayout: StructuralGridConfig = {
    angleDeg: 0,
    floorZ: 0,
    rowAxes: [{ label: "A", v: 0 }],
    uBase: 0,
    bayStepM: 6,
    bayIndices: [0],
  };
  const g0 = computeStructuralGridGeometry([0, 0, 0], measuredLayout);
  const gOffset = computeStructuralGridGeometry([10, -20, 5], measuredLayout);

  assert.ok(g0 && gOffset);
  assert.ok(Math.abs(gOffset.transverseLinePositions[0] - (g0.transverseLinePositions[0] - 10)) < 1e-4);
  assert.ok(Math.abs(gOffset.transverseLinePositions[1] - (g0.transverseLinePositions[1] + 20)) < 1e-4);
  assert.ok(Math.abs(gOffset.transverseLinePositions[2] - (g0.transverseLinePositions[2] - 5)) < 1e-4);
});
