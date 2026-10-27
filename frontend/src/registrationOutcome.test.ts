import assert from "node:assert/strict";
import test from "node:test";
import { registrationOutcome } from "./registrationOutcome.ts";

test("does not call an unconverged ICP run a successful registration", () => {
  assert.deepEqual(registrationOutcome({ converged: false, rmse_mm: 4.2 }), {
    state: "not_converged",
    label: "Не сошлось",
    detail: "Остаток ICP не является оценкой точности регистрации.",
  });
});

test("keeps missing residual distinct from a zero-error result", () => {
  assert.equal(registrationOutcome({ converged: true, rmse_mm: null }).state, "no_residual");
});

test("marks a converged ICP residual above ten millimetres for review", () => {
  assert.equal(registrationOutcome({ converged: true, rmse_mm: 10.01 }).state, "above_threshold");
});

test("does not turn a low ICP residual into physical acceptance", () => {
  assert.equal(registrationOutcome({ converged: true, rmse_mm: 1.2 }).state, "review_required");
});
