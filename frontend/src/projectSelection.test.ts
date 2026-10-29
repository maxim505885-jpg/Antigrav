import assert from "node:assert/strict";
import test from "node:test";

import { selectInitialProject } from "./projectSelection.ts";

const projects = [
  { id: "workshop_project", name: "Завод №1 (демо)", cloud_count: 5 },
  { id: "real_faro", name: "Симферополь — Лёгкое", cloud_count: 810 },
  { id: "small_validation", name: "Проверка", cloud_count: 2 },
];

test("fresh profile selects project with the most imported clouds instead of a demo", () => {
  assert.equal(selectInitialProject(projects)?.id, "real_faro");
});

test("an explicit saved project selection remains preferred", () => {
  assert.equal(selectInitialProject(projects, "workshop_project")?.id, "workshop_project");
});

test("missing saved selection falls back to the most populated project", () => {
  assert.equal(selectInitialProject(projects, "removed_project")?.id, "real_faro");
});

test("empty projects return null", () => {
  assert.equal(selectInitialProject([]), null);
});
