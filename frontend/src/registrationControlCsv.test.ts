import assert from "node:assert/strict";
import test from "node:test";
import { parseRegistrationControlsCsv } from "./registrationControlCsv.ts";

test("parses survey controls with semicolon separators and decimal commas", () => {
  assert.deepEqual(parseRegistrationControlsCsv([
    "label;source_x;source_y;source_z;target_x;target_y;target_z",
    "Марка 1;1,25;2,5;3;4,25;5,5;6",
    "Марка 2;7;8;9;10;11;12",
    "Марка 3;13;14;15;16;17;18",
  ].join("\r\n")), [
    { label: "Марка 1", source: ["1.25", "2.5", "3"], target: ["4.25", "5.5", "6"] },
    { label: "Марка 2", source: ["7", "8", "9"], target: ["10", "11", "12"] },
    { label: "Марка 3", source: ["13", "14", "15"], target: ["16", "17", "18"] },
  ]);
});

test("supports reordered columns, UTF-8 BOM, quoted delimiters, and empty lines", () => {
  const parsed = parseRegistrationControlsCsv([
    "\uFEFFtarget_z,label,source_y,target_x,source_z,target_y,source_x",
    '6,"Репер, север";A,2,4,3,5,1',
    "",
    "12,Репер 2,8,10,9,11,7",
    "18,Репер 3,14,16,15,17,13",
  ].join("\n"));
  assert.equal(parsed[0].label, "Репер, север;A");
  assert.deepEqual(parsed[0].source, ["1", "2", "3"]);
  assert.deepEqual(parsed[0].target, ["4", "5", "6"]);
  assert.equal(parsed.length, 3);
});

test("rejects missing headers, invalid coordinates, and fewer than three controls", () => {
  assert.throws(() => parseRegistrationControlsCsv("source_x,source_y,source_z\n1,2,3"), /заголовки/i);
  assert.throws(() => parseRegistrationControlsCsv([
    "label,source_x,source_y,source_z,target_x,target_y,target_z",
    "one,1,2,3,4,5,6",
    "two,7,8,9,10,11,12",
    "three,13,14,15,16,17,not-a-number",
  ].join("\n")), /строк/i);
  assert.throws(() => parseRegistrationControlsCsv([
    "label,source_x,source_y,source_z,target_x,target_y,target_z",
    "one,1,2,3,4,5,6",
    "two,7,8,9,10,11,12",
  ].join("\n")), /минимум три/i);
});

console.log("registration control CSV: ok");
