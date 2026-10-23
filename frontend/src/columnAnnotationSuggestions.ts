import type { ColumnSurfaceTrackAnalysisResponse } from "./api";

export interface ColumnAnnotationHeightSuggestion {
  z_m: number;
  long_m: number;
  short_m: number;
  source_point_row_id_count: number;
  source_point_row_id_sample: number[];
  source_provenance: {
    source_point_row_id_count: number;
    source_point_row_id_sample: number[];
    source_index_space: "derived_positions_row_index/1";
    analysis_algorithm: string;
  };
  note: string;
}

/** Return only fully observed, point-linked rectangular contours as editable suggestions. */
export function buildColumnAnnotationHeightSuggestions(
  analysis: ColumnSurfaceTrackAnalysisResponse,
): ColumnAnnotationHeightSuggestion[] {
  const suggestions = analysis.section_series.section_slices.flatMap((slice) => {
    if (slice.status !== "proposed" || slice.hypotheses.length !== 1 ||
        slice.source_point_row_id_count <= 0 || slice.source_point_row_id_sample.length === 0) return [];
    const hypothesis = slice.hypotheses[0];
    if (hypothesis.observed_edge_count !== 4 || hypothesis.inferred_edge_count !== 0 ||
        hypothesis.edge_evidence.length !== 4 || hypothesis.edge_evidence.some((edge) => edge !== "observed")) return [];
    const sides = hypothesis.side_lengths_m;
    if (sides.length !== 2 || sides.some((side) => !Number.isFinite(side) || side <= 0)) return [];
    const [short_m, long_m] = [...sides].sort((a, b) => a - b);
    return [{
      z_m: slice.z_m,
      long_m,
      short_m,
      source_point_row_id_count: slice.source_point_row_id_count,
      source_point_row_id_sample: [...slice.source_point_row_id_sample],
      source_provenance: {
        source_point_row_id_count: slice.source_point_row_id_count,
        source_point_row_id_sample: [...slice.source_point_row_id_sample],
        source_index_space: "derived_positions_row_index/1" as const,
        analysis_algorithm: analysis.algorithm.section_series,
      },
      note: "Черновая гипотеза системы; перед сохранением как эталон сверь с исходными точками. " +
        `Использовано строк: ${slice.source_point_row_id_count}; примеры строк: ${slice.source_point_row_id_sample.slice(0, 8).join(", ")}.`,
    }];
  });
  return suggestions.sort((a, b) => a.z_m - b.z_m);
}
