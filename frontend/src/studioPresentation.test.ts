import assert from "node:assert/strict";
import test from "node:test";

import { cameraViewFromLabel, canOfferRcpBatchResume, canRenderPointColorMode, cloudPointCoverage, rcpDeclaredCountWarning, rcpTransformWarning, scannerModelLabel, progressPercent, resolvePointColorMode } from "./studioPresentation.ts";

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
  } }), "RCP NumPoints: 295 836 062; SCAN прочитал из связанного RCS: 295 591 803; разница: 244 259 точек. Смысл NumPoints не подтверждён; сама разница не доказывает потерю точек.");
  assert.equal(rcpDeclaredCountWarning({ recap_project: {
    selected_node: { declared_point_count: 100 }, actual_source_point_count: 100,
  } }), null);
  assert.equal(rcpDeclaredCountWarning({}), null);
  assert.equal(rcpDeclaredCountWarning({ recap_project: {
    selected_node: { declared_point_count: 295_836_062 }, actual_source_point_count: 295_591_803,
  } }, "Манифест RCP указывает 295,836,062; reader прочитал 295,591,803 (разница +244,259)."), null);
});

test("RCP point-count warning shows recorded import settings without claiming they caused the difference", () => {
  const warning = rcpDeclaredCountWarning({ recap_project: {
    selected_node: {
      declared_point_count: 1000,
      source_import: {
        noise_filter_level: "MEDIUM",
        intensity_clip_min: "0",
        intensity_clip_max: "100",
        decimation_density: "7",
      },
    },
    actual_source_point_count: 800,
  } });

  assert.equal(warning, "RCP NumPoints: 1 000; SCAN прочитал из связанного RCS: 800; разница: 200 точек. Смысл NumPoints не подтверждён; сама разница не доказывает потерю точек. В RCP записаны: фильтр помех MEDIUM; интенсивность 0–100; density=7 (единица не установлена). Эти параметры могут влиять на число точек при создании RCS; причина этого расхождения не доказана.");
});

test("RCP point-count warning explains Autodesk's E57 duplicate-point filtering only for E57 sources", () => {
  const e57Warning = rcpDeclaredCountWarning({ recap_project: {
    selected_node: {
      declared_point_count: 1000,
      source_import: { raw_scan_path: "station.e57" },
    },
    actual_source_point_count: 800,
  } });
  assert.match(e57Warning || "", /E57.*близкие эквивалентные точки.*даже при decimation=0/);
  assert.match(e57Warning || "", /возможный фактор.*вклад.*не измерен/);

  const otherWarning = rcpDeclaredCountWarning({ recap_project: {
    selected_node: {
      declared_point_count: 1000,
      source_import: { raw_scan_path: "station.las" },
    },
    actual_source_point_count: 800,
  } });
  assert.doesNotMatch(otherWarning || "", /E57.*близкие эквивалентные точки/);
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

test("unapplied RCP node poses are visible as unverified registration state", () => {
  assert.equal(rcpTransformWarning({ recap_project: {
    transform_applied: false,
    selected_node: { registered: false, translation: [30.8, -68.4, 3.4], rotation: [0, 0, 81.5] },
  } }), "Поза узла RCP сохранена, но не применена. Зарегистрировано в ReCap: нет; общая система координат не подтверждена.");
  assert.equal(rcpTransformWarning({ recap_project: { transform_applied: true, selected_node: { registered: true } } }), null);
  assert.equal(rcpTransformWarning({ recap_project: { selected_node: { registered: false } } }), null);
  assert.equal(rcpTransformWarning({}), null);
});

test("RCP batch resume is hidden when all project clouds are already ready", () => {
  assert.equal(canOfferRcpBatchResume([]), false);
  assert.equal(canOfferRcpBatchResume([{ status: "ready" }, { status: "ready" }]), false);
  assert.equal(canOfferRcpBatchResume([{ status: "ready" }, { status: "failed" }]), true);
  assert.equal(canOfferRcpBatchResume([{ status: "ready" }, { status: "processing" }]), true);
});
