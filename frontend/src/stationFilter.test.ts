import assert from "node:assert/strict";
import { filterRegistrationStations } from "./stationFilter.ts";
import type { Cloud } from "./types.ts";

const stations = [
  { id: "one", name: "Симферополь — scans__faro_scan_029", source_format: "rcs", source_path: "C:\\project\\scan_029.rcs" },
  { id: "two", name: "Цех — scans__rt_11064", source_format: "e57", source_path: "D:\\archive\\scan_064.e57" },
] as Cloud[];

assert.deepEqual(filterRegistrationStations(stations, ""), stations, "an empty query preserves the full ordered list");
assert.deepEqual(filterRegistrationStations(stations, "FARO_SCAN_029").map(({ id }) => id), ["one"], "matches station names without case sensitivity");
assert.deepEqual(filterRegistrationStations(stations, "rt_11064").map(({ id }) => id), ["two"], "matches station IDs embedded in the name");
assert.deepEqual(filterRegistrationStations(stations, "E57").map(({ id }) => id), ["two"], "matches the source format");
assert.deepEqual(filterRegistrationStations(stations, "archive").map(({ id }) => id), ["two"], "matches the source path");
assert.deepEqual(filterRegistrationStations(stations, "not-found"), [], "returns an empty list when there is no match");

console.log("registration station filter: ok");
