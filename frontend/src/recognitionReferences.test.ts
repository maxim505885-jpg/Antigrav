import assert from "node:assert/strict";
import test from "node:test";
import { buildRecognitionEvaluationRequest, emptyPhysicalReferenceDraft, roleMatchesClass, roleOptionsForClass } from "./recognitionReferences.ts";
import type { ElementAnnotationDataset } from "./api.ts";

const dataset = {
  source_snapshot_sha256: "snapshot-123",
} as ElementAnnotationDataset;

const validReference = {
  ...emptyPhysicalReferenceDraft(),
  physical_instance_id: "  C-01  ",
  class_name: "column",
  min_x: "0", min_y: "1.25", min_z: "-2",
  max_x: "0.4", max_y: "1.65", max_z: "5.5",
};

test("builds a snapshot-bound request from independent meter coordinates", () => {
  const result = buildRecognitionEvaluationRequest(dataset, {
    reference_set_id: "field-check-01",
    reference_kind: "field_measurement",
    annotator: "Surveyor",
  }, [validReference]);

  assert.deepEqual(result, {
    source_snapshot_sha256: "snapshot-123",
    reference_set_id: "field-check-01",
    reference_origin: "independent_manual",
    reference_kind: "field_measurement",
    annotator: "Surveyor",
    iou_threshold: 0.5,
    reference_elements: [{
      physical_instance_id: "C-01",
      class_name: "column",
      role_label: null,
      bbox: { min: [0, 1.25, -2], max: [0.4, 1.65, 5.5] },
    }],
  });
});

test("accepts Russian decimal commas and leaves a new reference completely blank", () => {
  const empty = emptyPhysicalReferenceDraft();
  assert.ok(Object.values(empty).every((value) => value === ""));
  const result = buildRecognitionEvaluationRequest(dataset, {
    reference_set_id: "field-check-02", reference_kind: "manual_cloud", annotator: "Engineer",
  }, [{ ...validReference, min_x: "0,0", min_y: "1,25", min_z: "-2,0", max_x: "0,4", max_y: "1,65", max_z: "5,5" }]);
  assert.deepEqual(result.reference_elements[0].bbox, { min: [0, 1.25, -2], max: [0.4, 1.65, 5.5] });
});

test("keeps the physical reference role optional and independent", () => {
  const metadata = { reference_set_id: "set-role", reference_kind: "field_measurement" as const, annotator: "Engineer" };
  const role = buildRecognitionEvaluationRequest(dataset, metadata, [{ ...validReference, class_name: "beam", role_label: "crane_girder" }]);
  assert.equal(role.reference_elements[0].role_label, "crane_girder");
  assert.equal(buildRecognitionEvaluationRequest(dataset, metadata, [validReference]).reference_elements[0].role_label, null);
});

test("filters and validates roles against the independent physical class", () => {
  const options = [["column", "Колонна"], ["crane_girder", "Подкрановая балка"], ["unknown", "Неизвестно"]] as const;
  assert.deepEqual(roleOptionsForClass("column", options).map(([id]) => id), ["column", "unknown"]);
  assert.equal(roleMatchesClass("beam", "crane_girder"), true);
  assert.equal(roleMatchesClass("column", "crane_girder"), false);
  assert.throws(() => buildRecognitionEvaluationRequest(dataset, {
    reference_set_id: "set-invalid-role", reference_kind: "field_measurement", annotator: "Engineer",
  }, [{ ...validReference, role_label: "crane_girder" }]), /роль не соответствует/i);
});

test("rejects blank metadata, duplicate physical ids, nonfinite and reversed bounds", () => {
  const metadata = { reference_set_id: "set-1", reference_kind: "manual_cloud" as const, annotator: "Engineer" };
  assert.throws(() => buildRecognitionEvaluationRequest(dataset, { ...metadata, annotator: " " }, [validReference]), /разметчика/i);
  assert.throws(() => buildRecognitionEvaluationRequest(dataset, metadata, [validReference, validReference]), /повторяется/i);
  assert.throws(() => buildRecognitionEvaluationRequest(dataset, metadata, [{ ...validReference, min_x: "NaN" }]), /координат/i);
  assert.throws(() => buildRecognitionEvaluationRequest(dataset, metadata, [{ ...validReference, max_y: "1.2" }]), /меньше/i);
  assert.throws(() => buildRecognitionEvaluationRequest(dataset, metadata, [{ ...validReference, class_name: "" }]), /класс/i);
});

test("requires at least one actual physical reference and never infers it from a candidate", () => {
  assert.throws(() => buildRecognitionEvaluationRequest(dataset, {
    reference_set_id: "set-1", reference_kind: "mixed", annotator: "Engineer",
  }, []), /хотя бы один/i);
});
