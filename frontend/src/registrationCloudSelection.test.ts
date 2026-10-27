import assert from "node:assert/strict";
import { defaultRegistrationCloudIds } from "./registrationCloudSelection.ts";
import type { Cloud } from "./types.ts";

function cloud(id: string, source_format: string, decimated = false): Cloud {
  return { id, name: id, source_format, decimated } as Cloud;
}

assert.deepEqual(
  defaultRegistrationCloudIds([
    cloud("merged", "ply"),
    { ...cloud("validation", "rcs", true), name: "Live validation RCS" },
    { ...cloud("station-a", "rcs"), name: "Workshop 1.rcs" },
    { ...cloud("station-b", "rcs", true), name: "Workshop 2.rcs sample" },
  ]),
  { sourceId: "station-a", targetId: "station-b" },
  "the workshop scan pair should be preferred over the merged project cloud and unrelated validation scan",
);

assert.deepEqual(
  defaultRegistrationCloudIds([
    { ...cloud("station-a", "rcs"), name: "Workshop 1.rcs" },
    { ...cloud("station-b", "rcs"), name: "Workshop 2.rcs" },
  ], "station-b"),
  { sourceId: "station-b", targetId: "station-a" },
  "a selected full-resolution FARO station should be kept as the moving cloud",
);

assert.deepEqual(
  defaultRegistrationCloudIds([cloud("cloud-a", "ply"), cloud("cloud-b", "e57")]),
  { sourceId: "cloud-a", targetId: "cloud-b" },
  "other projects should retain a ready-cloud fallback",
);

console.log("registration cloud selection: ok");
