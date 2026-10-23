import assert from "node:assert/strict";
import test from "node:test";

import type { ColumnSurfaceTrackAnalysisResponse } from "./api.ts";
import { buildColumnAnnotationHeightSuggestions } from "./columnAnnotationSuggestions.ts";

function analysis(slices: any[]): ColumnSurfaceTrackAnalysisResponse {
  return { algorithm: { section_series: "surface_tracks-v1", surface_extraction: "vertical-surfaces-v1" },
    section_series: { section_slices: slices } } as unknown as ColumnSurfaceTrackAnalysisResponse;
}

function slice(z_m: number, overrides: Record<string, unknown> = {}) {
  return {
    z_m, status: "proposed", source_point_row_id_count: 12,
    source_point_row_id_sample: [3, 4, 5],
    hypotheses: [{
      side_lengths_m: [0.4, 0.5], observed_edge_count: 4, inferred_edge_count: 0,
      edge_evidence: ["observed", "observed", "observed", "observed"],
    }],
    ...overrides,
  };
}

test("creates sorted point-linked draft rows only from complete observed rectangles", () => {
  const result = buildColumnAnnotationHeightSuggestions(analysis([slice(4), slice(2)]));
  assert.deepEqual(result.map(({ z_m, long_m, short_m }) => ({ z_m, long_m, short_m })), [
    { z_m: 2, long_m: 0.5, short_m: 0.4 },
    { z_m: 4, long_m: 0.5, short_m: 0.4 },
  ]);
  assert.equal(result[0].source_point_row_id_count, 12);
  assert.deepEqual(result[0].source_point_row_id_sample, [3, 4, 5]);
  assert.deepEqual(result[0].source_provenance, {
    source_point_row_id_count: 12, source_point_row_id_sample: [3, 4, 5],
    source_index_space: "derived_positions_row_index/1", analysis_algorithm: "surface_tracks-v1",
  });
  assert.match(result[0].note, /Черновая гипотеза системы/);
  assert.deepEqual(slice(2).hypotheses[0].side_lengths_m, [0.4, 0.5]);
});

test("does not suggest inferred, ambiguous, unknown, malformed or unlinked dimensions", () => {
  const inferred = slice(1);
  inferred.hypotheses[0].edge_evidence[3] = "inferred";
  inferred.hypotheses[0].observed_edge_count = 3;
  inferred.hypotheses[0].inferred_edge_count = 1;
  const ambiguous = slice(2, { hypotheses: [slice(2).hypotheses[0], slice(2).hypotheses[0]] });
  const unknown = slice(3, { status: "unknown" });
  const unlinked = slice(4, { source_point_row_id_count: 0, source_point_row_id_sample: [] });
  const malformed = slice(5);
  malformed.hypotheses[0].side_lengths_m[0] = Number.NaN;

  assert.deepEqual(buildColumnAnnotationHeightSuggestions(analysis([inferred, ambiguous, unknown, unlinked, malformed])), []);
});
