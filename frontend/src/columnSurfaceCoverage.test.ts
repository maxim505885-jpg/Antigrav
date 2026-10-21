import assert from "node:assert/strict";
import test from "node:test";
import { buildColumnSurfaceCoverage, createSectionSampleHeights } from "./columnSurfaceCoverage.ts";

const box = {
  center: [0, 0, 0] as [number, number, number],
  rotation_z: 0,
  sizes: { length: 2, thickness: 1, height: 4 },
};

function fitAt(z: number, fractions = [0.5, 1, 0, 0.25]) {
  return {
    slice_z_m: z,
    status: "proposed",
    hypotheses: [{
      corners_world_m: [[-1, -0.5], [1, -0.5], [1, 0.5], [-1, 0.5]] as [number, number][],
      edge_observation_coverage: fractions.map((coverage_fraction, edge_index) => ({
        edge_index, length_m: edge_index % 2 === 0 ? 2 : 1,
        observed_span_m: coverage_fraction * (edge_index % 2 === 0 ? 2 : 1),
        coverage_fraction,
      })),
    }],
  };
}

test("maps edge evidence to stable oriented-box sides and sorts slices by height", () => {
  const rows = buildColumnSurfaceCoverage([fitAt(2), fitAt(1)], box);

  assert.deepEqual(rows.map((row) => row.slice_z_m), [1, 2]);
  assert.deepEqual(rows[0].sides, {
    "u+": { status: "observed", coverage_fraction: 1, observed_span_m: 1, edge_length_m: 1 },
    "u-": { status: "partial", coverage_fraction: 0.25, observed_span_m: 0.25, edge_length_m: 1 },
    "v+": { status: "no_points", coverage_fraction: 0, observed_span_m: 0, edge_length_m: 2 },
    "v-": { status: "partial", coverage_fraction: 0.5, observed_span_m: 1, edge_length_m: 2 },
  });
});

test("maps world-space corners back to the same local sides after column rotation", () => {
  const rotated = { ...box, rotation_z: Math.PI / 2 };
  const fit = fitAt(1);
  fit.hypotheses[0].corners_world_m = [[0.5, -1], [0.5, 1], [-0.5, 1], [-0.5, -1]];
  const row = buildColumnSurfaceCoverage([fit], rotated)[0];
  assert.deepEqual(Object.fromEntries(Object.entries(row.sides).map(([side, cell]) => [side, cell.status])), {
    "u+": "observed", "u-": "partial", "v+": "no_points", "v-": "partial",
  });
});

test("keeps every side ambiguous when a slice has multiple contour hypotheses", () => {
  const fit = fitAt(1);
  fit.hypotheses.push(fitAt(1).hypotheses[0]);

  const row = buildColumnSurfaceCoverage([fit], box)[0];

  assert.equal(Object.values(row.sides).every((side) => side.status === "ambiguous"), true);
  assert.equal(Object.values(row.sides).every((side) => side.coverage_fraction === null), true);
});

test("marks a slice unknown when no supported contour exists", () => {
  const row = buildColumnSurfaceCoverage([{ slice_z_m: 1, status: "unknown", hypotheses: [] }], box)[0];

  assert.equal(Object.values(row.sides).every((side) => side.status === "unknown"), true);
});

test("samples heights inside the measured box and leaves the top and bottom margin", () => {
  const heights = createSectionSampleHeights(box, 5, 0.2);
  heights.forEach((height, index) => assert.ok(Math.abs(height - [-1.9, -0.95, 0, 0.95, 1.9][index]) < 1e-10));
});

test("rejects a requested slice series that cannot fit inside the box", () => {
  assert.throws(() => createSectionSampleHeights(box, 4, 0.2), /нечётным целым числом от 3 до 9/);
  assert.throws(() => createSectionSampleHeights(box, 5, 4), /должна быть больше толщины среза/);
});
