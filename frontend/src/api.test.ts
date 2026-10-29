import assert from "node:assert/strict";
import test from "node:test";

import { api, waitForCloud } from "./api.ts";
import { detailText } from "./errorMessage.ts";

test("structured storage errors show both the headline and recovery guidance", () => {
  const message = detailText({ detail: { detail: {
    summary: "Недостаточно места.",
    message: "Освободите диск или выберите ограниченный импорт.",
    available_bytes: 100,
    required_bytes: 200,
  } } });
  assert.equal(message, "Недостаточно места. Освободите диск или выберите ограниченный импорт.");
});

test("unavailable storage preflight explains why a full RCP import did not start", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => ({
    ok: false,
    statusText: "Service Unavailable",
    json: async () => ({ detail: {
      summary: "Не удалось проверить хранилище данных.",
      storage_check: "unavailable",
      message: "Полный импорт RCP не запущен. Проверьте подключение и права доступа.",
    } }),
  }) as Response) as typeof fetch;
  try {
    await assert.rejects(
      api.importRcpPath("project-1", "C:/scans/plant.rcp", undefined, 0),
      (error: any) => {
        assert.equal(
          detailText(error),
          "Не удалось проверить хранилище данных. Полный импорт RCP не запущен. Проверьте подключение и права доступа.",
        );
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("learning manifest preview is read-only and export requires the reviewed content hash", async () => {
  const originalFetch = globalThis.fetch;
  const requested: Array<{ url: string; method: string; body?: any }> = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requested.push({
      url: String(input),
      method: init?.method || "GET",
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return { ok: true, json: async () => ({ manifest_sha256: "a".repeat(64) }) } as Response;
  }) as typeof fetch;
  try {
    await api.learningManifestPreview("project / 1");
    await api.exportLearningManifest("project / 1", "a".repeat(64));
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(requested, [
    { url: "/api/v1/projects/project%20%2F%201/learning-manifest/preview", method: "GET", body: undefined },
    {
      url: "/api/v1/projects/project%20%2F%201/learning-manifests/export",
      method: "POST",
      body: { confirmed: true, expected_manifest_sha256: "a".repeat(64) },
    },
  ]);
});

test("project column reference summary uses project-scoped independent labels", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = String(input);
    return { ok: true, json: async () => ({ schema: "scan.column-reference-types/1", groups: [] }) } as Response;
  }) as typeof fetch;
  try {
    await api.projectColumnReferenceTypes("project / 1");
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedUrl, "/api/v1/projects/project%20%2F%201/column-reference-types");
});

test("independent registration controls use the separate validation endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let body: any;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    body = JSON.parse(String(init?.body));
    return { ok: true, json: async () => ({ status: "controls_evaluated", criterion_passed: true }) } as Response;
  }) as typeof fetch;
  try {
    await api.evaluateRegistrationControls(
      "source 1", "target 2", [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
      [{ source_point: [0, 0, 0], target_point: [0, 0, 0], label: "Control A" }], true,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedUrl, "/api/v1/registration/evaluate-controls");
  assert.deepEqual(body, {
    source_cloud_id: "source 1",
    target_cloud_id: "target 2",
    matrix_4x4: [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
    controls: [{ source_point: [0, 0, 0], target_point: [0, 0, 0], label: "Control A" }],
    independent_of_fit: true,
    acceptance_rmse_mm: 10,
  });
});

test("plain API error details remain readable", () => {
  assert.equal(detailText({ detail: { detail: "Import rejected" } }), "Import rejected");
  assert.equal(detailText({ detail: "Server unavailable" }), "Server unavailable");
});

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

test("RCP batch import sends project path and decodes station cloud response", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let body: any;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    body = JSON.parse(String(init?.body));
    return { ok: true, json: async () => ({
      project_id: "project-1", project_file: "plant.rcp", project_sha256: "abc",
      import_job_id: "job-1", node_count: 1,
      stations: [{ node_id: "station-1", node_name: "Station 1", cloud: { id: "cloud-1" } }],
    }) } as Response;
  }) as typeof fetch;
  try {
    const result = await api.importRcpPath("project / 1", "C:/scans/plant.rcp", undefined, 0);
    assert.equal(requestedUrl, "/api/v1/projects/project%20%2F%201/rcp/import-path");
    assert.deepEqual(body, { path: "C:/scans/plant.rcp", max_points: 0 });
    assert.equal(result.import_job_id, "job-1");
    assert.equal(result.stations[0].cloud.id, "cloud-1");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("single cloud import sends an explicit full-resolution request", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let body: any;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    body = JSON.parse(String(init?.body));
    return { ok: true, json: async () => ({ id: "cloud-1" }) } as Response;
  }) as typeof fetch;
  try {
    await api.importPath("project-1", "C:/scans/station.rcs", undefined, 0);
    assert.equal(requestedUrl, "/api/v1/projects/project-1/clouds/import-path");
    assert.deepEqual(body, { path: "C:/scans/station.rcs", max_points: 0 });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("source evidence audit requests the project cloud endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = String(input);
    return { ok: true, json: async () => ({
      cloud_id: "cloud / 1", candidate_count: 0,
      status_counts: { consistent: 0, mismatch: 0, unverifiable: 0 },
      status_counts_by_class: {},
      source_snapshot_counts: { current: 0, missing: 1, stale: 0, unchecked: 0 },
      attention_count: 0, accuracy_status: "not_measured", candidates: [],
    }) } as Response;
  }) as typeof fetch;
  try {
    const result = await api.sourceEvidenceAudit("cloud / 1");
    assert.equal(requestedUrl, "/api/v1/clouds/cloud%20%2F%201/source-evidence-audit");
    assert.equal(result.accuracy_status, "not_measured");
    assert.equal(result.source_snapshot_counts.missing, 1);
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

test("resuming a failed RCP batch calls the project job resume endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let method = "";
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    method = init?.method || "GET";
    return { ok: true, json: async () => ({ id: "job-1", type: "rcp_batch_ingest", status: "queued" }) } as Response;
  }) as typeof fetch;
  try {
    const result = await api.resumeRcpBatchJob("project / 1", "job / 1");
    assert.equal(requestedUrl, "/api/v1/projects/project%20%2F%201/jobs/job%20%2F%201/resume");
    assert.equal(method, "POST");
    assert.equal(result.status, "queued");
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

test("native ReCap export sends only the selected source scans to DeCap", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let payload: any;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    payload = JSON.parse(String(init?.body));
    return {
      ok: true,
      json: async () => ({ status: "created_by_autodesk_decap", package_verified: true, source_files_copied_for_decap: true, source_cache_path: null, rcp_path: "Hall/Hall.rcp" }),
    } as Response;
  }) as typeof fetch;
  try {
    const result = await api.exportNativeRecapProject("Hall", [
      { name: "Station 01", path: "C:/scans/station-01.rcs", point_count: 1200 },
    ]);
    assert.equal(requestedUrl, "/api/v1/registration/export-rcp-project");
    assert.deepEqual(payload, {
      project_name: "Hall",
      stations: [{ name: "Station 01", path: "C:/scans/station-01.rcs", point_count: 1200 }],
    });
    assert.equal(result.package_verified, true);
    assert.equal(result.source_files_copied_for_decap, true);
    assert.equal(result.source_cache_path, null);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("column surface tracking requests a source-linked review analysis", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let method = "";
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    method = init?.method || "GET";
    return { ok: true, json: async () => ({ candidate_id: "column-1", review_required: true }) } as Response;
  }) as typeof fetch;
  try {
    const result = await api.analyzeColumnSurfaceTracks("column / 1");
    assert.equal(requestedUrl, "/api/v1/elements/column%20%2F%201/surface-track-analysis");
    assert.equal(method, "POST");
    assert.equal(result.candidate_id, "column-1");
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

test("independent element role annotations use versioned cloud-scoped endpoints", async () => {
  const originalFetch = globalThis.fetch;
  const calls: { url: string; method: string; body: any }[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), method: init?.method || "GET",
      body: init?.body ? JSON.parse(String(init.body)) : null });
    return { ok: true, json: async () => ({ annotations: [], revision: 1 }) } as Response;
  }) as typeof fetch;
  try {
    await api.elementAnnotations("cloud / 1");
    await api.elementAnnotationHistory("cloud / 1");
    await api.saveElementAnnotation("cloud / 1", "beam #1", {
      source_snapshot_sha256: "b".repeat(64), annotator: "reviewer", state: "labeled",
      physical_instance_id: "B-01", class_label: "beam", role_label: "crane_girder",
      type_label: "KB-1", reason: "", note: "checked",
    });
    await api.exportElementAnnotations("cloud / 1");
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(calls[0].url, "/api/v1/clouds/cloud%20%2F%201/element-annotations");
  assert.equal(calls[1].url, "/api/v1/clouds/cloud%20%2F%201/element-annotations/history");
  assert.equal(calls[2].url, "/api/v1/clouds/cloud%20%2F%201/element-annotations/beam%20%231");
  assert.equal(calls[2].method, "POST");
  assert.equal(calls[2].body.role_label, "crane_girder");
  assert.equal(calls[3].url, "/api/v1/clouds/cloud%20%2F%201/element-annotations/export");
});

