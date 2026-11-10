"""Why do Grandma's episodes end within ~4 control steps (run g1)? CPU MuJoCo: from the reset keyframe, hold the
default pose with the actuators (PD) and report, step by step, the stock G1 Joystick termination tests:
torso gravity z < 0 (fallen), left foot <-> right foot, foot <-> opposite shin collisions; plus pelvis height and
every contact pair touching a foot. Usage (trainer container, CPU is fine): python grandma/diag_reset.py [--creature matt]"""
import sys
from pathlib import Path

import mujoco
import numpy as np

who = sys.argv[sys.argv.index("--creature") + 1] if "--creature" in sys.argv else "grandma"
xml = Path(__file__).resolve().parents[1] / who / "assets" / f"{who}_porace.xml"
m = mujoco.MjModel.from_xml_path(str(xml)); d = mujoco.MjData(m)
key = m.key("knees_bent").id
mujoco.mj_resetDataKeyframe(m, d, key)
d.ctrl[:] = m.key_ctrl[key] if m.nkey and m.key_ctrl.size else d.qpos[7:]
mujoco.mj_forward(m, d)

def gid(name):
  try: return m.geom(name).id
  except KeyError: return -1

feet = {"left_foot": gid("left_foot"), "right_foot": gid("right_foot")}
shins = {"left_shin": gid("left_shin"), "right_shin": gid("right_shin")}
print(who, "| geoms:", {**feet, **shins}, "| nq", m.nq, "nu", m.nu, "| timestep", m.opt.timestep)
pairs = [(feet["left_foot"], feet["right_foot"], "Lfoot-Rfoot"), (feet["left_foot"], shins["right_shin"], "Lfoot-Rshin"),
         (feet["right_foot"], shins["left_shin"], "Rfoot-Lshin")]
torso_site = m.site("imu_in_torso").id if any(m.site(i).name == "imu_in_torso" for i in range(m.nsite)) else None

def grav_z():
  if torso_site is not None: R = d.site_xmat[torso_site].reshape(3, 3)
  else: R = d.xmat[m.body("torso_link").id].reshape(3, 3)
  return (R.T @ np.array([0, 0, -1.0]))[2] * -1   # stock get_gravity: gravity in the torso frame, z component sign as G1Env

def colliding(a, b):
  for i in range(d.ncon):
    c = d.contact[i]
    if {c.geom1, c.geom2} == {a, b} and c.dist < 0: return True
  return False

steps_per_ctrl = 5
for k in range(0, 60):
  if k in (0, 1, 2, 3, 4, 5, 10, 25, 50) or k == 59:
    hits = [n for a, b, n in pairs if a >= 0 and b >= 0 and colliding(a, b)]
    footc = sorted({(m.geom(c.geom1).name or str(c.geom1), m.geom(c.geom2).name or str(c.geom2)) for c in d.contact[:d.ncon]
                    if c.geom1 in feet.values() or c.geom2 in feet.values()})
    sens = {n: float(d.sensordata[m.sensor_adr[m.sensor(n).id]]) for n in ("right_foot_left_foot_found", "left_foot_right_shin_found", "right_foot_left_shin_found")}
    fired = [n for n, v in sens.items() if v > 0]
    print(f"ctrl step {k:2d}: pelvis z {d.qpos[2]:.3f}  torso up {grav_z():+.3f}  termination sensors fired {fired or '-'}  foot-floor {len(footc)}")
  for _ in range(steps_per_ctrl): mujoco.mj_step(m, d)
