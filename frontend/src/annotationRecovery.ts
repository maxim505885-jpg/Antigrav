import type { ColumnAnnotation, ColumnAnnotationDraft } from "./api";

export type ArchivedColumnAnnotation = ColumnAnnotation & {
  dataset_id: string;
  source_snapshot_sha256: string;
};

/** Copy an archived decision into an editable draft bound to the current snapshot. */
export function restoreAnnotationAsDraft(
  annotation: ArchivedColumnAnnotation,
  currentSnapshotSha256: string,
): ColumnAnnotationDraft {
  if (!currentSnapshotSha256.trim()) throw new Error("Текущий снимок облака не загружен.");
  return {
    source_snapshot_sha256: currentSnapshotSha256,
    annotator: annotation.annotator || "",
    state: annotation.state === "pending" ? "labeled" : annotation.state,
    physical_instance_id: annotation.physical_instance_id || null,
    type_label: annotation.type_label || null,
    shape_label: annotation.shape_label || null,
    structural_role: annotation.structural_role || null,
    sides_m: annotation.sides_m ? { ...annotation.sides_m } : null,
    measurement_source: annotation.measurement_source || null,
    z_measurements: annotation.z_measurements.map((item) => ({
      z_m: item.z_m,
      sides_m: item.sides_m ? { ...item.sides_m } : null,
      note: item.note,
    })),
    visible_faces: [...annotation.visible_faces],
    hidden_faces: [...annotation.hidden_faces],
    confidence: annotation.confidence,
    reason_unknown: annotation.reason_unknown,
    note: annotation.note,
  };
}
