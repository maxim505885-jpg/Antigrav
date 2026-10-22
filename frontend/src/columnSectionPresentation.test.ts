import assert from "node:assert/strict";
import test from "node:test";

import { columnSectionObservationSummary } from "./columnSectionPresentation.ts";

test("shows only the point-measured side of a partial section", () => {
  assert.equal(columnSectionObservationSummary({
    section_status: "partial_one_axis",
    measured_section_axes_m: { length: null, thickness: 0.4 },
    length_m: 0.6,
    thickness_m: 0.4,
  }), "сечение частичное: толщина 400 мм");
});

test("keeps coarse and unconfirmed sections explicitly unmeasured", () => {
  for (const section_status of ["coarse_grid_only", "unconfirmed"]) {
    assert.equal(columnSectionObservationSummary({ section_status }), "сечение не измерено");
  }
});

test("does not show invalid side values as measurements", () => {
  assert.equal(columnSectionObservationSummary({
    section_status: "partial_one_axis",
    measured_section_axes_m: { length: Infinity, thickness: -0.2 },
  }), "сечение частичное: размерность не определена");
});
