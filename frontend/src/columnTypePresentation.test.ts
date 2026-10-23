import assert from "node:assert/strict";
import test from "node:test";

import { measuredColumnTypeSides } from "./columnTypePresentation.ts";

test("shows point-measured section sides instead of the candidate box", () => {
  assert.deepEqual(measuredColumnTypeSides({
    geometry: { sizes: { length: 0.8, thickness: 0.4 } },
    dimensions: { section_status: "measured_2_axes", measured_section_m: [0.401, 0.601] },
  }), { long: 0.601, short: 0.401, source: "point-section" });
});

test("does not replace an invalid point-measured section with model box dimensions", () => {
  assert.equal(measuredColumnTypeSides({
    geometry: { sizes: { length: 0.8, thickness: 0.4 } },
    dimensions: { section_status: "unique_section", measured_section_m: [0.6, null] },
  }), null);
});

test("does not present partial or coarse section sizes as complete measurements", () => {
  for (const section_status of ["partial_one_axis", "coarse_grid_only", "unconfirmed"]) {
    assert.equal(measuredColumnTypeSides({
      geometry: { sizes: { length: 0.8, thickness: 0.4 } },
      dimensions: { section_status },
    }), null);
  }
});

test("uses preferred oriented-box sides and canonicalizes their order", () => {
  assert.deepEqual(measuredColumnTypeSides({
    geometry: { sizes: { length: 0.4, thickness: 0.5 } },
    dimensions: { length_m: 0.9, thickness_m: 0.7 },
  }), { long: 0.5, short: 0.4, source: "model-dimensions" });
});

test("an invalid preferred box side does not silently fall back to another field", () => {
  assert.equal(measuredColumnTypeSides({
    geometry: { sizes: { length: 0, thickness: 0.4 } },
    dimensions: { length_m: 0.5, thickness_m: 0.4 },
  }), null);
});
