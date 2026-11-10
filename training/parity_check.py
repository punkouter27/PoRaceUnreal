"""The parity gate (SPEC 5): does Unreal + URLab move the Go2 exactly as CPU MuJoCo does?

    uv run --no-project --python 3.12 --with mujoco==4.0.0 --with onnxruntime --with numpy python parity_check.py run
    ... parity_check.py make                       # only write the replay files Unreal plays
    ... parity_check.py compare <name>             # only compare an existing Unreal dump

`run` launches Unreal once per case (headless, -nullrhi) and compares what it recorded with Python:

  hold      2 s holding the home pose, no brain          gate: every body within 1 mm, joints within 1e-6
  replay    5 s of recorded controls (go2_loco, 0.5 m/s) gate: every body within 1 mm at every physics step
  policy    5 s with the brain in the loop in Unreal      gate: base within 1 cm after 5 s, same upright outcome,
                                                                Unreal's brain output vs onnxruntime < 1e-4

Python steps both the model Unreal runs (Saved/PoRace/model_bound.mjb: URLab's rebuild after URacerController wrote the
training numbers back over it) and the training model itself (the source XML). Both are gates: the first proves Unreal
steps MuJoCo faithfully, the second that what it steps is the model the brains were trained on.
Also checked: every physics number of the bound model against the source model (readback).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from go2 import constants as C  # noqa: E402
from go2.sim import DEFAULT, Go2Sim, brain, find, qpos_slot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPLAYS = ROOT / "training" / "replays"
SAVED = ROOT / "Saved" / "PoRace"
MJB = ROOT / "Saved" / "PoRace" / "model_bound.mjb"   # the model as URacerController runs it (after its corrections)
FP = json.loads((ROOT / "training" / "models" / "go2_fingerprint.json").read_text())
UE = Path(os.environ.get("UE_ROOT", r"C:\Program Files\Epic Games\UE_5.8")) / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
LEVEL = "/Game/Levels/L_Testbed"
CASES = {"hold": ("Replay", 2.0), "replay": ("Replay", 5.0), "policy": ("Policy", 5.0)}
POLICY_BRAIN, POLICY_COMMAND = "go2_loco", [0.5, 0.0, 0.0]


# --- replay files ----------------------------------------------------------------------------------------------------
def make():
  REPLAYS.mkdir(parents=True, exist_ok=True)
  base = {"actuators": C.ACTUATOR_NAMES, "qpos_names": FP["qpos_names"], "qpos0": FP["qpos_home"], "decimation": C.DECIMATION}
  hold = [[float(np.float32(x)) for x in C.DEFAULT_POSE]] * int(CASES["hold"][1] / C.CTRL_DT)
  ref = json.loads((ROOT / "docs" / "parity" / "reference_trajectory.json").read_text())
  for name, ctrl in (("hold", hold), ("replay", [f["ctrl"] for f in ref["frames"]])):
    (REPLAYS / f"go2_{name}.json").write_text(json.dumps({**base, "ctrl": ctrl}))
    print(f"wrote training/replays/go2_{name}.json ({len(ctrl)} control steps)")


# --- the two Python models -------------------------------------------------------------------------------------------
def apply_options(m):
  o = FP["option"]
  for k, v in o.items():
    if isinstance(v, list):
      getattr(m.opt, k)[:] = v
    else:
      setattr(m.opt, k, v)


def models():
  """(label, model, qpos addresses in fingerprint order) for the source XML and, when present, URLab's compiled model."""
  out = []
  src = mujoco.MjModel.from_xml_path(str(C.SCENE_XML))
  out.append(("source XML", src, list(range(src.nq))))
  if MJB.exists():
    mjb = mujoco.MjModel.from_binary_path(str(MJB))
    apply_options(mjb)   # the .mjb is saved before the controller overwrites the options
    slots = [qpos_slot(mjb, n) for n in FP["qpos_names"]]
    assert min(slots) >= 0, "URLab's model is missing a qpos slot"
    out.append(("Unreal model", mjb, slots))
  return out


def body_gap_mm(src, qa, qb):
  """Largest distance between the same body in two poses (fingerprint qpos order = the source model's), in mm."""
  da, db = mujoco.MjData(src), mujoco.MjData(src)
  worst = 0.0
  for a, b in zip(qa, qb):
    da.qpos[:] = a; db.qpos[:] = b
    mujoco.mj_kinematics(src, da); mujoco.mj_kinematics(src, db)
    worst = max(worst, float(np.linalg.norm(da.xpos[:14] - db.xpos[:14], axis=1).max()))   # world + the Go2's 13 bodies
  return worst * 1000.0


def py_replay(m, slots, replay):
  d = mujoco.MjData(m)
  mujoco.mj_resetData(m, d)
  d.qpos[slots] = replay["qpos0"]
  act = [find(m, mujoco.mjtObj.mjOBJ_ACTUATOR, m.nu, a) for a in replay["actuators"]]
  d.ctrl[act] = DEFAULT
  mujoco.mj_forward(m, d)
  out = []
  for row in replay["ctrl"]:
    for _ in range(replay["decimation"]):
      out.append(d.qpos[slots].copy())
      d.ctrl[act] = row
      mujoco.mj_step(m, d)
  out.append(d.qpos[slots].copy())
  return np.array(out)


