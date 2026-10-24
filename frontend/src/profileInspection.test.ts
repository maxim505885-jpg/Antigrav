import assert from "node:assert/strict";
import test from "node:test";

import { bboxExtentsMm } from "./profileInspection.ts";

test("profile inspection reports finite bbox extents without calling them a section", () => {
  assert.deepEqual(bboxExtentsMm({ min: [1, 2, 3], max: [1.4, 2.6, 9] }), [400, 600, 6000]);
});

test("profile inspection never invents extents when bbox is absent or invalid", () => {
  assert.equal(bboxExtentsMm(null), null);
  assert.equal(bboxExtentsMm({ min: [0, 0, 0], max: [0.4, Number.NaN, 6] }), null);
  assert.equal(bboxExtentsMm({ min: [1, 0, 0], max: [0, 1, 6] }), null);
});
