import assert from "node:assert/strict";
import { decodeRegistrationPreviewPositions, transformRegistrationPreviewPositions } from "./registrationPreview.ts";

const pointRecords = new ArrayBuffer(15 * 5);
const pointView = new DataView(pointRecords);
for (let i = 0; i < 5; i += 1) {
  pointView.setFloat32(i * 15, i, true);
  pointView.setFloat32(i * 15 + 4, i + 10, true);
  pointView.setFloat32(i * 15 + 8, i + 20, true);
}
assert.deepEqual([...decodeRegistrationPreviewPositions(pointRecords, 2)], [0, 10, 20, 3, 13, 23]);
assert.deepEqual([...decodeRegistrationPreviewPositions(pointRecords, 10)], [0, 10, 20, 1, 11, 21, 2, 12, 22, 3, 13, 23, 4, 14, 24]);
assert.throws(() => decodeRegistrationPreviewPositions(pointRecords, 0), /positive integer/);
assert.throws(() => decodeRegistrationPreviewPositions(new ArrayBuffer(14), 10), /15-byte records/);

const rotateTranslate = [
  [0, -1, 0, 10],
  [1, 0, 0, 20],
  [0, 0, 1, 30],
  [0, 0, 0, 1],
];

const original = new Float32Array([1, 2, 3, -2, 4, 0]);
const transformed = transformRegistrationPreviewPositions(original, rotateTranslate);
assert.deepEqual([...transformed], [8, 21, 33, 6, 18, 30]);
assert.deepEqual([...original], [1, 2, 3, -2, 4, 0], "source preview points must remain unchanged");
assert.notEqual(transformed, original, "preview uses a derived buffer");

assert.throws(() => transformRegistrationPreviewPositions(new Float32Array([1, 2]), rotateTranslate), /XYZ triplets/);
assert.throws(() => transformRegistrationPreviewPositions(original, [[1, 0], [0, 1]]), /finite 4×4/);
assert.throws(() => transformRegistrationPreviewPositions(new Float32Array([Number.NaN, 0, 0]), rotateTranslate), /positions must be finite/);
assert.throws(() => transformRegistrationPreviewPositions(original, [
  [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0],
]), /affine rigid transform/);

console.log("registration preview transform: ok");
