import assert from "node:assert/strict";
import test from "node:test";

import { api, waitForCloud } from "./api.ts";

test("canceling an import uses the cloud processing job endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let method = "";
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    method = init?.method || "GET";
    return { ok: true, json: async () => ({ cancel_requested: true }) } as Response;
  }) as typeof fetch;
  try {
    const result = await api.cancelJob("job / 1");
    assert.equal(requestedUrl, "/api/v1/jobs/job%20%2F%201/cancel");
    assert.equal(method, "POST");
    assert.equal(result.cancel_requested, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("resuming an interrupted import calls the cloud resume endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let method = "";
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    method = init?.method || "GET";
    return { ok: true, json: async () => ({ id: "cloud-1", status: "processing", import_job_id: "job-2" }) } as Response;
  }) as typeof fetch;
  try {
    const result = await api.resumeImport("cloud / 1");
    assert.equal(requestedUrl, "/api/v1/clouds/cloud%20%2F%201/resume");
    assert.equal(method, "POST");
    assert.equal(result.import_job_id, "job-2");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("cloud polling returns when an import was cancelled", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => ({
    ok: true,
    json: async () => ({ id: "cloud-1", status: "cancelled" }),
  }) as Response) as typeof fetch;
  try {
    const cloud = await waitForCloud("cloud-1");
    assert.equal(cloud.status, "cancelled");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rejecting a column group sends the review reason and matching tolerances", async () => {
  const originalFetch = globalThis.fetch;
  let url = "";
  let payload: any;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    url = String(input);
    payload = JSON.parse(String(init?.body));
    return { ok: true, json: async () => ({ action_id: "reject-1", changed: true }) } as Response;
  }) as typeof fetch;
  try {
    await api.rejectColumnType("group-1", "cloud-1", "different sections", 0.008, 0.02);
    assert.equal(url, "/api/v1/column-types/group-1/reject");
    assert.deepEqual(payload, {
      cloud_id: "cloud-1", note: "different sections", linear_tolerance_m: 0.008, relative_tolerance: 0.02,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("column type review preserves cloud context, thresholds and undo action", async () => {
  const originalFetch = globalThis.fetch;
  const calls: { url: string; body: any }[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), body: init?.body ? JSON.parse(String(init.body)) : null });
    return { ok: true, json: async () => ({ action_id: "action-1" }) } as Response;
  }) as typeof fetch;
  try {
    await api.columnTypes("cloud-1");
    await api.confirmColumnType("proposal-1", "cloud-1", "К1", 0.008, 0.02);
    await api.assignColumnType("column-1", "type-1");
    await api.undoColumnTypeAction("action-1");
    assert.equal(calls[0].url, "/api/v1/clouds/cloud-1/column-types");
    assert.deepEqual(calls[1].body, {
      cloud_id: "cloud-1", mark: "К1", linear_tolerance_m: 0.008, relative_tolerance: 0.02,
    });
    assert.equal(calls[2].body.type_id, "type-1");
    assert.equal(calls[3].url, "/api/v1/column-types/actions/action-1/undo");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("independent column annotations load and save against the frozen source snapshot", async () => {
  const originalFetch = globalThis.fetch;
  const calls: { url: string; method: string; body: any }[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), method: init?.method || "GET",
      body: init?.body ? JSON.parse(String(init.body)) : null });
    return { ok: true, json: async () => ({ annotations: [], revision: 1 }) } as Response;
  }) as typeof fetch;
  try {
    await api.columnAnnotations("cloud / 1");
    await api.columnAnnotationHistory("cloud / 1");
    await api.saveColumnAnnotation("cloud / 1", "column #1", {
      source_snapshot_sha256: "a".repeat(64), annotator: "reviewer", state: "unknown",
      reason_unknown: "occluded", note: "", physical_instance_id: null, type_label: null,
      shape_label: null, structural_role: "unknown", sides_m: null, measurement_source: null,
      z_measurements: [], visible_faces: [], hidden_faces: [], confidence: null,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(calls[0].url, "/api/v1/clouds/cloud%20%2F%201/column-annotations");
  assert.equal(calls[1].url, "/api/v1/clouds/cloud%20%2F%201/column-annotations/history");
  assert.equal(calls[2].url, "/api/v1/clouds/cloud%20%2F%201/column-annotations/column%20%231");
  assert.equal(calls[2].method, "POST");
  assert.equal(calls[2].body.source_snapshot_sha256, "a".repeat(64));
  assert.equal(calls[2].body.reason_unknown, "occluded");
});

test("structural plan PDF download includes scale and issue mode", async () => {
  const originalFetch = globalThis.fetch;
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;
  const originalDocument = globalThis.document;
  const requested: string[] = [];
  const downloaded: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requested.push(String(input));
    return {
      ok: true,
      blob: async () => new Blob(["pdf"]),
      headers: { get: () => null },
    } as Response;
  }) as typeof fetch;
  URL.createObjectURL = () => "blob:test";
  URL.revokeObjectURL = () => undefined;
  globalThis.document = {
    createElement: () => ({
      set href(_value: string) {},
      set download(value: string) { downloaded.push(value); },
      click: () => undefined,
    }),
  } as unknown as Document;

  try {
    await api.exportStructuralPlanPdf("cloud-1", "columns");
    await api.exportStructuralPlanPdf("cloud-1", "crane_girders", 200, "final");
  } finally {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    globalThis.document = originalDocument;
  }

  assert.deepEqual(requested, [
    "/api/v1/clouds/cloud-1/structural-plan.pdf?type=columns&scale=100&issue=final",
    "/api/v1/clouds/cloud-1/structural-plan.pdf?type=crane_girders&scale=200&issue=final",
  ]);
  assert.deepEqual(downloaded, ["plan-final-columns.pdf", "plan-final-crane_girders.pdf"]);
});
