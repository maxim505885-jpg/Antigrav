import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_APPLY_ICP_REFINEMENT } from "./manualRegistrationPolicy.ts";

test("manual tie-point alignment does not refine with cloud ICP by default", () => {
  assert.equal(DEFAULT_APPLY_ICP_REFINEMENT, false);
});
