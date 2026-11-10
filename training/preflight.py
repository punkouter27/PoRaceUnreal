"""Preflight config snapshot (proposals r3 D8; AGENTS.md: tag each checkpoint with its interface and physics versions).

Before a run initialises its policy, train.py calls `check(env, cfg, logdir, restore_params)`:
  - physics tag: sha256 over the compiled model's simulation fields (option block, masses, inertias, joint ranges,
    actuator gains / bias / force ranges, geom sizes / friction / solref / solimp). A changed MJCF, gain or solver
    option changes the tag; a rename or a visual-only edit does not.
  - interface tag: observation size, action size, actuator order (names) and control dt: the network's layout.
  - clock: the gait clock settings (recorded; the Unity runtime must use the same, MattSpec.GaitHzSlope).
  - sanity: gravity is -9.81 m/s^2 straight down, no NaN in the model, and the first reset's obs is finite.
It writes <logdir>/tags.json. When restoring from params.pkl it reads the tags.json beside it (or <name>.tags.json):
a different interface tag stops the run (the network's input / output layout would be wrong); a different physics tag
or clock is a warning (fine-tuning across such a change is allowed and deliberate, and the log records it).

  python preflight.py --env matt [--set realism.gait_hz_slope=0.2]     # print the tags without training
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

PHYSICS_FIELDS = ("body_mass", "body_inertia", "body_ipos", "jnt_range", "jnt_stiffness", "dof_damping", "dof_armature",
                  "dof_frictionloss", "actuator_gainprm", "actuator_biasprm", "actuator_forcerange", "actuator_ctrlrange",
                  "geom_size", "geom_friction", "geom_solref", "geom_solimp", "geom_contype", "geom_conaffinity")
OPTION_FIELDS = ("timestep", "gravity", "impratio", "iterations", "ls_iterations", "integrator", "cone", "o_solref")


def _digest(parts):
  h = hashlib.sha256()
  for name, arr in parts:
    h.update(name.encode()); h.update(np.ascontiguousarray(np.asarray(arr, np.float64)).tobytes())
  return h.hexdigest()[:16]


def physics_tag(m):
  parts = [(f, getattr(m, f)) for f in PHYSICS_FIELDS if hasattr(m, f)]
  parts += [("opt." + f, getattr(m.opt, f)) for f in OPTION_FIELDS if hasattr(m.opt, f)]
  return _digest(parts)


def interface_tag(m, obs_size, act_size, ctrl_dt):
  names = [m.actuator(i).name for i in range(m.nu)]
  h = hashlib.sha256(json.dumps([obs_size, act_size, round(float(ctrl_dt), 6), names]).encode())
  return h.hexdigest()[:16]


def tags(env, cfg):
  m = env.mj_model
  obs = env.observation_size
  obs_size = obs["state"][0] if isinstance(obs, dict) else int(obs)
  rz = cfg.get("realism", None)
  clock = {"gait_hz_slope": float(rz.gait_hz_slope), "gait_hz_v0": float(rz.gait_hz_v0)} if rz is not None and "gait_hz_slope" in rz else {}
  problems = []
  g = np.asarray(m.opt.gravity, float)
  if not np.allclose(g, [0, 0, -9.81], atol=1e-3): problems.append(f"gravity {g.tolist()} (want 0 0 -9.81)")
  for f in PHYSICS_FIELDS:
    if hasattr(m, f) and not np.isfinite(np.asarray(getattr(m, f), float)).all(): problems.append(f"non-finite {f}")
  # creature = the model file's stem (matt_porace, grandma_porace, scene_porace ...): AGENTS.md "no character reuses
  # another's brain", so a restore across creatures is refused even when the interface (Matt / Grandma: 103 -> 29) matches
  xml = getattr(env, "XML_PATH", None) or getattr(env, "_xml_path", None) or ""
  creature = Path(str(xml)).stem or type(env).__name__
  return dict(creature=creature, physics=physics_tag(m), interface=interface_tag(m, obs_size, env.action_size, env.dt),
              obs_size=int(obs_size), act_size=int(env.action_size), ctrl_dt=float(env.dt), sim_dt=float(m.opt.timestep),
              nq=int(m.nq), nv=int(m.nv), nu=int(m.nu), clock=clock, problems=problems)


def _restore_tags(restore_params):
  p = Path(restore_params)
  for c in (p.parent / "tags.json", p.with_suffix(".tags.json")):
    if c.exists(): return json.loads(c.read_text()), c
  return None, None


def check(env, cfg, logdir, restore_params=None):
  t = tags(env, cfg)
  if t["problems"]: sys.exit("PREFLIGHT FAIL: " + "; ".join(t["problems"]))
  if restore_params:
    old, where = _restore_tags(restore_params)
    t["restored_from"] = str(restore_params)
    if old is None:
      me = t["creature"].split("_")[0]
      other = [c for c in ("matt", "grandma", "g1", "go2") if c != me and c in Path(restore_params).name.lower()]
      if other:
        sys.exit(f"PREFLIGHT FAIL: untagged {restore_params} looks like {other[0]}'s policy, this run is {me} (one brain per character)")
      print(f"PREFLIGHT: {restore_params} has no tags.json (pre-r3 checkpoint); obs {t['obs_size']} / act {t['act_size']} must match it")
    else:
      if old.get("creature") and old["creature"] != t["creature"]:
        sys.exit(f"PREFLIGHT FAIL: {where} is {old['creature']}'s policy, this run is {t['creature']} (one brain per character)")
      if old.get("interface") != t["interface"]:
        sys.exit(f"PREFLIGHT FAIL: interface {t['interface']} != {old.get('interface')} in {where} (obs/act layout changed)")
      if old.get("clock", {}) != t["clock"]:
        print(f"PREFLIGHT WARN: gait clock {t['clock'] or 'fixed'} != {old.get('clock') or 'fixed'} in {where}")
      if old.get("physics") != t["physics"]:
        print(f"PREFLIGHT WARN: physics {t['physics']} != {old.get('physics')} in {where}: fine-tuning across a physics change")
  if logdir is not None:
    Path(logdir).mkdir(parents=True, exist_ok=True); (Path(logdir) / "tags.json").write_text(json.dumps(t, indent=1))
  print(f"PREFLIGHT OK: physics {t['physics']} interface {t['interface']} obs {t['obs_size']} act {t['act_size']} "
        f"ctrl {t['ctrl_dt']} s sim {t['sim_dt']} s clock {t['clock'] or 'fixed'}", flush=True)
  return t


if __name__ == "__main__":
  import argparse
  sys.argv[0] = "train.py"
  import train
  ap = argparse.ArgumentParser(); ap.add_argument("--env", default="matt"); ap.add_argument("--set", action="append", default=[])
  a = ap.parse_args()

  def tweak(cfg):
    import ast
    for kv in a.set:
      key, val = kv.split("=", 1); *path, leaf = key.split("."); node = cfg
      for p in path: node = node[p]
      node[leaf] = ast.literal_eval(val)
    return cfg
  env, cfg = train.make_env(a.env, num_worlds=1, tweak=tweak)
  print(json.dumps(tags(env, cfg), indent=1))
