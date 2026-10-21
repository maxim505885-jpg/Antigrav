import assert from "node:assert/strict";
import test from "node:test";
import { sliceElementPositions, toLocalElementPositions } from "./elementPointGeometry.ts";

test("converts world element points to the cloud preview coordinate frame", () => {
  const positions = toLocalElementPositions([[110, 198, 305], [112, 201, 307]], [100, 200, 300]);
  assert.deepEqual(Array.from(positions), [10, -2, 5, 12, 1, 7]);
});

test("uses a zero origin when cloud metadata has no origin", () => {
  const positions = toLocalElementPositions([[1, 2, 3]], null);
  assert.deepEqual(Array.from(positions), [1, 2, 3]);
});

test("extracts centered X, Y and Z source-point slices within the element bounds", () => {
  const positions = [
    [0, 0, 0],
    [0.5, 0.1, 0.1],
    [0.1, 0.5, 0.1],
    [0.1, 0.1, 0.5],
    [0.5, 0.5, 0.5],
    [1.1, 0.5, 0.5],
  ];
  const slices = sliceElementPositions(positions, { min: [0, 0, 0], max: [1, 1, 1] }, [0.5, 0.5, 0.5]);
  assert.deepEqual(slices.map((slice) => slice.length / 3), [2, 2, 2]);
});
