import assert from "node:assert/strict";
import test from "node:test";

import { elementTableEvidenceBadges } from "./elementEvidence.ts";
import { elementPlanDimensionSummary } from "./elementTablePresentation.ts";
import type { Element } from "./types.ts";

const candidate = (overrides: Partial<Element> = {}) => ({
  bbox: { min: [1, 2, 0], max: [1, 2, 6] },
  geometry: undefined,
  ...overrides,
}) as Element;

test("does not present a zero-volume bbox as a measured zero-size section", () => {
  assert.equal(elementPlanDimensionSummary(candidate()), "габарит не измерен (bbox вырожден)");
});

test("labels a valid member centerline without claiming a section measurement", () => {
  assert.equal(elementPlanDimensionSummary(candidate({
    geometry: { kind: "member", p0: [1, 2, 0], p1: [1, 2, 6] },
  })), "ось кандидата · сечение не измерено");
});

test("shows positive XY extents as bbox dimensions, not as a catalog profile", () => {
  assert.equal(elementPlanDimensionSummary(candidate({
    bbox: { min: [1, 2, 0], max: [1.4, 2.3, 6] },
  })), "400 × 300 мм (bbox)");
});

test("treats missing bounds as unknown instead of calculating from placeholders", () => {
  assert.equal(elementPlanDimensionSummary(candidate({ bbox: undefined })), "габарит не определён");
});

test("shows nominal-grid column hypotheses as unverified and exposes only the known pitch", () => {
  const badges = elementTableEvidenceBadges(candidate({
    class_name: "column",
    confidence: 0,
    confidence_kind: "not_calibrated",
    measured: false,
    inferred: true,
    source: "structural_grid",
    dimensions: {
      nominal_grid_hypothesis: { grid_hypothesis: { status: "grid_control_not_provided", nominal_step_m: 6 } },
    },
    metadata: { method: "legacy_grid_search_window", legacy_claims_redacted: true },
  }));

  assert.ok(badges.some((badge) => badge.text === "оси не заданы · шаг 6 м"));
  assert.match(badges.find((badge) => badge.text === "оси не заданы · шаг 6 м")!.title, /Начало координат, поворот и поперечные оси не заданы/);
});

test("marks a recognizer-proposed crane-girder role as a hypothesis in the candidate table", () => {
  const badges = elementTableEvidenceBadges(candidate({
    class_name: "beam",
    dimensions: { role: "crane_girder", role_label: "подкрановая балка", role_status: "proposed" },
  }));
  assert.ok(badges.some((badge) => badge.text === "роль — гипотеза"));
});
