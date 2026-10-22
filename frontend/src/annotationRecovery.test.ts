import assert from "node:assert/strict";
import test from "node:test";
import { restoreAnnotationAsDraft } from "./annotationRecovery.ts";

test("restores an archived annotation only as an editable draft bound to the current snapshot", () => {
  const archived = {
    source_snapshot_sha256: "old-snapshot",
    dataset_id: "cloud:old",
    element_id: "column-a1",
    revision: 3,
    created_at: "2026-10-20T12:00:00Z",
    annotator: "reviewer",
    state: "labeled" as const,
    physical_instance_id: "C-01",
    type_label: "K1",
    shape_label: "rectangular_solid" as const,
    structural_role: "column" as const,
    sides_m: { long: 0.5, short: 0.4 },
    measurement_source: "manual_cloud" as const,
    z_measurements: [{ z_m: 2, sides_m: { long: 0.5, short: 0.4 }, note: "checked" }],
    visible_faces: ["u+", "v+"] as ("u+" | "u-" | "v+" | "v-")[],
    hidden_faces: ["u-", "v-"] as ("u+" | "u-" | "v+" | "v-")[],
    confidence: 0.9,
    reason_unknown: "",
    note: "reviewed dimensions",
  };

  const draft = restoreAnnotationAsDraft(archived, "current-snapshot");

  assert.equal(draft.source_snapshot_sha256, "current-snapshot");
  assert.equal(draft.physical_instance_id, "C-01");
  assert.equal(draft.sides_m?.long, 0.5);
  assert.deepEqual(draft.z_measurements, archived.z_measurements);
  assert.notEqual(draft.visible_faces, archived.visible_faces);
  draft.visible_faces.pop();
  assert.equal(archived.visible_faces.length, 2);
  assert.equal("revision" in draft, false);
  assert.equal("dataset_id" in draft, false);
});