def py_policy(m, slots, command, seconds):
  sim = Go2Sim(model=m, home=dict(zip(slots, FP["qpos_home"])))
  policy = brain(POLICY_BRAIN)
  out = []
  for _ in range(int(round(seconds / C.CTRL_DT))):
    # sim.step_joystick, opened up to record qpos before each physics step as Unreal does
    target = np.asarray(command, np.float32)
    sim.command = sim.command + np.clip(target - sim.command, -C.CMD_SLEW_STEP, C.CMD_SLEW_STEP)
    obs = sim.obs_joystick()
    action = np.clip(policy(obs), -1, 1).astype(np.float32)
    sim.d.ctrl[sim.act] = (DEFAULT + C.ACTION_SCALE * action).astype(np.float32)
    for _ in range(C.DECIMATION):
      out.append(sim.d.qpos[slots].copy())
      mujoco.mj_step(sim.m, sim.d)
    sim.last_action = action
  out.append(sim.d.qpos[slots].copy())
  return np.array(out), sim


# --- comparisons -----------------------------------------------------------------------------------------------------
rows, failed = [], []


def row(name, ok, note, gate=True):
  rows.append((name, "OK  " if ok else ("FAIL" if gate else "info"), note))
  if gate and not ok:
    failed.append(name)


def upright(q):
  """z of the base's up axis in the world, from the root quaternion (w, x, y, z)."""
  w, x, y, z = q[3:7]
  return 1.0 - 2.0 * (x * x + y * y)


def compare(name):
  mode, seconds = CASES[name]
  dump = json.loads((SAVED / f"parity_{name}.json").read_text())
  ue = np.array(dump["qpos"])
  src = mujoco.MjModel.from_xml_path(str(C.SCENE_XML))
  for label, m, slots in reversed(models()):   # the bound model first, then the training model
    gate = True
    if mode == "Replay":
      py = py_replay(m, slots, json.loads((REPLAYS / f"go2_{name}.json").read_text()))
    else:
      py, _ = py_policy(m, slots, dump["command"], seconds)
    n = min(len(py), len(ue))
    if len(ue) != len(py):
      row(f"{name}: length", False, f"Unreal {len(ue)} samples, Python {len(py)}", gate)
    dq = np.abs(ue[:n, :C.NQ_ROBOT] - py[:n, :C.NQ_ROBOT])
    gap = body_gap_mm(src, ue[:n], py[:n])
    if mode == "Replay":
      first = next((i for i in range(n) if dq[i].max() > 1e-6), n)
      row(f"{name} vs {label}", gap <= 1.0 and (name != "hold" or dq[:, 7:].max() < 1e-6),
          f"worst body gap {gap:.2e} mm, worst |dqpos| {dq.max():.2e}, identical to 1e-6 for {first * C.SIM_DT:.2f} s of {seconds:.0f} s", gate)
    else:
      base_cm = float(np.linalg.norm(ue[n - 1, :3] - py[n - 1, :3])) * 100.0
      same = (upright(ue[n - 1]) > 0.5) == (upright(py[n - 1]) > 0.5)
      row(f"{name} vs {label}", base_cm <= 1.0 and same,
          f"base {base_cm:.3f} cm apart after {seconds:.0f} s (Unreal x {ue[n - 1, 0]:.3f} m, Python {py[n - 1, 0]:.3f} m), "
          f"worst body gap {gap:.2f} mm, upright Unreal {upright(ue[n - 1]):.3f} / Python {upright(py[n - 1]):.3f}", gate)
  if mode == "Policy":
    policy = brain(POLICY_BRAIN)
    obs, act = np.array(dump["obs"], np.float32), np.array(dump["action"], np.float32)
    err = max(float(np.abs(np.clip(policy(o), -1, 1) - a).max()) for o, a in zip(obs, act))
    row(f"{name}: Unreal's brain vs onnxruntime", err < 1e-4 and len(obs) > 0, f"worst action difference {err:.2e} over {len(obs)} decisions")


# Arrays that do not move a body: names, drawing, mesh data and the solver's caches. Everything else must match.
NOT_PHYSICS = ("name_", "names", "paths", "text_", "tuple_", "numeric_", "key_", "mesh_", "tex_", "mat_", "skin_", "hfield_",
               "light_", "cam_", "flex_", "bvh_", "oct_", "plugin", "vis", "stat", "body_bvhadr", "body_bvhnum", "geom_rgba",
               "geom_matid", "geom_group", "geom_dataid", "site_rgba", "site_group", "site_matid", "site_size", "sensor_",
               "body_plugin", "geom_plugin", "actuator_plugin", "sensor_plugin", "body_iquat", "geom_aabb", "geom_rbound",
               # dof_length scales only the sleep test (engine_sleep.c), and sleep is off (asserted in compare_models).
               # MuJoCo derives it from body sizes, which include URLab's re-centred visual meshes.
               "dof_length")


