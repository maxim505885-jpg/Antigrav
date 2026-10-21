import assert from "node:assert/strict";
import test from "node:test";

import { filterReferenceElements, filterReviewElements, type ReferenceFilter, type ReviewFilter } from "./reviewQueue.ts";

const elements = [
  { id: "new", review_status: "unreviewed", dimensions: {} },
  { id: "conflict", review_status: "unreviewed", dimensions: { review_conflict_with: ["manual-1"] } },
  { id: "confirmed", review_status: "confirmed", dimensions: {} },
  { id: "corrected", review_status: "corrected", dimensions: {} },
  { id: "rejected", review_status: "rejected", dimensions: {} },
];

test("review queue filters pending, conflicts, checked, rejected and all elements", () => {
  const expected: Record<ReviewFilter, string[]> = {
    pending: ["new", "conflict"],
    conflicts: ["conflict"],
    checked: ["confirmed", "corrected"],
    rejected: ["rejected"],
    all: ["new", "conflict", "confirmed", "corrected", "rejected"],
  };

  for (const [filter, ids] of Object.entries(expected) as [ReviewFilter, string[]][]) {
    assert.deepEqual(filterReviewElements(elements, filter).map((element) => element.id), ids);
  }
});

test("independent reference queue separates unlabelled, labelled, unknown and excluded columns", () => {
  const candidates = [
    { id: "a", class_name: "column" }, { id: "b", class_name: "column" },
    { id: "c", class_name: "column" }, { id: "d", class_name: "beam" },
  ];
  const states = { b: "labeled", c: "unknown" };
  const expected: Record<ReferenceFilter, string[]> = {
    all: ["a", "b", "c", "d"], needs_reference: ["a"], labeled: ["b"], unknown: ["c"], excluded: [],
  };
  for (const [filter, ids] of Object.entries(expected) as [ReferenceFilter, string[]][]) {
    assert.deepEqual(filterReferenceElements(candidates, filter, states).map((item) => item.id), ids);
  }
  assert.deepEqual(filterReferenceElements([...candidates, { id: "d", class_name: "column" }], "excluded", { d: "excluded" }).map((item) => item.id), ["d"]);
});
