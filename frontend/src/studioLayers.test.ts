import assert from "node:assert/strict";
import { isStudioLayerVisible, selectStudioOverlayElements } from "./studioLayers.ts";
import type { Element } from "./types.ts";

const element = (id: string, review_status: string) => ({ id, review_status }) as Element;
const candidates = [
  element("candidate", "unreviewed"),
  element("confirmed", "confirmed"),
  element("corrected", "corrected"),
  element("rejected", "rejected"),
  element("invalidated", "invalidated"),
];

assert.deepEqual(
  selectStudioOverlayElements(candidates, { aiStructures: true, bimModel: false }).map(({ id }) => id),
  ["candidate"],
);
assert.deepEqual(
  selectStudioOverlayElements(candidates, { aiStructures: false, bimModel: true }).map(({ id }) => id),
  ["confirmed", "corrected"],
);
assert.deepEqual(
  selectStudioOverlayElements(candidates, { aiStructures: true, bimModel: true }).map(({ id }) => id),
  ["candidate", "confirmed", "corrected"],
);
assert.deepEqual(selectStudioOverlayElements(candidates, { aiStructures: false, bimModel: false }), []);
assert.equal(isStudioLayerVisible(true, true), true);
assert.equal(isStudioLayerVisible(true, false), false);
assert.equal(isStudioLayerVisible(false, true), false);
console.log("studio layer visibility: ok");