test("project activity is loaded from the project jobs API", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = String(input);
    return { ok: true, json: async () => [{ id: "job-1", type: "recognize", status: "succeeded" }] } as Response;
  }) as typeof fetch;
  try {
    const jobs = await api.projectJobs("shop / 1");
    assert.equal(jobs[0].id, "job-1");
    assert.equal(jobs[0].status, "succeeded");
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedUrl, "/api/v1/projects/shop%20%2F%201/jobs");
});

test("recognition evaluation submits independent physical references to the cloud-scoped endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let requestUrl = "";
  let requestBody: any = null;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestUrl = String(input);
    requestBody = JSON.parse(String(init?.body));
    return { ok: true, json: async () => ({ overall_precision: 0.5, overall_recall: 0.4, holdout_status: "not_verified" }) } as Response;
  }) as typeof fetch;
  try {
    const report = await api.evaluateRecognition("cloud / 1", {
      source_snapshot_sha256: "c".repeat(64), reference_set_id: "pilot-ref-1",
      reference_origin: "independent_manual", reference_kind: "field_measurement", annotator: "engineer",
      reference_elements: [{ physical_instance_id: "C-01", class_name: "column",
        bbox: { min: [0, 0, 0], max: [1, 1, 5] } }],
    });
    assert.equal(report.holdout_status, "not_verified");
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestUrl, "/api/v1/clouds/cloud%20%2F%201/recognition-evaluation");
  assert.equal(requestBody.reference_elements[0].physical_instance_id, "C-01");
  assert.equal(requestBody.reference_origin, "independent_manual");
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

