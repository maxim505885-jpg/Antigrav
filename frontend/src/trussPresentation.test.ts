import assert from "node:assert/strict";
import { trussCompletenessBadge, trussDimensionSummary } from "./trussPresentation.ts";

const partial = {
  completeness: "partial",
  span_m: 16,
  height_m: 2,
  panels: 2,
  observed_panels: 2,
  missing_evidence: ["additional_vertical_posts"],
};

assert.deepEqual(trussCompletenessBadge(partial), {
  text: "неполная ферма",
  title: "Показаны только найденные стержни; недостающие не достраиваются. Не хватает evidence: additional_vertical_posts.",
});
assert.match(trussDimensionSummary(partial), /неполный кандидат, размеры только наблюдаемой части/);
assert.match(trussDimensionSummary(partial), /наблюдаемых стоек: 2/);
assert.equal(trussCompletenessBadge({ completeness: "candidate_complete" }), null);
