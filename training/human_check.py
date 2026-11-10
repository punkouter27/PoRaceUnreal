"""Slice 3: does Matt's brain (m20, trained on MuJoCo 3.x) still walk on MuJoCo 4.0.0, through racelib/human.py?

    uv run --no-project --python 3.12 --with mujoco==4.0.0 --with onnxruntime --with numpy python human_check.py [--creature matt]

  replay   the training recording's controls played open loop (docs/parity/matt_reference_m20.json, made by
           matt/sim.py record from the JAX checkpoint): how far does the physics itself drift on this version?
  brain    the exported ONNX on the recorded observations against the recorded actions (export fidelity)
  closed   HumanRacer with the brain in the loop from the same start and command: the recording's speed and stance
  rungs    stand 10 s; race speeds 0.8 / 1.2 / 1.6 m/s for 10 s; a 0.8 rad/s turn; from perturbed starts, 10 seeds
Writes docs/parity/human_check_<creature>_<version>.json. Exit 1 if a gated row fails.
"""
import argparse
import json
import sys
from pathlib import Path

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from go2.sim import brain  # noqa: E402
from racelib.human import CTRL_DT, DECIMATION, HumanRacer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SEEDS = 10
rows, failed = [], []


def row(group, name, ok, note, gate=True):
  rows.append({"group": group, "name": name, "ok": bool(ok), "gate": gate, "note": note})
  if gate and not ok:
    failed.append(name)


def setup(creature):
  card = json.loads((ROOT / "training" / "characters" / f"{creature}.json").read_text())
  fp = json.loads((ROOT / card["fingerprint"]).read_text())
  m = mujoco.MjModel.from_xml_path(str(ROOT / card["model"]))
  d = mujoco.MjData(m)
  mujoco.mj_resetData(m, d)
  r = HumanRacer(m, d, "", card, fp, brain(card["brains"]["flat"]))
  return card, fp, m, d, r


def run(r, command, decisions, on_step=None):
  r.target[:] = command
  for k in range(decisions * DECIMATION):
    r.control()
    mujoco.mj_step(r.m, r.d)
    if on_step:
      on_step(k)


def recorded(creature):
  ref = json.loads((ROOT / "docs" / "parity" / f"{creature}_reference_m20.json").read_text())
  frames = ref["frames"]
  card, fp, m, d, r = setup(creature)
  r.reset_to_spawn()
  # open loop: the recorded controls
  drift = []
  for f in frames:
    d.ctrl[r.act] = np.array(f["ctrl"], np.float64)[r.act] if len(f["ctrl"]) == m.nu else f["ctrl"]
    for _ in range(DECIMATION):
      mujoco.mj_step(m, d)
    drift.append(float(np.abs(d.qpos - np.array(f["qpos"])).max()))
  first = next((i for i, e in enumerate(drift) if e > 1e-3), len(drift))
  row("replay", f"{creature} recorded controls", drift[49] < 1e-3, f"|dqpos| after 1 s {drift[49]:.1e}, 5 s {drift[-1]:.1e}; under 1 mm for {first * CTRL_DT:.2f} s", gate=False)
  # the brain on the recorded observations
  err = max(float(np.abs(r.loco(np.array(f["obs"], np.float32)) - np.array(f["action"])).max()) for f in frames)
  row("brain", f"{creature} ONNX vs recorded actions", err < 1e-4, f"worst action difference {err:.1e} over {len(frames)} decisions")
  # closed loop
  card, fp, m, d, r = setup(creature)
  r.reset_to_spawn()
  mine = []
  r.target[:] = ref["command"]
  first_obs_err = None
  for k, f in enumerate(frames):
    for s in range(DECIMATION):
      r.control()
      if s == 0 and first_obs_err is None:
        first_obs_err = float(np.abs(r.obs - np.array(f["obs"], np.float32)).max())
      mujoco.mj_step(m, d)
    mine.append(d.qpos.copy())
  rec = np.array([f["qpos"] for f in frames]); mine = np.array(mine)
  base_cm = float(np.linalg.norm(mine[-1, :3] - rec[-1, :3])) * 100
  vx_mine, vx_rec = (mine[-1, 0] - mine[49, 0]) / (len(frames) - 50) / CTRL_DT, (rec[-1, 0] - rec[49, 0]) / (len(frames) - 50) / CTRL_DT
  up = bool(mine[:, 2].min() > card["fallenPelvisZ"])
  row("closed", f"{creature} brain in the loop, cmd {ref['command'][0]}", up and abs(vx_mine - vx_rec) < 0.1,
      f"first observation vs recorded {first_obs_err:.1e}; after 5 s pelvis {base_cm:.1f} cm from the recording; speed 1-5 s {vx_mine:.3f} m/s "
      f"(recorded {vx_rec:.3f}); lowest pelvis {mine[:, 2].min():.3f} m")


def rungs(creature):
  def episodes(name, commands, seconds, tol, need):
    passes, worst, speeds = 0, 0.0, []
    for seed in range(SEEDS):
      rng = np.random.default_rng(seed)
      card, fp, m, d, r = setup(creature)
      r.spawn_yaw = rng.uniform(-np.pi, np.pi)
      r.reset_to_spawn()
      d.qpos[r.qadr] += rng.uniform(-0.05, 0.05, r.nu)
      mujoco.mj_forward(m, d)
      cmd = np.array(commands[seed % len(commands)])
      fell, v = False, []
      n = int(seconds / CTRL_DT)
      def watch(k):
        nonlocal fell
        fell = fell or not r.upright or d.qpos[r.root_q + 2] < card["fallenPelvisZ"]
        if k % DECIMATION == 0 and k // DECIMATION >= n // 2:
          v.append([d.sensordata[r.adr_linvel], d.sensordata[r.adr_linvel + 1], d.sensordata[r.adr_gyro + 2]])
      run(r, cmd, n, watch)
      mv = np.mean(v, axis=0)
      e = float(np.abs(mv[:2] - cmd[:2]).max()) if cmd[2] == 0 else float(abs(mv[2] - cmd[2]))
      worst = max(worst, e); speeds.append(float(mv[0]))
      passes += (not fell) and e < tol
    row("rung", f"{creature} {name}", passes >= need, f"{passes}/{SEEDS} (need {need}), worst error {worst:.2f}, mean vx {np.mean(speeds):.2f} m/s")
  episodes("stand 10 s", [[0, 0, 0]], 10, 0.25, SEEDS)
  episodes("race speeds 0.8/1.2/1.6 m/s", [[0.8, 0, 0], [1.2, 0, 0], [1.6, 0, 0]], 10, 0.25, 9)
  episodes("turn 0.8 rad/s at 1.0 m/s", [[1.0, 0, 0.8]], 10, 0.3, 9)


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--creature", default="matt")
  a = ap.parse_args()
  recorded(a.creature)
  rungs(a.creature)
  w = max(len(r["name"]) for r in rows)
  print(f"MuJoCo {mujoco.__version__}")
  for r in rows:
    print(f"{r['group']:6} {r['name']:{w}}  {'OK  ' if r['ok'] else ('FAIL' if r['gate'] else 'diff')}  {r['note']}")
  (ROOT / "docs" / "parity" / f"human_check_{a.creature}_{mujoco.__version__}.json").write_text(
      json.dumps({"mujoco": mujoco.__version__, "rows": rows}, indent=1) + "\n")
  print("\nRESULT", "PASS" if not failed else f"FAIL: {failed}")
  return 1 if failed else 0


if __name__ == "__main__":
  sys.exit(main())