test("full SPDS album downloads the draft ZIP endpoint", async () => {
  const originalFetch = globalThis.fetch;
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;
  const originalDocument = globalThis.document;
  let requestedUrl = "";
  let downloadedName = "";
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = String(input);
    return { ok: true, blob: async () => new Blob(["zip"]), headers: { get: () => null } } as Response;
  }) as typeof fetch;
  URL.createObjectURL = () => "blob:test";
  URL.revokeObjectURL = () => undefined;
  globalThis.document = {
    createElement: () => ({
      set href(_value: string) {},
      set download(value: string) { downloadedName = value; },
      click: () => undefined,
    }),
  } as unknown as Document;
  try {
    await api.exportSpdsAlbum("cloud / 1");
  } finally {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    globalThis.document = originalDocument;
  }
  assert.equal(requestedUrl, "/api/v1/clouds/cloud%20%2F%201/spds-album.zip");
  assert.equal(downloadedName, "spds-album-draft.zip");
});

test("global FGR registration posts station IDs and preserves preliminary status", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let requestBody: any = null;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    requestBody = JSON.parse(String(init?.body));
    return {
      ok: true,
      json: async () => ({ status: "candidate", accuracy_status: "not_measured",
        method: "open3d_fgr_point_to_plane_icp", source_cloud_id: "A/1", target_cloud_id: "B/1",
        matrix_4x4: [], world_matrix_4x4: null, coordinate_frame: {}, rmse_mm: 130,
        inlier_fraction: 0.8, optimizer_convergence: "not_exposed_by_open3d_result",
        holdout: { status: "evaluated", rmse_mm: 145, inlier_count: 4000,
          source_sample_count: 5000, target_sample_count: 5000,
          inlier_fraction: 0.8, is_disjoint_from_fit: true } }),
    } as Response;
  }) as typeof fetch;
  try {
    const result = await api.matchCloudsGlobalFgrIcp("A/1", "B/1", 5000, 42, 0.25);
    assert.equal(result.status, "candidate");
    assert.equal(result.accuracy_status, "not_measured");
    assert.equal(result.method, "open3d_fgr_point_to_plane_icp");
    assert.equal(result.holdout.status, "evaluated");
    assert.equal(result.holdout.is_disjoint_from_fit, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requestedUrl, "/api/v1/registration/global-match");
  assert.deepEqual(requestBody, {
    source_cloud_id: "A/1", target_cloud_id: "B/1", sample_points: 5000, sample_seed: 42, max_correspondence_distance_m: 0.25,
  });
});
