import assert from "node:assert/strict";
import test from "node:test";
import { recognitionReviewState } from "./recognitionReviewState.ts";

test("shows green-check text only for independently labeled elements", () => {
  assert.deepEqual(recognitionReviewState("labeled"), { state: "labeled", label: "✓ Размечено" });
  assert.deepEqual(recognitionReviewState("unknown"), { state: "unknown", label: "? Неизвестно" });
  assert.deepEqual(recognitionReviewState("excluded"), { state: "excluded", label: "Исключено" });
});

test("missing, pending and unexpected states remain pending", () => {
  for (const state of [undefined, null, "pending", "confirmed", "auto-classified"]) {
    assert.deepEqual(recognitionReviewState(state), {
      state: "pending",
      label: "Ожидает независимой проверки",
    });
  }
});
