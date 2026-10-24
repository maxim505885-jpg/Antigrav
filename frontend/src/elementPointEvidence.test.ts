import test from "node:test";
import assert from "node:assert/strict";
import { elementPointEvidenceMessage } from "./elementPointEvidence.ts";

test("warns when persisted source row IDs do not land inside the current element bbox", () => {
  const message = elementPointEvidenceMessage(0, [0, 0, 0], {
    status: "mismatch",
    row_ids_count: 512,
    row_ids_checked_count: 512,
    row_ids_valid_count: 498,
    row_ids_within_bbox_count: 0,
    row_ids_sampled: true,
  });
  assert.match(message, /0\/512/);
  assert.match(message, /не совпадают/);
  assert.match(message, /повторной проверки/);
});

test("explains when a cloud snapshot changed after recognition", () => {
  const message = elementPointEvidenceMessage(0, [0, 0, 0], {
    status: "mismatch",
    row_ids_count: 512,
    row_ids_checked_count: 0,
    row_ids_valid_count: 0,
    row_ids_within_bbox_count: 0,
    row_ids_sampled: true,
    snapshot_matches: false,
  });
  assert.match(message, /файл облака изменился после распознавания/);
  assert.match(message, /запустить распознавание повторно/);
});

test("does not present an empty point query as a confirmed physical element", () => {
  const message = elementPointEvidenceMessage(0, [0, 0, 0], {
    status: "unverifiable",
    row_ids_count: 0,
    row_ids_valid_count: 0,
    row_ids_within_bbox_count: 0,
    row_ids_sampled: false,
  });
  assert.match(message, /непроверенной гипотезой/);
});

test("does not treat matching bbox points as verified without a source cloud snapshot", () => {
  const message = elementPointEvidenceMessage(12, [4, 5, 3], {
    status: "unverifiable",
    reason: "missing_source_cloud_snapshot",
    row_ids_count: 2,
    row_ids_valid_count: 2,
    row_ids_within_bbox_count: 2,
    row_ids_sampled: false,
  });
  assert.match(message, /SHA-снимок облака не сохранён/);
  assert.match(message, /повторите распознавание/);
  assert.match(message, /непроверенной гипотезой/);
});

test("reports member source rows against its measured axis rather than its zero-thickness bbox", () => {
  const message = elementPointEvidenceMessage(25, [4, 5, 3], {
    status: "consistent",
    row_ids_count: 12,
    row_ids_checked_count: 12,
    row_ids_valid_count: 12,
    row_ids_within_bbox_count: 3,
    row_ids_within_geometry_count: 12,
    geometry_check: "member_axis",
    row_ids_sampled: false,
  });
  assert.match(message, /source ID у измеренной оси: 12\/12/);
});
