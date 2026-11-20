"""The stroller's skill ladder on CPU MuJoCo with an exported brain, through racelib.stroller.StrollerRacer (the race's
own loop), so a pass here is a pass in the race's code path.

    uv run --no-project --python 3.12 --with mujoco==4.0.0 --with onnxruntime --with numpy python stroller/sim.py ladder --brain models/brains/stroller_roll.onnx [--impratio 1]

Tests (10 seeds each unless noted; a seed = random start heading and a small random push off the line):
  hold still      command 0 for 10 s: drifts < 0.3 m, never tips
  straight        1.0 / 1.5 / 2.0 m/s from standstill: |mean speed - command| < 0.15 m/s over the last 3 s of 8 s
  turn            1.0 m/s with +-0.8 rad/s: |mean yaw rate - command| < 0.15 over the last 3 s of 8 s
  reverse         -0.5 m/s: |mean speed - command| < 0.15
  graduation      100 seeds x 20 s of race-range commands (1.0-2.0 m/s, yaw +-1.0, a change every 2-6 s): pass = never
                  tips and mean |speed error| + 0.5 |yaw-rate error| < 0.25; need 90
Prints one line per test and a summary; exit 0 when every test passes.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from go2.sim import brain  # noqa: E402
from racelib.stroller import StrollerRacer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
SCENE = Path(__file__).resolve().parent / "assets" / "scene_stroller.xml"
DT = 0.004


def make(impratio):
    m = mujoco.MjModel.from_xml_path(str(SCENE))
    m.opt.impratio = impratio
    return m, mujoco.MjData(m)


def episode(m, d, racer, commands, seconds, seed, push=True):
    """commands(t) -> (vx, wz). Returns per-step arrays (t, vx, wz, cmd vx, cmd wz) and whether it ever tipped."""
    rng = np.random.default_rng(seed)
    mujoco.mj_resetData(m, d)
    racer.spawn = (0.0, 0.0, racer.home_height)
    racer.spawn_yaw = float(rng.uniform(-math.pi, math.pi))
    racer.reset_to_spawn()
    if push:
        d.qvel[racer.root_v + 1] = float(rng.uniform(-0.3, 0.3))
    tipped = False
    rows = []
    for k in range(int(seconds / DT)):
        t = k * DT
        vx, wz = commands(t)
        racer.target[:] = (vx, 0.0, wz)
        racer.update_state()
        racer.control()
        mujoco.mj_step(m, d)
        if racer.up_z() < 0.5:
            tipped = True
        lv = d.sensordata[racer.adr_linvel : racer.adr_linvel + 3]
        gz = d.sensordata[racer.adr_gyro + 2]
        rows.append((t, float(lv[0]), float(gz), float(racer.cmd[0]), float(racer.cmd[2])))
    return np.array(rows), tipped


def tail_mean(rows, col, secs):
    return float(rows[rows[:, 0] >= rows[-1, 0] - secs][:, col].mean())


def run_ladder(brain_path, impratio, seeds=10, grad_seeds=100):
    m, d = make(impratio)
    card = json.loads((ROOT / "training" / "characters" / "stroller.json").read_text())
    racer = StrollerRacer(m, d, "", card, brain(brain_path))
    results = []

    def test(name, need, outcomes, detail):
        passes = sum(outcomes)
        results.append(
            {
                "test": name,
                "passes": passes,
                "of": len(outcomes),
                "need": need,
                "detail": detail,
                "pass": passes >= need,
            }
        )
        print(f"{name:28s} {passes:3d}/{len(outcomes):<3d} (need {need:3d})  {detail}", flush=True)

    out, drift = [], []
    for s in range(seeds):
        rows, tipped = episode(m, d, racer, lambda t: (0.0, 0.0), 10.0, s)
        dd = math.hypot(*racer.pos())
        drift.append(dd)
        out.append(not tipped and dd < 0.3)
    test("hold still 10 s", seeds, out, f"max drift {max(drift):.2f} m")

    for v in (1.0, 1.5, 2.0):
        out, errs = [], []
        for s in range(seeds):
            rows, tipped = episode(m, d, racer, lambda t, v=v: (v, 0.0), 8.0, 100 + s)
            e = abs(tail_mean(rows, 1, 3.0) - v)
            errs.append(e)
            out.append(not tipped and e < 0.15)
        test(
            f"straight {v:.1f} m/s",
            math.ceil(0.9 * seeds),
            out,
            f"mean err {np.mean(errs):.3f} m/s, worst {max(errs):.3f}",
        )

    for w in (0.8, -0.8):
        out, errs = [], []
        for s in range(seeds):
            rows, tipped = episode(m, d, racer, lambda t, w=w: (1.0, w), 8.0, 200 + s)
            e = abs(tail_mean(rows, 2, 3.0) - w)
            errs.append(e)
            out.append(not tipped and e < 0.15)
        test(
            f"turn {w:+.1f} rad/s at 1 m/s",
            math.ceil(0.9 * seeds),
            out,
            f"mean err {np.mean(errs):.3f} rad/s, worst {max(errs):.3f}",
        )

    out, errs = [], []
    for s in range(seeds):
        rows, tipped = episode(m, d, racer, lambda t: (-0.5, 0.0), 8.0, 300 + s)
        e = abs(tail_mean(rows, 1, 3.0) + 0.5)
        errs.append(e)
        out.append(not tipped and e < 0.15)
    test("reverse 0.5 m/s", math.ceil(0.9 * seeds), out, f"mean err {np.mean(errs):.3f} m/s")

    out, errs, tips = [], [], 0
    for s in range(grad_seeds):
        rng = np.random.default_rng(1000 + s)
        switches, t, cmds = [], 0.0, []
        while t < 20.0:
            switches.append(t)
            cmds.append((float(rng.uniform(1.0, 2.0)), float(rng.uniform(-1.0, 1.0)) if rng.uniform() < 0.7 else 0.0))
            t += float(rng.uniform(2.0, 6.0))

        def cmd(tt, switches=switches, cmds=cmds):
            i = max(k for k, s0 in enumerate(switches) if s0 <= tt)
            return cmds[i]

        rows, tipped = episode(m, d, racer, cmd, 20.0, 1000 + s)
        settled = rows[rows[:, 0] > 1.0]
        e = float(np.mean(np.abs(settled[:, 1] - settled[:, 3])) + 0.5 * np.mean(np.abs(settled[:, 2] - settled[:, 4])))
        errs.append(e)
        tips += tipped
        out.append(not tipped and e < 0.25)
    test("graduation (race range)", math.ceil(0.9 * grad_seeds), out, f"mean err {np.mean(errs):.3f}, tipped {tips}")

    ok = all(r["pass"] for r in results)
    print(
        f"[StrollerLadder] {'PASS' if ok else 'FAIL'} impratio {impratio}: "
        + ", ".join(f"{r['test']} {r['passes']}/{r['of']}" for r in results)
    )
    return ok, results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ladder"])
    ap.add_argument("--brain", default="stroller_roll")
    ap.add_argument("--impratio", type=float, default=1.0)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--grad", type=int, default=100)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    ok, results = run_ladder(a.brain, a.impratio, a.seeds, a.grad)
    if a.json:
        a.json.write_text(json.dumps(results, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
