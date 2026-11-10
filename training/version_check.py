"""Slice 1.0: do the Go2 brains (trained on MuJoCo 3.15.0) still work on another MuJoCo version?

    uv run --no-project --python 3.12 --with mujoco==4.0.0 --with onnxruntime --with numpy python version_check.py
    uv run --no-project --python 3.12 --with mujoco==3.15.0 ... (the same checks on the training version, for comparison)

CPU MuJoCo + ONNX only. Four groups of checks, one row each:
  replay    recorded controls from docs/parity/*.json played open loop: how far does the physics itself drift?
  closed    brain in the loop from the recorded start: the closed-loop gate's metrics against the recording
  rung      R0 stand, R1 velocity tracking, speed (fast brain), each over SEEDS perturbed starts
  getup     R3: dropped in a random pose, standing again within 3 s
Writes docs/parity/version_check_<version>.json. Exit code 1 if a brain fails a rung.
"""
import json
import sys
from pathlib import Path

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from go2 import constants as C  # noqa: E402
from go2.sim import DEFAULT, Go2Sim, Q, V, brain  # noqa: E402

PARITY = C.ROOT_PATH.parent / "docs" / "parity"
SEEDS = 10
IMPRATIO = None   # --impratio: run the checks at another impratio (a race with a human runs at 1)
rows, failed = [], []


def make_sim():
  sim = Go2Sim()
  if IMPRATIO is not None:
    sim.m.opt.impratio = IMPRATIO
    sim.reset()
  return sim


def row(group, name, ok, note, gate=True):
  rows.append({"group": group, "name": name, "ok": bool(ok), "gate": gate, "note": note})
  if gate and not ok:
    failed.append(name)


# --- replay and closed loop against the 3.15.0 recordings -----------------------------------------------------------
def analyse(sim, frames):
  """Same measurements as compare_trajectory.py, recomputed from qpos / qvel / ctrl."""
  m, d = sim.m, sim.d
  feet = [m.geom(g).id for g in C.FEET_GEOMS]
  foot_r = float(m.geom_size[feet[0], 0])
  vx, contacts, forces, up = [], [], [], []
  for f in frames:
    d.qpos[:] = f["qpos"]; d.qvel[:] = f["qvel"]; d.ctrl[:] = f["ctrl"]
    mujoco.mj_forward(m, d)
    vx.append(d.qvel[0]); up.append(sim.upright() > 0)
    contacts.append([d.geom_xpos[g][2] < foot_r + 0.005 for g in feet])
    forces.append(np.clip(C.KP * (d.ctrl - d.qpos[Q]) - C.KD * d.qvel[V], -C.FORCERANGE, C.FORCERANGE))
  contacts = np.array(contacts)
  secs = frames[-1]["t"] - frames[0]["t"]
  return dict(upright=bool(np.all(up)), vx=float(np.mean(vx)),
              cadence=float(np.sum(contacts[1:] & ~contacts[:-1]) / max(secs, 1e-6) / 4),
              force=float(np.mean(np.abs(forces))))


def recorded(ref_name, brain_name):
  ref = json.loads((PARITY / f"{ref_name}.json").read_text())
  frames = ref["frames"]
  sim = make_sim()

  # Open loop: the recorded ctrl, no brain. Drift here is the physics change between versions and nothing else.
  sim.reset()
  drift = []
  for f in frames:
    sim.d.ctrl[:] = np.array(f["ctrl"], np.float32)
    sim.physics()
    drift.append(float(np.abs(sim.d.qpos[:C.NQ_ROBOT] - np.array(f["qpos"][:C.NQ_ROBOT])).max()))
  first_mm = next((i for i, e in enumerate(drift) if e > 1e-3), len(drift))
  row("replay", ref_name, drift[49] < 1e-3,
      f"|dqpos| after 0.2 s {drift[9]:.1e}, 1 s {drift[49]:.1e}, 5 s {drift[-1]:.1e}; under 1 mm for {first_mm * C.CTRL_DT:.2f} s", gate=False)

  # Closed loop: the brain reacts, so small physics differences are corrected or amplified. This is the one that matters.
  sim.reset()
  policy = brain(brain_name)
  mine, act_err = [], 0.0
  for f in frames:
    act_err = max(act_err, float(np.abs(policy(np.array(f["obs"], np.float32)) - np.array(f["action"])).max()))
    sim.step_joystick(policy, ref["command"])
    mine.append({"t": float(sim.d.time), "qpos": sim.d.qpos.tolist(), "qvel": sim.d.qvel.tolist(), "ctrl": sim.d.ctrl.tolist()})
  r, u = analyse(sim, frames), analyse(sim, mine)
  ok = (u["upright"] and abs(u["vx"] - r["vx"]) <= 0.1 and abs(u["cadence"] - r["cadence"]) <= 0.1 * r["cadence"] + 0.05
        and abs(u["force"] - r["force"]) <= 0.15 * r["force"])
  row("closed", f"{brain_name} cmd {ref['command'][0]}", ok,
      f"vx {u['vx']:.3f} (rec {r['vx']:.3f}), cadence {u['cadence']:.2f} Hz ({r['cadence']:.2f}), "
      f"|force| {u['force']:.2f} N.m ({r['force']:.2f}), upright {u['upright']}, brain vs recorded action {act_err:.1e}")


