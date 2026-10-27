import assert from "node:assert/strict";
import test from "node:test";

import { cameraViewFromLabel, canRenderPointColorMode, cloudPointCoverage, rcpDeclaredCountWarning, scannerModelLabel, progressPercent, resolvePointColorMode } from "./studioPresentation.ts";

test("cloud coverage distinguishes stored points from the full source scan", () => {
  assert.deepEqual(cloudPointCoverage({
    point_count: 576_820_490,
    ingested_count: 3_500_000,
    decimated: false,
    metadata: { decimated: true },
  }), {
    sourcePointCount: 576_820_490,
    storedPointCount: 3_500_000,
    sampled: true,
    label: "3 500 000 / 576 820 490",
  });
});

test("RCP metadata count differences are shown as unverified instead of trusted as source truth", () => {
  assert.equal(rcpDeclaredCountWarning({ recap_project: {
    selected_node: { declared_point_count: 295_836_062 },
    actual_source_point_count: 295_591_803,
    declared_point_count_difference: 244_259,
  } }), "Манифест RCP: 295 836 062 точек; связанный RCS: 295 591 803. Расхождение: 244 259 точек; число из манифеста не подтверждено.");
  assert.equal(rcpDeclaredCountWarning({ recap_project: {
    selected_node: { declared_point_count: 100 }, actual_source_point_count: 100,
  } }), null);
  assert.equal(rcpDeclaredCountWarning({}), null);
  assert.equal(rcpDeclaredCountWarning({ recap_project: {
    selected_node: { declared_point_count: 295_836_062 }, actual_source_point_count: 295_591_803,
  } }, "Манифест RCP указывает 295,836,062; reader прочитал 295,591,803 (разница +244,259)."), null);
});

test("scanner panel does not invent a FARO model or accuracy when metadata is absent", () => {
  assert.equal(scannerModelLabel({ metadata: {} }), "Модель сканера не указана");
  assert.equal(scannerModelLabel({ metadata: { scanner_model: "FARO Focus S350" } }), "FARO Focus S350");
});

test("idle progress is absent and active progress uses the live job fraction", () => {
  assert.equal(progressPercent(null), null);
  assert.equal(progressPercent(0), 0);
  assert.equal(progressPercent(Number.NaN), null);
  assert.equal(progressPercent(0.74), 74);
  assert.equal(progressPercent(1.2), 100);
});

test("saved camera labels restore a matching view preset and ignore unknown labels", () => {
  assert.equal(cameraViewFromLabel("TOP (ПЛАН)"), "top");
  assert.equal(cameraViewFromLabel("FRONT (ФАСАД)"), "front");
  assert.equal(cameraViewFromLabel("RIGHT (СБОКУ)"), "right");
  assert.equal(cameraViewFromLabel("3D ISO"), "iso");
  assert.equal(cameraViewFromLabel("FIT"), "fit");
  assert.equal(cameraViewFromLabel(undefined), null);
  assert.equal(cameraViewFromLabel("unknown"), null);
});

test("point display falls back to a mode the viewer can actually render", () => {
  const cloud = { has_color: false, has_intensity: true, metadata: { normals_available: true } };
  assert.equal(resolvePointColorMode("rgb", cloud), "height");
  assert.equal(resolvePointColorMode("intensity", cloud), "height");
  assert.equal(resolvePointColorMode("normals", cloud), "height");
  assert.equal(resolvePointColorMode("error", cloud), "height");
  assert.equal(resolvePointColorMode("height", cloud), "height");
});

test("RGB stays selected only when the source cloud carries color", () => {
  assert.equal(canRenderPointColorMode("rgb", { has_color: false }), false);
  assert.equal(canRenderPointColorMode("rgb", { has_color: true }), true);
  assert.equal(canRenderPointColorMode("height", null), false);
  assert.equal(canRenderPointColorMode("intensity", { has_color: true }), false);
  assert.equal(resolvePointColorMode("rgb", { has_color: true }), "rgb");
});
