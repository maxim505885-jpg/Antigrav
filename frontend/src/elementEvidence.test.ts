import assert from "node:assert/strict";
import test from "node:test";

import { columnCandidateStatusBadges, elementEvidenceBadges, nominalGridHypothesisBadges } from "./elementEvidence.ts";

test("labels geometry-passing column as a candidate pending review", () => {
  assert.deepEqual(columnCandidateStatusBadges({ structural_status: "structural_candidate" }), [{
    text: "кандидат колонны · нужна проверка",
    title: "Кандидат проходит геометрические фильтры, но облако точек не подтверждает конструктивную роль, физический ID или сечение",
    cls: "inferred",
  }]);
});

test("keeps failed and single-level candidates visible with uncertainty badges", () => {
  assert.deepEqual(columnCandidateStatusBadges({
    structural_status: "single_storey_coverage_candidate",
    rejection_reason: "Короткий кандидат",
  }), [
    {
      text: "кандидат не прошёл фильтр · проверить",
      title: "Короткий кандидат",
      cls: "inferred",
    },
    {
      text: "видна на одном уровне · проверить",
      title: "Неполное сканирование или закрытие поверхности может объяснить отсутствие точек на других уровнях; кандидат сохранён для ручной проверки",
      cls: "inferred",
    },
  ]);
  assert.deepEqual(columnCandidateStatusBadges({ structural_status: "failed_structural_heuristic" })[0].cls, "inferred");
  assert.deepEqual(columnCandidateStatusBadges(null), []);
});

test("shows unresolved vertical layer diagnostics without claiming a member role", () => {
  assert.deepEqual(elementEvidenceBadges({
    vertical_profile_evidence: {
      interpretation: "ambiguous_vertical_profile",
      layer_centers_m: [8.2, 8.55],
      role_assignment: "unresolved",
    },
  }), [{
    text: "несколько высотных слоёв",
    title: "Профиль точек содержит несколько разнесённых по высоте слоёв. Их роль не определена; рельс и балка автоматически не разделялись.",
    cls: "inferred",
  }]);
});

test("shows end detail as ambiguous and keeps physical support unknown", () => {
  assert.deepEqual(elementEvidenceBadges({
    terminal_evidence: {
      interpretation: "possible_end_plate_or_connection_detail",
      ambiguous_end_regions: ["start", "end"],
      physical_support: "unknown",
      axis_changed: false,
    },
  }), [{
    text: "проверить торцевую деталь",
    title: "У конца оси есть поперечно расширенная группа точек — возможны торцевая пластина, соединение или помеха. Физическая опора не подтверждена; измеренная ось не смещалась.",
    cls: "inferred",
  }]);
});

test("ignores absent, unrelated and malformed metadata", () => {
  assert.deepEqual(elementEvidenceBadges({}), []);
  assert.deepEqual(elementEvidenceBadges({ terminal_evidence: { interpretation: "other" } }), []);
  assert.deepEqual(elementEvidenceBadges({ vertical_profile_evidence: null }), []);
});

test("shows nominal grid alignment as an unverified hypothesis", () => {
  const badges = nominalGridHypothesisBadges({
    nominal_grid_hypothesis: {
      review_state: "unreviewed",
      grid_hypothesis: {
        row: "Б",
        axis: 5,
        delta_u_mm: 12,
        delta_v_mm: -8,
        status: "unverified_candidate",
      },
    },
  });
  assert.equal(badges.length, 1);
  assert.equal(badges[0].text, "ряд Б · ось 5 — гипотеза");
  assert.match(badges[0].title, /не подтверждение марки или допуска/);
  assert.equal(badges[0].cls, "inferred");
});

test("downgrades legacy grid and tolerance claims to a review warning", () => {
  const badges = nominalGridHypothesisBadges({
    structural_status: "confirmed_grid_column",
    tolerance_badge: "В допуске СП 70",
  });
  assert.equal(badges.length, 1);
  assert.equal(badges[0].text, "старое подтверждение по сетке · проверить");
  assert.equal(badges[0].cls, "inferred");
});
