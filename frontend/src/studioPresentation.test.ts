import assert from "node:assert/strict";
import test from "node:test";

import { cameraViewFromLabel, cloudPointCoverage, scannerModelLabel, progressPercent } from "./studioPresentation.ts";

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
