"""The contract every runtime shares (Python reference, Unreal, browser), and the tool that writes it out.

    uv run --no-project --python 3.12 --with mujoco==4.0.0 --with numpy python contract.py          # write the files
    uv run --no-project --python 3.12 --with mujoco==4.0.0 --with numpy python contract.py --check  # exit 1 if any is stale

Writes, from the trainer's own constants and compiled models:
  training/models/go2_fingerprint.json        the Go2 model as Unreal must reproduce it (options, names, home pose)
  Source/PoRaceUnreal/RaceContract.gen.h      the constants the C++ controller compiles in

Unreal reads the fingerprint at bind time and overwrites URLab's solver options with it: URLab attaches an MJCF as a
child spec, which drops the file's <option> block (PoSlapUnreal found this), so the options must be set by hand.
"""
import argparse
import json
import sys
from pathlib import Path

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from go2 import constants as G  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MUJOCO_VERSION = "4.0.0"

# mjOption fields copied into the fingerprint (scalars, then vectors). Unreal sets exactly these.
OPT_SCALARS = ["timestep", "impratio", "tolerance", "ls_tolerance", "noslip_tolerance", "ccd_tolerance", "density", "viscosity",
               "o_margin", "integrator", "cone", "jacobian", "solver", "iterations", "ls_iterations", "noslip_iterations",
               "ccd_iterations", "disableflags", "enableflags", "sdf_initpoints", "sdf_iterations"]
OPT_VECTORS = ["gravity", "wind", "magnetic", "o_solref", "o_solimp", "o_friction"]


def qpos_names(m):
  """One name per qpos slot: "joint" for a hinge, "joint[k]" for the 7 slots of a free joint.
  An unnamed joint (the Go2's root) is named after its body: "@base[k]". Unreal resolves both forms (RaceNames.h)."""
  out = []
  for j in range(m.njnt):
    name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or "@" + mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.jnt_bodyid[j])
    n = {mujoco.mjtJoint.mjJNT_FREE: 7, mujoco.mjtJoint.mjJNT_BALL: 4}.get(mujoco.mjtJoint(m.jnt_type[j]), 1)
    out += [name] if n == 1 else [f"{name}[{k}]" for k in range(n)]
  return out


def option(m):
  o = {k: (int(getattr(m.opt, k)) if isinstance(getattr(m.opt, k), (int, np.integer)) else float(getattr(m.opt, k))) for k in OPT_SCALARS}
  o.update({k: [float(x) for x in getattr(m.opt, k)] for k in OPT_VECTORS})
  return o


def floats(x):
  return [float(v) for v in np.asarray(x).ravel()]


