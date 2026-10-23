import assert from "node:assert/strict";
import test from "node:test";
import { RenderFpsSampler } from "./renderFps.ts";

test("measures the actual render loop rate over one-second windows", () => {
  const sampler = new RenderFpsSampler();
  assert.equal(sampler.sample(0), null);
  for (let frame = 1; frame < 60; frame += 1) {
    assert.equal(sampler.sample(frame * (1000 / 60)), null);
  }
  assert.equal(sampler.sample(1000), 60);
});

test("reports a slower renderer and restarts the sample window", () => {
  const sampler = new RenderFpsSampler();
  sampler.sample(5);
  for (let frame = 1; frame < 30; frame += 1) {
    assert.equal(sampler.sample(5 + frame * (1000 / 30)), null);
  }
  assert.equal(sampler.sample(1005), 30);
  assert.equal(sampler.sample(1010), null);
  assert.equal(sampler.sample(3005), 1);
});

test("resets on a non-monotonic clock and ignores invalid timestamps", () => {
  const sampler = new RenderFpsSampler();
  sampler.sample(100);
  assert.equal(sampler.sample(Number.NaN), null);
  assert.equal(sampler.sample(50), null);
  assert.equal(sampler.sample(1050), 1);
});
