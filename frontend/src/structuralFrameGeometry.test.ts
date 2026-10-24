import test from "node:test";
import assert from "node:assert/strict";
import { elementBoxLinePositions } from "./structuralFrameGeometry.ts";

test("elementBoxLinePositions extracts 24 vertices (72 floats) for a single oriented box", () => {
  const elements = [
    {
      id: "col-1",
      class_name: "column",
      geometry: {
        kind: "oriented_box",
        center: [10, 20, 5],
        sizes: { length: 2, thickness: 1, height: 4 },
        rotation_z: 0,
      },
    },
  ];

  const pos = elementBoxLinePositions(elements, "column", [0, 0, 0]);
  assert.equal(pos.length, 72); // 12 edges * 2 points * 3 floats = 72
  assert.equal(pos.constructor.name, "Float32Array");
});

test("elementBoxLinePositions filters by class name correctly", () => {
  const elements = [
    {
      id: "col-1",
      class_name: "column",
      bbox: { min: [0, 0, 0], max: [1, 1, 3] },
    },
    {
      id: "beam-1",
      class_name: "beam",
      bbox: { min: [0, 0, 3], max: [6, 1, 3.5] },
    },
  ];

  const colPos = elementBoxLinePositions(elements, "column", [0, 0, 0]);
  assert.equal(colPos.length, 72);

  const beamPos = elementBoxLinePositions(elements, "beam", [0, 0, 0]);
  assert.equal(beamPos.length, 72);

  const allPos = elementBoxLinePositions(elements, "all", [0, 0, 0]);
  assert.equal(allPos.length, 144);
});

test("legacy local-frame element boxes stay aligned with the cloud preview", () => {
  const elements = [{
    id: "legacy-column",
    class_name: "column",
    source: "structural_grid",
    metadata: {},
    bbox: { min: [1, 2, 0], max: [2, 3, 4] },
  }];

  const pos = elementBoxLinePositions(elements, "column", [100, 200, 300]);
  assert.equal(pos.length, 72);
  assert.equal(Math.min(...pos.filter((_, i) => i % 3 === 0)), 1);
  assert.equal(Math.max(...pos.filter((_, i) => i % 3 === 0)), 2);
});

test("explicit world-frame element boxes are translated into cloud-local coordinates", () => {
  const elements = [{
    id: "new-column",
    class_name: "column",
    source: "geometric",
    metadata: { bbox_coordinate_frame: "source_cloud_world" },
    bbox: { min: [101, 202, 300], max: [102, 203, 304] },
  }];

  const pos = elementBoxLinePositions(elements, "column", [100, 200, 300]);
  assert.equal(Math.min(...pos.filter((_, i) => i % 3 === 0)), 1);
  assert.equal(Math.max(...pos.filter((_, i) => i % 3 === 0)), 2);
});