def model_numbers(m):
  """The training model's own numbers, by name, for Unreal to write back over URLab's rebuild of it.

  URLab rebuilds the model from its components and gets some of it wrong (measured 2026-11-10 on the Go2): the free
  joint picks up the default class's damping 0.5 and armature 0.01 (MuJoCo never applies defaults to a free joint),
  the foot sites lose their positions, and every number passes through single precision. Geoms are matched by their
  body and their order inside it (URLab keeps both), since most of the Go2's are unnamed. Visual-only geoms are left
  alone: URLab re-centres their meshes, which moves the drawing, not the physics."""
  T = mujoco.mjtObj
  name = lambda t, i: mujoco.mj_id2name(m, t, i)  # noqa: E731
  # The creature is the body tree under its root; everything else in the scene (floor, testbed cubes) is "optional":
  # written when the model has it, skipped quietly on a track that does not.
  root = mujoco.mj_name2id(m, T.mjOBJ_BODY, G.ROOT_BODY)
  mine = lambda b: int(m.body_rootid[b]) == root  # noqa: E731
  opt = lambda b: {} if mine(b) else {"optional": True}  # noqa: E731
  bodies = {name(T.mjOBJ_BODY, b): {"mass": float(m.body_mass[b]), "inertia": floats(m.body_inertia[b]), "ipos": floats(m.body_ipos[b]),
                                    "iquat": floats(m.body_iquat[b]), "pos": floats(m.body_pos[b]), "quat": floats(m.body_quat[b]), **opt(b)}
            for b in range(1, m.nbody)}
  for k in ("pos", "quat"):   # a free body's pose is its joint's state: on a track the race places it, not the card
    bodies[G.ROOT_BODY].pop(k)
  joints = []
  for j in range(m.njnt):
    d0, nd = int(m.jnt_dofadr[j]), {0: 6, 1: 3}.get(int(m.jnt_type[j]), 1)
    joints.append({"name": name(T.mjOBJ_JOINT, j) or "", "body": name(T.mjOBJ_BODY, m.jnt_bodyid[j]), **opt(m.jnt_bodyid[j]),
                   "range": floats(m.jnt_range[j]), "pos": floats(m.jnt_pos[j]), "axis": floats(m.jnt_axis[j]),
                   "stiffness": float(m.jnt_stiffness[j]), "margin": float(m.jnt_margin[j]),
                   "solref": floats(m.jnt_solref[j]), "solimp": floats(m.jnt_solimp[j]),
                   "damping": floats(m.dof_damping[d0:d0 + nd]), "armature": floats(m.dof_armature[d0:d0 + nd]),
                   "frictionloss": floats(m.dof_frictionloss[d0:d0 + nd])})
  actuators = {name(T.mjOBJ_ACTUATOR, a): {"gainprm": floats(m.actuator_gainprm[a]), "biasprm": floats(m.actuator_biasprm[a]),
                                           "ctrlrange": floats(m.actuator_ctrlrange[a]), "forcerange": floats(m.actuator_forcerange[a]),
                                           "gear": floats(m.actuator_gear[a])}
               for a in range(m.nu)}
  sites = {name(T.mjOBJ_SITE, s): {"pos": floats(m.site_pos[s]), "quat": floats(m.site_quat[s])} for s in range(m.nsite)}
  geoms, seen = [], {}
  for g in range(m.ngeom):
    b = int(m.geom_bodyid[g])
    k = seen.get(b, 0); seen[b] = k + 1
    if not mine(b):
      # world and testbed geoms (floor, cubes): optional, by name. On a track the track fingerprint owns the world.
      gname = name(T.mjOBJ_GEOM, g)
      if gname:
        geoms.append({"name": gname, "optional": True, "type": int(m.geom_type[g]), "pos": floats(m.geom_pos[g]),
                      "quat": floats(m.geom_quat[g]), "size": floats(m.geom_size[g]), "friction": floats(m.geom_friction[g]),
                      "margin": float(m.geom_margin[g]), "gap": float(m.geom_gap[g]), "solref": floats(m.geom_solref[g]),
                      "solimp": floats(m.geom_solimp[g]), "solmix": float(m.geom_solmix[g])})
      continue
    if not (m.geom_contype[g] or m.geom_conaffinity[g]):
      # visual only: just the margin and gap (they feed body_margin, which the broadphase reads); never the pose,
      # which URLab's re-centred mesh needs
      geoms.append({"body": name(T.mjOBJ_BODY, b) or "world", "index": k, "type": int(m.geom_type[g]), "visual": True,
                    "margin": float(m.geom_margin[g]), "gap": float(m.geom_gap[g])})
      continue
    geoms.append({"body": name(T.mjOBJ_BODY, b) or "world", "index": k, "type": int(m.geom_type[g]),
                  "pos": floats(m.geom_pos[g]), "quat": floats(m.geom_quat[g]), "size": floats(m.geom_size[g]),
                  "friction": floats(m.geom_friction[g]), "margin": float(m.geom_margin[g]), "gap": float(m.geom_gap[g]),
                  "solref": floats(m.geom_solref[g]), "solimp": floats(m.geom_solimp[g]), "solmix": float(m.geom_solmix[g])})
  return {"bodies": bodies, "joints": joints, "actuators": actuators, "sites": sites, "geoms": geoms}


