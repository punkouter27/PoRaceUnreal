// Attract (demo) mode clock for the policy viewer. Only frames of at most MAX_FRAME_S count as idle time, so a
// background tab, a stalled frame or a brain download never starts demo mode on its own. Tested by web/idle.test.mjs
// (run by tests/test_web_idle.py). The Unreal game has the same rule in URaceShowcaseConfig (MaxIdleFrameSeconds).
export const IDLE_S = 30;
export const MAX_FRAME_S = 0.25;
export const DEMO_DWELL_S = 8; // demo mode shows each recorded race this long

export function createIdleClock({ idleS = IDLE_S, maxFrameS = MAX_FRAME_S } = {}) {
  let idle = 0;
  let demo = false;
  return {
    get idleSeconds() {
      return idle;
    },
    get demo() {
      return demo;
    },
    /** One rendered frame of `dt` seconds. Returns "start" on the frame demo mode begins, else null. */
    frame(dt) {
      if (Number.isFinite(dt) && dt > 0 && dt <= maxFrameS) idle += dt;
      if (!demo && idle >= idleS) {
        demo = true;
        return "start";
      }
      return null;
    },
    /** Keyboard, pointer, wheel, touch or gamepad input. Returns "stop" when it ended demo mode, else null. */
    input() {
      const was = demo;
      idle = 0;
      demo = false;
      return was ? "stop" : null;
    },
  };
}
