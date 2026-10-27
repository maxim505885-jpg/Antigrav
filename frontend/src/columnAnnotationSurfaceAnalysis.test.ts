import assert from "node:assert/strict";
import test from "node:test";

import type { ColumnSurfaceTrackAnalysisResponse } from "./api.ts";
import { validateColumnAnnotationSurfaceAnalysis } from "./columnAnnotationSurfaceAnalysis.ts";

const report = (overrides: Record<string, unknown> = {}) => ({
  schema: "scan.column-surface-track-analysis/1",
  cloud_id: "cloud-1",
  candidate_id: "column-1",
  confirmed: false,
  persisted: false,
  source_geometry_modified: false,
  ...overrides,
}) as unknown as ColumnSurfaceTrackAnalysisResponse;

test("accepts only a read-only surface report bound to the selected cloud and column", () => {
  const value = report();
  assert.equal(validateColumnAnnotationSurfaceAnalysis(value, "cloud-1", "column-1"), value);
});

test("rejects reports from another candidate or cloud", () => {
  assert.throws(() => validateColumnAnnotationSurfaceAnalysis(report({ candidate_id: "other" }), "cloud-1", "column-1"));
  assert.throws(() => validateColumnAnnotationSurfaceAnalysis(report({ cloud_id: "other" }), "cloud-1", "column-1"));
});

test("rejects persisted or geometry-mutating reports from annotation evidence", () => {
  assert.throws(() => validateColumnAnnotationSurfaceAnalysis(report({ persisted: true }), "cloud-1", "column-1"));
  assert.throws(() => validateColumnAnnotationSurfaceAnalysis(report({ source_geometry_modified: true }), "cloud-1", "column-1"));
});
