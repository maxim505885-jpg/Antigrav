import assert from "node:assert/strict";
import test from "node:test";
import { elementRoleSummary } from "./elementRoleSummary.ts";
import type { Element } from "./types";

const beam = (metadata: Record<string, unknown>, dimensions: Record<string, unknown> = {}): Element => ({
  id: "beam-1", project_id: "project", cloud_id: "cloud", class_name: "beam",
  geometry: {}, bbox: { min: [0, 0, 0], max: [6, 0.4, 0.6] }, confidence: 0.5,
  confidence_kind: "heuristic", measured: true, inferred: false, source: "steel",
  review_status: "unreviewed", dimensions, metadata, created_at: "", updated_at: "",
});

test("shows a proposed crane girder role as a hypothesis", () => {
  assert.deepEqual(elementRoleSummary(beam({}, {
    role: "crane_girder", role_label: "подкрановая балка", role_status: "proposed",
  })), {
    role: "подкрановая балка",
    status: "гипотеза распознавателя",
    columnSupport: "Связь с колоннами не проверена.",
  });
});

test("explains when the beam has no detected column support", () => {
  const summary = elementRoleSummary(beam({
    column_support_context: { status: "insufficient_context", supports: [] },
  }, { role: "crane_girder", role_status: "proposed" }));
  assert.equal(summary?.columnSupport, "Связь с колоннами не установлена; проверьте опоры вручную.");
});

test("does not claim physical support when only one beam end has a column", () => {
  const summary = elementRoleSummary(beam({
    column_support_context: {
      status: "insufficient_context",
      supports: [{ column_index: 2 }],
      end_supports: { start: { column_index: 2, gap_m: 0.2 }, end: null },
    },
  }, { role: "crane_girder", role_status: "proposed" }));
  assert.equal(summary?.columnSupport, "Найдены колонны рядом: 1; пара опор у обоих концов не подтверждена.");
});

test("requires distinct column candidates at both ends before showing paired support context", () => {
  const summary = elementRoleSummary(beam({
    column_support_context: {
      status: "supported_hypothesis",
      supports: [{ column_index: 2 }, { column_index: 7 }],
      end_supports: { start: { column_index: 2, gap_m: 0.1 }, end: { column_index: 7, gap_m: 0.3 } },
    },
  }, { role: "crane_girder", role_status: "proposed" }));
  assert.equal(summary?.columnSupport, "Колонны найдены у обоих концов; физическое опирание и крановый рельс не подтверждены.");
});

test("shows the independent review status after a person confirms an element", () => {
  const summary = elementRoleSummary({ ...beam({}, { role: "crane_girder" }), review_status: "confirmed" });
  assert.equal(summary?.status, "проверено человеком");
});
