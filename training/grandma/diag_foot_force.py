"""Is the stock contact-force cost measuring the floor? CPU MuJoCo, reset keyframe, PD hold of the default pose for
0.4 s (before the passive topple): the `left_foot_force` / `right_foot_force` sensors (what the stock contact_force
cost reads) vs the true floor normal force on each foot (mj_contactForce), in body weights, and where each sensor site
sits relative to its foot geom. Usage: python grandma/diag_foot_force.py [matt|grandma]"""
import sys
from pathlib import Path

import mujoco
import numpy as np

who = sys.argv[1] if len(sys.argv) > 1 else "grandma"
m = mujoco.MjModel.from_xml_path(str(Path(__file__).resolve().parents[1] / who / "assets" / f"{who}_porace.xml"))
d = mujoco.MjData(m)
key = m.key("knees_bent").id
mujoco.mj_resetDataKeyframe(m, d, key); d.ctrl[:] = d.qpos[7:]; mujoco.mj_forward(m, d)
W = m.body_mass.sum() * 9.81
floor = m.geom("floor").id
for side in ("left", "right"):
  s = m.sensor(f"{side}_foot_force"); site = s.objid[0]; g = m.geom(f"{side}_foot").id
  print(f"{side}: sensor type {mujoco.mjtSensor(s.type[0]).name} on site '{m.site(site).name}' (body '{m.body(m.site_bodyid[site]).name}'), "
        f"foot geom body '{m.body(m.geom_bodyid[g]).name}', site-to-foot-centre {np.linalg.norm(d.site_xpos[site] - d.geom_xpos[g]) * 100:.1f} cm")
sens, true = [], []
f6 = np.zeros(6)
for k in range(100):   # 0.4 s
  mujoco.mj_step(m, d)
  row_s, row_t = [], []
  for side in ("left", "right"):
    a = m.sensor_adr[m.sensor(f"{side}_foot_force").id]; row_s.append(np.linalg.norm(d.sensordata[a:a + 3]))
    g = m.geom(f"{side}_foot").id; tot = 0.0
    for i in range(d.ncon):
      c = d.contact[i]
      if {c.geom1, c.geom2} == {g, floor}: mujoco.mj_contactForce(m, d, i, f6); tot += f6[0]
    row_t.append(tot)
  sens.append(row_s); true.append(row_t)
sens, true = np.array(sens) / W, np.array(true) / W
print(f"{who} ({m.body_mass.sum():.1f} kg): sensor |F| per foot, median / p99 {np.median(sens):.2f} / {np.percentile(sens, 99):.2f} BW | "
      f"floor normal force per foot, median / p99 {np.median(true):.2f} / {np.percentile(true, 99):.2f} BW")
