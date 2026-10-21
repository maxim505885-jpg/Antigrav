import assert from "node:assert/strict";
import test from "node:test";
import { columnGroupLinePositions, groupCameraDistance } from "./columnGroupGeometry.ts";

const column = {
  id: "a", class_name: "column", measured: true, inferred: false,
  geometry: { kind: "oriented_box", center: [1001, 2002, 3003],
    sizes: { length: 2, thickness: 1, height: 4 }, rotation_z: Math.PI / 2 },
};

test("camera fits the whole group in a narrow viewport as well as a wide one", () => {
  const radius = 10, verticalFov = 50;
  const narrow = groupCameraDistance(radius, verticalFov, 0.3);
  const wide = groupCameraDistance(radius, verticalFov, 2);
  const halfVertical = verticalFov * Math.PI / 360;
  const halfHorizontal = Math.atan(Math.tan(halfVertical) * 0.3);
  assert.ok(narrow * Math.sin(halfHorizontal) >= radius * 1.05);
  assert.ok(wide * Math.sin(halfVertical) >= radius * 1.05);
  assert.ok(narrow > wide);
});

test("group outlines preserve measured rotation, origin and each physical instance", () => {
  const other = { ...column, id: "b", geometry: { ...column.geometry, center: [1007, 2002, 3003] } };
  const result = columnGroupLinePositions([column, other], ["a", "b", "a"], [1000, 2000, 3000]);
  assert.deepEqual(result.rendered_ids, ["a", "b"]);
  assert.equal(result.positions.length, 144); // twelve independent box edges per column
  const first = Array.from(result.positions.slice(0, 72));
  const xs = first.filter((_, i) => i % 3 === 0);
  const ys = first.filter((_, i) => i % 3 === 1);
  const zs = first.filter((_, i) => i % 3 === 2);
  assert.equal(Math.min(...xs), 0.5);
  assert.equal(Math.max(...xs), 1.5);
  assert.equal(Math.min(...ys), 1);
  assert.equal(Math.max(...ys), 3);
  assert.equal(Math.min(...zs), 1);
  assert.equal(Math.max(...zs), 5);
  assert.deepEqual(column.geometry.center, [1001, 2002, 3003]);
});

test("unknown, unmeasured and malformed members do not create invented group geometry", () => {
  const noAngle = { ...column, id: "no-angle", geometry: { ...column.geometry, rotation_z: undefined } };
  const result = columnGroupLinePositions([
    noAngle, { ...column, id: "inferred", inferred: true },
    { ...column, id: "beam", class_name: "beam" },
  ], ["no-angle", "inferred", "beam", "missing"]);
  assert.equal(result.positions.length, 0);
  assert.deepEqual(result.rendered_ids, []);
  assert.deepEqual(result.unavailable_ids, ["no-angle", "inferred", "beam", "missing"]);
});
