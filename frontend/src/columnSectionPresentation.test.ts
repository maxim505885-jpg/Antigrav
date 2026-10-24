import assert from "node:assert/strict";
import test from "node:test";

import { columnSectionObservationSummary, parallelFaceObservationSummary } from "./columnSectionPresentation.ts";

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

test("distinguishes several parallel surface traces from a rectangular section", () => {
  assert.equal(parallelFaceObservationSummary([
    { start_world_m: [0, 0], end_world_m: [0.1, 0.5] },
    { start_world_m: [1, 1], end_world_m: [1.1, 1.5] },
    { start_world_m: [2, 0], end_world_m: [2.1, 0.5] },
  ]), "Обнаружено параллельных поверхностей: 3. Они не подтверждают замкнутый прямоугольный контур колонны.");
});

test("does not mark perpendicular section edges as parallel", () => {
  assert.equal(parallelFaceObservationSummary([
    { start_world_m: [0, 0], end_world_m: [1, 0] },
    { start_world_m: [0, 0], end_world_m: [0, 1] },
  ]), null);
});
