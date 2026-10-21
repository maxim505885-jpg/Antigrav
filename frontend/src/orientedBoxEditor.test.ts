import assert from "node:assert/strict";
import test from "node:test";
import { buildOrientedBoxGeometry, orientedBoxDraft } from "./orientedBoxEditor.ts";

test("initializes the editor draft from stored geometry in radians", () => {
  assert.deepEqual(orientedBoxDraft({
    kind: "oriented_box",
    center: [1, 2, 3],
    sizes: { length: 4, thickness: 0.3, height: 5 },
    rotation_z: Math.PI / 4,
  }), {
    centerX: "1",
    centerY: "2",
    centerZ: "3",
    length: "4",
    thickness: "0.3",
    height: "5",
    rotationDegrees: "45",
  });
});

test("builds editable oriented-box geometry and converts degrees to radians", () => {
  const geometry = buildOrientedBoxGeometry({
    centerX: "10.5",
    centerY: "-2",
    centerZ: "3",
    length: "6",
    thickness: "0.4",
    height: "5.2",
    rotationDegrees: "90",
  });

  assert.deepEqual(geometry, {
    kind: "oriented_box",
    center: [10.5, -2, 3],
    sizes: { length: 6, thickness: 0.4, height: 5.2 },
    rotation_z: Math.PI / 2,
  });
});

test("rejects non-finite centers, rotations and non-positive dimensions", () => {
  const valid = {
    centerX: "0", centerY: "0", centerZ: "0", length: "1", thickness: "1", height: "1", rotationDegrees: "0",
  };
  assert.throws(() => buildOrientedBoxGeometry({ ...valid, centerX: "" }), /координаты и размеры/);
  assert.throws(() => buildOrientedBoxGeometry({ ...valid, length: "0" }), /Размеры.*больше нуля/);
  assert.throws(() => buildOrientedBoxGeometry({ ...valid, rotationDegrees: "Infinity" }), /угол поворота/);
});