def go2_fingerprint():
  m = mujoco.MjModel.from_xml_path(str(G.SCENE_XML))
  assert abs(m.opt.timestep - G.SIM_DT) < 1e-12 and m.nu == G.NU
  return {
      "creature": "go2",
      "mujoco": MUJOCO_VERSION,
      "source": "training/assets/go2/scene_porace.xml",
      "option": option(m),
      "decimation": G.DECIMATION,
      "action_scale": G.ACTION_SCALE,
      "cmd_slew": G.CMD_SLEW,
      "root_body": G.ROOT_BODY,
      "imu_site": G.IMU_SITE,
      "gyro_sensor": G.GYRO_SENSOR,
      "linvel_sensor": G.LOCAL_LINVEL_SENSOR,
      "joints": G.JOINT_NAMES,
      "actuators": G.ACTUATOR_NAMES,
      "default_pose": G.DEFAULT_POSE,
      "obs_joystick": G.OBS_JOYSTICK,
      "obs_getup": G.OBS_GETUP,
      "qpos_names": qpos_names(m),
      "qpos_home": [float(x) for x in m.key_qpos[0]],
      "model": model_numbers(m),
  }


def header():
  f = lambda x: f"{x!r}"  # noqa: E731 - shortest round-trip repr of a Python float
  pose = ", ".join(f"{x}f" for x in G.DEFAULT_POSE)
  return f"""// GENERATED by training/contract.py - do not edit. Regenerate: python training/contract.py
#pragma once

namespace RaceContract
{{
	inline constexpr int MuJoCoVersionHeader = {int(MUJOCO_VERSION.split('.')[0]) * 1000000 + int(MUJOCO_VERSION.split('.')[1]) * 1000 + int(MUJOCO_VERSION.split('.')[2])};	// mjVERSION_HEADER the brains are gated on ({MUJOCO_VERSION})

	namespace Go2
	{{
		inline constexpr double SimDt = {f(G.SIM_DT)};		// s per physics step (250 Hz)
		inline constexpr int Decimation = {G.DECIMATION};		// physics steps per brain decision (50 Hz)
		inline constexpr int Nu = {G.NU};				// motors: FL, FR, RL, RR x hip, thigh, calf
		inline constexpr int ObsJoystick = {G.OBS_JOYSTICK};		// local_linvel 3, gyro 3, gravity 3, q - default 12, qvel 12, last action 12, command 3
		inline constexpr int ObsGetup = {G.OBS_GETUP};			// gyro 3, gravity 3, q - default 12, qvel 12, last action 12
		inline constexpr float ActionScale = {f(G.ACTION_SCALE)}f;	// rad per unit action
		inline constexpr float CmdSlewStep = {f(G.CMD_SLEW_STEP)}f;	// command change per decision ({f(G.CMD_SLEW)} per second)
		inline constexpr float DefaultPose[Nu] = {{ {pose} }};
	}}
}}
"""


TARGETS = {
    ROOT / "training" / "models" / "go2_fingerprint.json": lambda: json.dumps(go2_fingerprint(), indent=1) + "\n",
    ROOT / "Source" / "PoRaceUnreal" / "RaceContract.gen.h": header,
}


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--check", action="store_true", help="do not write; exit 1 if a generated file differs")
  a = ap.parse_args()
  assert mujoco.__version__ == MUJOCO_VERSION, f"run with mujoco=={MUJOCO_VERSION} (found {mujoco.__version__})"
  stale = []
  for path, make in TARGETS.items():
    text = make()
    old = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None
    if old == text:
      print(f"up to date  {path.relative_to(ROOT)}")
    elif a.check:
      stale.append(path); print(f"STALE       {path.relative_to(ROOT)}")
    else:
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text(text, encoding="utf-8", newline="\n"); print(f"wrote       {path.relative_to(ROOT)}")
  return 1 if stale else 0


if __name__ == "__main__":
  sys.exit(main())
