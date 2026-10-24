import assert from "node:assert/strict";
import test from "node:test";

import { columnCandidateStatusBadges, elementEvidenceBadges, nominalGridHypothesisBadges, structuralRoleStatusBadge } from "./elementEvidence.ts";
import { annotationCandidateEvidence } from "./annotationCandidateEvidence.ts";
import type { Element } from "./types.ts";

test("presents recognition output as read-only evidence for independent annotation", () => {
  const evidence = annotationCandidateEvidence({
    class_name: "beam",
    source: "geometric",
    confidence: 0.82,
    confidence_kind: "heuristic",
    bbox: { min: [1, 2, 3], max: [7, 2.4, 3.6] },
    dimensions: { role: "crane_girder", role_status: "proposed" },
  } as Element, (className) => className === "beam" ? "балка" : className);

  assert.deepEqual(evidence, {
    classLabel: "балка",
    roleLabel: "подкрановая балка",
    roleStatus: "гипотеза",
    sourceLabel: "геометрия",
    bboxLabel: "6000 × 400 × 600 мм",
    confidenceLabel: "82% · эвристический балл, не вероятность",
  });
});

test("explains grid consensus without presenting it as a physical survey", () => {
  const evidence = annotationCandidateEvidence({
    class_name: "column",
    source: "structural_grid",
    confidence: 0.98,
    confidence_kind: "measured_grid_consensus",
    bbox: { min: [0, 0, 0], max: [0.9, 0.7, 9.5] },
    dimensions: {},
  } as Element);

  assert.equal(evidence.confidenceLabel, "98% · согласование с номинальной сеткой, не контрольная съёмка");
  assert.equal(evidence.sourceLabel, "номинальная сетка");
});

test("does not display an uncalibrated candidate as a zero-percent confidence score", () => {
  const evidence = annotationCandidateEvidence({
    class_name: "column",
    source: "structural_grid",
    confidence: 0,
    confidence_kind: "not_calibrated",
    geometry: { kind: "member", axis_status: "window_derived_candidate", p0: [1, 2, 0], p1: [1, 2, 8] },
    bbox: { min: [1, 2, 0], max: [1, 2, 8] },
    dimensions: { section_status: "not_measured" },
  } as Element);

  assert.equal(evidence.confidenceLabel, "не калибрована");
  assert.equal(evidence.bboxLabel, "ось · наблюдаемая длина 8000 мм · сечение не измерено");
});

test("does not invent dimensions or confidence when candidate geometry is invalid", () => {
  const evidence = annotationCandidateEvidence({
    class_name: "column",
    source: "unknown_source",
    confidence: Number.NaN,
    confidence_kind: "",
    bbox: { min: [2, 2, 2], max: [1, 2, 3] },
    dimensions: {},
  } as Element);

  assert.equal(evidence.bboxLabel, "габарит не рассчитан");
  assert.equal(evidence.confidenceLabel, "не задана или не калибрована");
  assert.equal(evidence.roleLabel, "роль не предложена");
  assert.equal(evidence.sourceLabel, "unknown_source");
});

test("marks recognizer-assigned structural roles as hypotheses until reviewed", () => {
  assert.deepEqual(structuralRoleStatusBadge("подкрановая балка", "proposed"), [{
    text: "роль — гипотеза",
    title: "Распознаватель предложил роль «подкрановая балка» по геометрии. Инженерная проверка не выполнена; не использовать её как подтверждённую классификацию.",
    cls: "inferred",
  }]);
  assert.deepEqual(structuralRoleStatusBadge("подкрановая балка", "confirmed"), []);
  assert.deepEqual(structuralRoleStatusBadge(" ", "proposed"), []);
});

test("column context stays a runway hypothesis with unknown physical support", () => {
  const [badge] = elementEvidenceBadges({column_support_context: {
    status: "supported_hypothesis", support_spacing_m: 6,
    supports: [
      {axis_offset_m: 0.08},
      {axis_offset_m: 0.14},
    ],
  }});
  assert.match(badge.text, /колонны/);
  assert.match(badge.title, /6 м/);
  assert.match(badge.title, /2 колонны/);
  assert.match(badge.title, /0\.14 м/);
  assert.match(badge.title, /не подтверждены/);
  assert.equal(badge.cls, "inferred");
});

test("shows separate endpoint column evidence for a runway hypothesis", () => {
  const [badge] = elementEvidenceBadges({column_support_context: {
    status: "supported_hypothesis", support_spacing_m: 6,
    endpoint_search_margin_m: 0.6,
    end_supports: {
      start: {column_index: 2, gap_m: 0.1},
      end: {column_index: 7, gap_m: 0.3},
    },
    supports: [{axis_offset_m: 0.12}, {axis_offset_m: 0.14}],
  }});
  assert.equal(badge.text, "колонны у обоих концов · проверить опирание");
  assert.match(badge.title, /начало: 0\.10 м/);
  assert.match(badge.title, /конец: 0\.30 м/);
  assert.match(badge.title, /эвристика/);
  assert.match(badge.title, /не подтверждены/);
});

test("missing column context is visible and invalid spacing is not printed", () => {
  const [badge] = elementEvidenceBadges({column_support_context: {status: "insufficient_context"}});
  assert.match(badge.text, /не установлена/);
  const invalid = elementEvidenceBadges({column_support_context: {
    status: "supported_hypothesis", support_spacing_m: NaN,
  }});
  assert.doesNotMatch(invalid[0].title, /NaN/);
  assert.deepEqual(elementEvidenceBadges({column_support_context: {status: "other"}}), []);
});

test("explains when columns exist but do not cover both beam ends", () => {
  const [badge] = elementEvidenceBadges({column_support_context: {
    status: "insufficient_context",
    supports: [{column_index: 1}, {column_index: 2}],
    end_supports: {start: null, end: null},
  }});
  assert.equal(badge.text, "опоры у обоих концов не найдены");
  assert.match(badge.title, /В полосе балки найдено колонн: 2/);
  assert.match(badge.title, /нужны разные колонны у обоих концов/);
  assert.equal(badge.cls, "inferred");
});

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

test("shows only known bay pitch when surveyed grid control is missing", () => {
  const badges = nominalGridHypothesisBadges({
    nominal_grid_hypothesis: {
      review_state: "unreviewed",
      grid_hypothesis: {
        row: null,
        axis: null,
        delta_u_mm: null,
        delta_v_mm: null,
        status: "grid_control_not_provided",
        nominal_step_m: 6.0,
      },
    },
  });

  assert.equal(badges[0].text, "оси не заданы · шаг 6 м");
  assert.match(badges[0].title, /Начало координат, поворот и поперечные оси не заданы/);
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