# --- ladder rungs ----------------------------------------------------------------------------------------------------
def perturbed(sim, rng):
  """Home pose with a random heading and small joint offsets, so the seeds are different episodes."""
  sim.reset()
  yaw = rng.uniform(-np.pi, np.pi)
  sim.d.qpos[3:7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
  sim.d.qpos[Q] = DEFAULT + rng.uniform(-0.1, 0.1, C.NU)
  mujoco.mj_forward(sim.m, sim.d)


def rung_track(name, brain_name, commands, seconds, tol, need):
  sim, policy, rng = make_sim(), brain(brain_name), np.random.default_rng(0)
  passes, worst, speeds = 0, 0.0, []
  for seed in range(SEEDS):
    cmd = np.array(commands[seed % len(commands)], np.float32)
    perturbed(sim, rng)
    n = int(seconds / C.CTRL_DT)
    fell, v = False, []
    for k in range(n):
      sim.step_joystick(policy, cmd)
      fell = fell or sim.upright() < 0.5
      if k >= n // 2:   # measured over the second half, after the start-up transient
        v.append([sim.local_linvel()[0], sim.local_linvel()[1], sim.gyro()[2]])
    err = float(np.abs(np.mean(v, axis=0)[:2] - cmd[:2]).max())
    worst = max(worst, err); speeds.append(float(np.mean(v, axis=0)[0]))
    passes += (not fell) and err < tol
  row("rung", name, passes >= need, f"{passes}/{SEEDS} (need {need}), worst velocity error {worst:.2f} m/s, mean vx {np.mean(speeds):.2f}")


def rung_getup():
  sim, policy, rng = make_sim(), brain("go2_getup"), np.random.default_rng(1)
  passes, times = 0, []
  for _ in range(SEEDS):
    sim.reset()
    q = rng.normal(size=4); q /= np.linalg.norm(q)   # any orientation
    sim.d.qpos[2] = 0.5; sim.d.qpos[3:7] = q
    lo, hi = sim.m.jnt_range[1:13, 0], sim.m.jnt_range[1:13, 1]
    sim.d.qpos[Q] = rng.uniform(lo, hi)
    mujoco.mj_forward(sim.m, sim.d)
    sim.d.ctrl[:] = sim.d.qpos[Q]
    sim.physics(int(0.5 / C.SIM_DT))   # drop and settle 0.5 s holding the joints, as the env does
    sim.last_action[:] = 0
    stood = None
    for k in range(int(5.0 / C.CTRL_DT)):
      sim.step_getup(policy)
      if stood is None and sim.upright() > 0.9 and sim.d.qpos[2] > 0.2:
        stood = (k + 1) * C.CTRL_DT
    ok = stood is not None and stood <= 3.0 and sim.upright() > 0.9 and sim.d.qpos[2] > 0.2
    passes += ok
    if stood is not None:
      times.append(stood)
  row("getup", "R3 go2_getup", passes >= 9, f"{passes}/{SEEDS} (need 9), mean time to stand {np.mean(times) if times else float('nan'):.2f} s")


def main():
  global IMPRATIO
  if "--impratio" in sys.argv:
    IMPRATIO = float(sys.argv[sys.argv.index("--impratio") + 1])
  recorded("reference_trajectory", "go2_loco")
  recorded("reference_fast", "go2_loco_fast")
  recorded("reference_steeple", "go2_loco_steeple")
  rung_track("R0 stand go2_loco", "go2_loco", [[0, 0, 0]], 10, 0.2, SEEDS)
  rung_track("R1 track go2_loco", "go2_loco", [[0.5, 0, 0], [1.0, 0, 0], [1.5, 0, 0], [0.5, 0.3, 0], [1.0, 0, 0.5]], 10, 0.2, SEEDS)
  rung_track("R1 track go2_loco_steeple", "go2_loco_steeple", [[0.5, 0, 0], [1.0, 0, 0], [1.5, 0, 0]], 10, 0.2, SEEDS)
  rung_track("R1 track go2_loco_bank", "go2_loco_bank", [[0.5, 0, 0], [1.0, 0, 0], [1.5, 0, 0]], 10, 0.2, SEEDS)
  rung_track("speed go2_loco_fast", "go2_loco_fast", [[2.0, 0, 0], [2.5, 0, 0]], 10, 0.5, 9)
  rung_getup()
  w = max(len(r["name"]) for r in rows)
  print(f"MuJoCo {mujoco.__version__}" + (f", impratio {IMPRATIO}" if IMPRATIO is not None else ""))
  for r in rows:
    print(f"{r['group']:6} {r['name']:{w}}  {'OK  ' if r['ok'] else ('FAIL' if r['gate'] else 'diff')}  {r['note']}")
  (PARITY / f"version_check_{mujoco.__version__}{'' if IMPRATIO is None else f'_impratio{IMPRATIO:g}'}.json").write_text(json.dumps({"mujoco": mujoco.__version__, "rows": rows}, indent=1) + "\n")
  print("\nRESULT", "PASS" if not failed else f"FAIL: {failed}")
  return 1 if failed else 0


if __name__ == "__main__":
  sys.exit(main())
