import type { ColumnSurfaceTrackAnalysisResponse } from "./api";

/** Reject stale, cross-cloud, or mutating reports before they enter an annotation draft. */
export function validateColumnAnnotationSurfaceAnalysis(
  analysis: ColumnSurfaceTrackAnalysisResponse,
  cloudId: string,
  candidateId: string,
): ColumnSurfaceTrackAnalysisResponse {
  if (analysis.schema !== "scan.column-surface-track-analysis/1" ||
      analysis.cloud_id !== cloudId || analysis.candidate_id !== candidateId ||
      analysis.persisted !== false || analysis.source_geometry_modified !== false || analysis.confirmed !== false) {
    throw new Error("Отчёт не прошёл проверку облака, кандидата или режима без сохранения.");
  }
  return analysis;
}
