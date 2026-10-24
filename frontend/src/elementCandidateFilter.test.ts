import assert from "node:assert/strict";
import { filterElementCandidates } from "./elementCandidateFilter.ts";
import type { Element } from "./types.ts";

const element = (id: string, class_name: string, role_label = "") => ({
  id,
  class_name,
  dimensions: { role_label },
}) as Element;

const candidates = [
  element("truss-001", "truss"),
  element("beam-002", "beam", "Подкрановая балка"),
  element("brace-003", "brace", "Связь"),
];

assert.deepEqual(
  filterElementCandidates(candidates, "TRUSS-00", "all").map(({ id }) => id),
  ["truss-001"],
  "search is case-insensitive and matches IDs",
);
assert.deepEqual(
  filterElementCandidates(candidates, "ферма", "all").map(({ id }) => id),
  ["truss-001"],
  "search matches the Russian class label even when no role label is stored",
);
assert.deepEqual(
  filterElementCandidates(candidates, "подкрановая", "all").map(({ id }) => id),
  ["beam-002"],
  "search also matches the candidate's role label",
);
assert.deepEqual(
  filterElementCandidates(candidates, "", "beam").map(({ id }) => id),
  ["beam-002"],
  "class filter is independent from text search",
);
assert.deepEqual(filterElementCandidates(candidates, "нет такого", "all"), []);
assert.deepEqual(filterElementCandidates(candidates, "", "all"), candidates);

console.log("element candidate filtering: ok");
