import assert from "node:assert/strict";
import test from "node:test";
import { selectLodLevel } from "./lodLevel.ts";

const levels = [
  { level: 0, distance_min: 60, distance_max: 10000 },
  { level: 1, distance_min: 20, distance_max: 60 },
  { level: 2, distance_min: 0, distance_max: 20 },
];

test("selects progressively denser LOD levels as the camera approaches", () => {
  assert.equal(selectLodLevel(levels, 200), 0);
  assert.equal(selectLodLevel(levels, 35), 1);
  assert.equal(selectLodLevel(levels, 10), 2);
});

test("keeps shared distance boundaries on the coarser level", () => {
  assert.equal(selectLodLevel(levels, 60), 0);
  assert.equal(selectLodLevel(levels, 20), 1);
});

test("handles unordered manifests, range gaps and invalid levels deterministically", () => {
  assert.equal(selectLodLevel([
    { level: 3, distance_min: 0, distance_max: 10 },
    { level: 8, distance_min: 50, distance_max: 100 },
  ], 30), 8);
  assert.equal(selectLodLevel([{ level: -1, distance_min: 0, distance_max: 10 }], 5), null);
  assert.equal(selectLodLevel(levels, Number.NaN), null);
  assert.equal(selectLodLevel(levels, -1), null);
});
