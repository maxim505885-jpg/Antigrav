import assert from "node:assert/strict";
import test from "node:test";
import { columnAnnotationQueueStats, nextPendingColumn } from "./columnAnnotationQueue.ts";
import type { ColumnAnnotation } from "./api.ts";
import type { Element } from "./types.ts";

function column(id: string): Element {
  return { id, class_name: "column" } as Element;
}

function annotation(element_id: string, state: ColumnAnnotation["state"]): Pick<ColumnAnnotation, "element_id" | "state"> {
  return { element_id, state };
}

test("queue moves forward by stable ID and wraps to the next pending column", () => {
  const columns = [column("c"), column("a"), column("b")];
  assert.equal(nextPendingColumn(columns, [], "a")?.id, "b");
  assert.equal(nextPendingColumn(columns, [], "c")?.id, "a");
});

test("queue skips labeled, unknown, and excluded columns", () => {
  const columns = [column("a"), column("b"), column("c"), column("d")];
  const annotations = [annotation("b", "labeled"), annotation("c", "unknown"), annotation("d", "excluded")];
  assert.equal(nextPendingColumn(columns, annotations, "a"), null);
  assert.deepEqual(columnAnnotationQueueStats(columns, annotations), {
    total: 4, reviewed: 3, pending: 1, labeled: 1, unknown: 1, excluded: 1,
  });
});

test("queue treats a missing annotation as pending and never reselects the current item", () => {
  const columns = [column("a"), column("b")];
  assert.equal(nextPendingColumn(columns, [annotation("a", "labeled")], "a")?.id, "b");
  assert.equal(nextPendingColumn(columns, [], "a")?.id, "b");
});
