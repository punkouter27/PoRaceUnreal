// node --test web/idle.test.mjs   (tests/test_web_idle.py runs it in pytest, locally and in CI)
import assert from "node:assert/strict";
import { test } from "node:test";
import { createIdleClock, IDLE_S, MAX_FRAME_S } from "./idle.js";

const run = (clock, seconds, fps = 60) => {
  let starts = 0;
  for (let i = 0; i < Math.round(seconds * fps); i++) if (clock.frame(1 / fps) === "start") starts++;
  return starts;
};

test("the thresholds are 30 s idle and 0.25 s per frame", () => {
  assert.equal(IDLE_S, 30);
  assert.equal(MAX_FRAME_S, 0.25);
});

test("demo mode starts once, after 30 s of normal frames", () => {
  const c = createIdleClock();
  assert.equal(run(c, 29.5), 0);
  assert.equal(c.demo, false);
  assert.equal(run(c, 1), 1);
  assert.equal(c.demo, true);
  assert.equal(run(c, 10), 0); // already running: no second start
});

test("a frame longer than 0.25 s is not idle time", () => {
  const c = createIdleClock();
  assert.equal(c.frame(45), null); // a 45 s frame (tab in the background) alone must not start demo mode
  assert.equal(c.frame(0.26), null);
  assert.equal(c.idleSeconds, 0);
  run(c, 20);
  assert.equal(c.frame(15), null); // 20 s + a 15 s hitch is still not 30 s of frames
  assert.equal(c.demo, false);
  assert.equal(c.frame(0.25), null); // exactly 0.25 s still counts
  assert.ok(Math.abs(c.idleSeconds - 20.25) < 1e-6);
  assert.equal(run(c, 10), 1);
});

test("input ends demo mode and restarts the clock", () => {
  const c = createIdleClock();
  run(c, 31);
  assert.equal(c.demo, true);
  assert.equal(c.input(), "stop");
  assert.equal(c.demo, false);
  assert.equal(c.idleSeconds, 0);
  assert.equal(c.input(), null);
  assert.equal(run(c, 29), 0);
});

test("non-finite or negative frame times are ignored", () => {
  const c = createIdleClock();
  for (const dt of [NaN, -1, Infinity, 0]) assert.equal(c.frame(dt), null);
  assert.equal(c.idleSeconds, 0);
});