def compare_models():
  """Every numeric physics array of the bound model against the training model. Collision geoms only for geom arrays
  (URLab re-centres visual meshes; that moves the drawing, not the physics). body_iquat is compared as a rotation
  (q and -q are the same)."""
  ms = models()
  if len(ms) < 2:
    return row("model readback", False, f"{MJB} not found")
  (_, a, _), (_, b, _) = ms
  coll = np.array([bool(a.geom_contype[g] or a.geom_conaffinity[g]) for g in range(a.ngeom)])
  diffs, checked = [], 1
  if b.opt.enableflags & mujoco.mjtEnableBit.mjENBL_SLEEP:
    diffs.append("sleep is enabled: dof_length (exempt above) now changes the physics, compare it")
  for k in sorted(dir(a)):
    if k.startswith("_") or any(k.startswith(p) or p in k for p in NOT_PHYSICS):
      continue
    try:
      x, y = getattr(a, k), getattr(b, k)
    except Exception:  # noqa: BLE001 - not an array on this model
      continue
    if not isinstance(x, np.ndarray) or x.dtype.kind not in "fiub" or x.size == 0:
      continue
    checked += 1
    if x.shape != y.shape:
      diffs.append(f"{k}: shape {x.shape} vs {y.shape}"); continue
    x, y = x.astype(float), y.astype(float)
    if k.startswith("geom_") and x.shape[0] == a.ngeom:
      x, y = x[coll], y[coll]
    d = np.abs(x - y)
    if d.size and d.max() > 1e-12 * max(1.0, float(np.abs(x).max())):
      i = np.unravel_index(d.argmax(), d.shape)
      diffs.append(f"{k}: {(d > 1e-12).sum()} values differ, worst {d.max():.3g} at {tuple(int(v) for v in i)} ({x[i]:.12g} vs {y[i]:.12g})")
  q = np.abs(np.einsum("ij,ij->i", a.body_iquat, b.body_iquat))   # |<q1, q2>| = 1 when they are the same rotation
  checked += 1
  if (1.0 - q).max() > 1e-12:
    diffs.append(f"body_iquat: rotations differ, worst 1 - |q1.q2| = {(1.0 - q).max():.3g}")
  row("model readback (Unreal model vs training model)", not diffs, f"{checked} physics arrays compared, {len(diffs)} differ" + "".join(f"\n    {x}" for x in diffs[:15]))


# --- driving Unreal --------------------------------------------------------------------------------------------------
def launch(name):
  mode, seconds = CASES[name]
  dump = SAVED / f"parity_{name}.json"
  dump.unlink(missing_ok=True)
  args = [str(UE), str(ROOT / "PoRaceUnreal.uproject"), LEVEL, "-game", "-nullrhi", "-unattended", "-nosplash", "-nosound",
          f"-RaceMode={mode}", f"-RaceDump={dump}", "-RaceQuit", "-stdout", "-FullStdOutLogOutput"]
  if mode == "Replay":
    args.append(f"-RaceReplay=training/replays/go2_{name}.json")
  else:
    args += [f"-RaceBrain=training/models/brains/{POLICY_BRAIN}.onnx", f"-RaceCommand={','.join(str(x) for x in POLICY_COMMAND)}", f"-RaceRecord={seconds}"]
  log = SAVED / f"parity_{name}.log"
  SAVED.mkdir(parents=True, exist_ok=True)
  try:
    p = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=600)
    out = p.stdout
  except subprocess.TimeoutExpired as e:
    out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
    out += "\n[parity_check] TIMEOUT after 600 s"
  log.write_text(out, encoding="utf-8", errors="replace")
  lines = [l[l.index("LogRace"):] for l in out.splitlines() if "LogRace" in l]
  print(f"--- Unreal: {name} ({len(lines)} LogRace lines, full log {log.relative_to(ROOT)})")
  for l in lines[:12]:
    print("   ", l[:220])
  return dump.exists()


def report():
  w = max(len(r[0]) for r in rows)
  print()
  for name, status, note in rows:
    print(f"{name:{w}}  {status}  {note}")
  print("\nPARITY", "PASS" if not failed else f"FAIL: {failed}")
  (ROOT / "docs" / "parity" / "ue_parity.json").write_text(json.dumps(
      {"mujoco": mujoco.__version__, "pass": not failed, "rows": [{"name": n, "status": s.strip(), "note": t} for n, s, t in rows]}, indent=1) + "\n")
  return 1 if failed else 0


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("cmd", choices=["make", "run", "compare"])
  ap.add_argument("name", nargs="?", choices=list(CASES))
  a = ap.parse_args()
  if a.cmd == "make":
    return make()
  if a.cmd == "run":
    make()
    for name in ([a.name] if a.name else CASES):
      if launch(name):
        compare(name)
      else:
        row(name, False, "Unreal wrote no dump (see the log)")
    compare_models()
  else:
    for name in ([a.name] if a.name else CASES):
      compare(name)
    compare_models()
  return report()


if __name__ == "__main__":
  sys.exit(main())
