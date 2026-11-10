"""A track's MuJoCo model: floor, rails and every racer of the roster, in one file Unreal imports through URLab.

    uv run --no-project --python 3.12 --with mujoco==4.0.0 --with numpy python build_track_model.py planar_sprint [--racers go2]

Writes
  training/assets/tracks/<track>.xml              the model (meshes are read from the creatures' own asset folders)
  training/models/tracks/<track>_fingerprint.json options, the world geoms' exact numbers, the racer roster

Rails: one box per centre-line segment and side, 0.3 m tall and 0.1 m thick, at the half width (mitred at corners, 6 m
past the ends of an open track): Unity's TrackBuilder, as MuJoCo geoms. The floor and options are the Go2 training
scene's. Banked surfaces and obstacles arrive in Slice 6.
Racers are attached with a name prefix ("blue_"), so one model holds them all; their numbers come from the
creature fingerprint (training/contract.py).
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from go2 import constants as G  # noqa: E402
from contract import OPT_SCALARS, OPT_VECTORS, floats, option  # noqa: E402
from racelib.track import Track, left  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "training" / "assets" / "tracks"
MODELS = ROOT / "training" / "models" / "tracks"
RAIL_HALF_HEIGHT, RAIL_HALF_THICK, RAIL_OVERLAP, OPEN_END = 0.15, 0.05, 0.06, 6.0


def card(name):
  return json.loads((ROOT / "training" / "characters" / f"{name}.json").read_text(encoding="utf-8"))


def rails(track: Track):
  """(name, centre x, y, half length, yaw) per rail box, from the mitred offset polylines."""
  n, w = track.n, track.half_width
  verts = n if track.closed else n + 1
  centre, lft, rgt = [], [], []
  for i in range(verts):
    p = track.P(i)
    def unit(a, b):
      dx, dy = b[0] - a[0], b[1] - a[1]
      ln = math.hypot(dx, dy)
      return (dx / ln, dy / ln)
    d_prev = unit(track.P(i - 1), p) if (track.closed or i > 0) else unit(p, track.P(i + 1))
    d_next = unit(p, track.P(i + 1)) if (track.closed or i < n) else d_prev
    lp, ln_ = left(d_prev), left(d_next)
    nx, ny = lp[0] + ln_[0], lp[1] + ln_[1]
    nl = math.hypot(nx, ny)
    nrm = (nx / nl, ny / nl)
    k = 1.0 / max(0.5, nrm[0] * ln_[0] + nrm[1] * ln_[1])   # mitre length
    if not track.closed and i == 0:
      p = (p[0] - d_next[0] * OPEN_END, p[1] - d_next[1] * OPEN_END)
    elif not track.closed and i == n:
      p = (p[0] + d_prev[0] * OPEN_END, p[1] + d_prev[1] * OPEN_END)
    centre.append(p)
    lft.append((p[0] + nrm[0] * w * k, p[1] + nrm[1] * w * k))
    rgt.append((p[0] - nrm[0] * w * k, p[1] - nrm[1] * w * k))
  out = []
  for i in range(n):
    j = (i + 1) % verts
    for side, pts in (("L", lft), ("R", rgt)):
      a, b = pts[i], pts[j]
      dx, dy = b[0] - a[0], b[1] - a[1]
      out.append((f"rail_{side}{i}", 0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]), 0.5 * math.hypot(dx, dy) + RAIL_OVERLAP, math.atan2(dy, dx)))
  return out


def build(track_id, racer_cards):
  track = Track.load(track_id)
  if track.terrain != "flat":
    raise SystemExit(f"{track_id}: {track.terrain} terrain is built in Slice 6 (banked surface, obstacles)")
  scene = mujoco.MjModel.from_xml_path(str(G.SCENE_XML))   # the Go2 training scene: options and floor come from here

  spec = mujoco.MjSpec()
  spec.modelname = f"porace_{track_id}"
  spec.compiler.degree = False
  spec.meshdir = os.path.relpath(G.ASSET_PATH / "assets", ASSETS).replace("\\", "/")
  o = spec.option
  for k in OPT_SCALARS:
    setattr(o, k, getattr(scene.opt, k))
  for k in OPT_VECTORS:
    getattr(o, k)[:] = getattr(scene.opt, k)

  wb = spec.worldbody
  fi = mujoco.mj_name2id(scene, mujoco.mjtObj.mjOBJ_GEOM, "floor")
  floor = wb.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0, 0, 0.01])
  floor.friction = scene.geom_friction[fi]; floor.condim = int(scene.geom_condim[fi]); floor.priority = int(scene.geom_priority[fi])
  floor.contype = int(scene.geom_contype[fi]); floor.conaffinity = int(scene.geom_conaffinity[fi])
  floor.rgba = [0.22, 0.24, 0.27, 1]
  for name, x, y, half, yaw in rails(track):
    g = wb.add_geom(name=name, type=mujoco.mjtGeom.mjGEOM_BOX, size=[half, RAIL_HALF_THICK, RAIL_HALF_HEIGHT],
                    pos=[x, y, RAIL_HALF_HEIGHT], quat=[math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)])
    g.rgba = [0.85, 0.25, 0.15, 1]

  roster = []
  for i, cname in enumerate(racer_cards):
    c = card(cname)
    if track.terrain not in c["terrains"]:
      print(f"{c['racerName']} sits out {track.name} ({track.terrain})")
      continue
    prefix = c["racerName"].lower() + "_"
    child = mujoco.MjSpec.from_file(str(ROOT / c["model"]))
    frame = wb.add_frame(pos=[0, 2.0 * i, c["homeHeight"]])   # placeholder pose: the race spawns every racer itself
    frame.attach_body(child.body(c["rootBody"]), prefix, "")
    roster.append({"name": c["racerName"], "card": cname, "prefix": prefix, "creature": c["id"], "fingerprint": c["fingerprint"],
                   "color": c["racerColor"], "cruise": c["cruise"], "maxYawRate": c["maxYawRate"], "homeHeight": c["homeHeight"],
                   "usesUnstick": c["usesUnstick"], "brain": c["brains"][track.terrain], "getupBrain": c["brains"]["getup"]})

  m = spec.compile()
  ASSETS.mkdir(parents=True, exist_ok=True); MODELS.mkdir(parents=True, exist_ok=True)
  xml_path = ASSETS / f"{track_id}.xml"
  xml_path.write_text(spec.to_xml(), encoding="utf-8", newline="\n")
  m2 = mujoco.MjModel.from_xml_path(str(xml_path))   # the file must reload to the same model
  assert (m2.nq, m2.nu, m2.ngeom) == (m.nq, m.nu, m.ngeom)

  T = mujoco.mjtObj
  geoms = []
  for g in range(m2.ngeom):
    if m2.geom_bodyid[g] != 0:
      continue
    geoms.append({"name": mujoco.mj_id2name(m2, T.mjOBJ_GEOM, g), "type": int(m2.geom_type[g]), "pos": floats(m2.geom_pos[g]),
                  "quat": floats(m2.geom_quat[g]), "size": floats(m2.geom_size[g]), "friction": floats(m2.geom_friction[g]),
                  "margin": float(m2.geom_margin[g]), "gap": float(m2.geom_gap[g]), "solref": floats(m2.geom_solref[g]),
                  "solimp": floats(m2.geom_solimp[g]), "solmix": float(m2.geom_solmix[g])})
  fp = {"track": track_id, "model": f"training/assets/tracks/{track_id}.xml", "option": option(m2),
        "world": {"geoms": geoms}, "racers": roster}
  fp_path = MODELS / f"{track_id}_fingerprint.json"
  fp_path.write_text(json.dumps(fp, indent=1) + "\n", encoding="utf-8", newline="\n")
  print(f"{track.name}: {len(geoms)} world geoms ({len(geoms) - 1} rails), {len(roster)} racers, nq {m2.nq} nu {m2.nu}"
        f"\n  wrote {xml_path.relative_to(ROOT)}\n  wrote {fp_path.relative_to(ROOT)}")
  return m2, fp


if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("track")
  ap.add_argument("--racers", nargs="+", default=["go2"], help="character cards to put on the grid")
  a = ap.parse_args()
  build(a.track, a.racers)
