"""Replays the stock G1 Joystick reset randomisation on CPU MuJoCo (base xy +-0.5, yaw, joints x U(0.5, 1.5), base
velocity U(-0.5, 0.5)) and holds ctrl = the randomised joint angles (the env's reset ctrl) with zero policy action,
for N seeds. Reports when the stock termination would end each episode (torso gravity z < 0, the three foot / shin
contact sensors, non-finite state) in control steps (20 ms), and the foot penetration at reset.
Usage (trainer container, CPU): python grandma/diag_reset_rand.py [--creature matt] [--seeds 200]"""
import sys
from collections import Counter
from pathlib import Path

import mujoco
import numpy as np

who = sys.argv[sys.argv.index("--creature") + 1] if "--creature" in sys.argv else "grandma"
N = int(sys.argv[sys.argv.index("--seeds") + 1]) if "--seeds" in sys.argv else 200
m = mujoco.MjModel.from_xml_path(str(Path(__file__).resolve().parents[1] / who / "assets" / f"{who}_porace.xml"))
d = mujoco.MjData(m)
key = m.key("knees_bent").id; q0 = m.key_qpos[key].copy()
S = {n: m.sensor_adr[m.sensor(n).id] for n in ("right_foot_left_foot_found", "left_foot_right_shin_found", "right_foot_left_shin_found")}
torso = m.body("torso_link").id
floor = m.geom("floor").id

def why():
  if not np.isfinite(d.qpos).all() or not np.isfinite(d.qvel).all(): return "nan"
  up = d.xmat[torso].reshape(3, 3)[2, 2]   # torso z axis . world z  (stock: gravity in torso frame, z < 0)
  if up < 0: return "fell"
  for n, a in S.items():
    if d.sensordata[a] > 0: return n
  return None

ends, reasons, pen0 = [], Counter(), []
for seed in range(N):
  rng = np.random.default_rng(seed)
  mujoco.mj_resetData(m, d)
  q = q0.copy(); q[0:2] += rng.uniform(-0.5, 0.5, 2)
  yaw = rng.uniform(-3.14, 3.14); q[3:7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
  q[7:] *= rng.uniform(0.5, 1.5, m.nq - 7)
  d.qpos[:] = q; d.qvel[:6] = rng.uniform(-0.5, 0.5, 6); d.ctrl[:] = q[7:]
  mujoco.mj_forward(m, d)
  pen0.append(min([d.contact[i].dist for i in range(d.ncon) if floor in (d.contact[i].geom1, d.contact[i].geom2)] or [0.0]))
  end, r = 1000, "survived 1000"
  for k in range(1000):
    for _ in range(5): mujoco.mj_step(m, d)
    w = why()
    if w: end, r = k + 1, w; break
  ends.append(end); reasons[r] += 1
ends = np.array(ends)
print(f"{who}: {N} seeds | episode length (ctrl steps) median {np.median(ends):.0f}, mean {ends.mean():.1f}, "
      f"<= 5 steps: {(ends <= 5).mean():.0%} | ends: {dict(reasons)}")
print(f"  floor penetration at reset: median {np.median(pen0) * 100:.1f} cm, worst {min(pen0) * 100:.1f} cm")
