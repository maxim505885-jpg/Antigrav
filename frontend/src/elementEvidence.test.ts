import assert from "node:assert/strict";
import test from "node:test";

import { elementEvidenceBadges } from "./elementEvidence.ts";

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
