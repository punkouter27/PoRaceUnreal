"""The fingerprints' exact numbers over a loaded model: Source/PoRaceUnreal/RaceModel.cpp in Python.

Unreal needs it because URLab rebuilds the model in single precision with a few mistakes (docs/20261110/slice1.md).
Python needs it because MjSpec.to_xml() writes some numbers with 6 significant digits: a track file's Matt has capsule
half-lengths like 0.207067 where training had 0.20706704 (found in Slice 3). Both runtimes therefore apply the
same numbers to whatever they loaded, then mj_setConst, and step the training model's values.
"""
import mujoco

from go2.sim import find

T = mujoco.mjtObj
NREF, NIMP = 2, 5


def _put(dst, values):
  dst[:len(values)] = values


def apply_option(m, option):
  for k, v in option.items():
    if isinstance(v, list):
      getattr(m.opt, k)[:] = v
    else:
      setattr(m.opt, k, v)


def apply_numbers(m, numbers, prefix=""):
  """A fingerprint's "model" or "world" object onto m. Returns the count of required names that were missing."""
  missing = 0

  def miss(o, what):
    nonlocal missing
    if not o.get("optional"):
      missing += 1
      print(f"model numbers: no {what} (prefix {prefix!r})")

  for name, o in numbers.get("bodies", {}).items():
    b = find(m, T.mjOBJ_BODY, m.nbody, prefix + name)
    if b < 0:
      miss(o, f"body {name}"); continue
    if "mass" in o: m.body_mass[b] = o["mass"]
    for k, dst in (("inertia", m.body_inertia), ("ipos", m.body_ipos), ("iquat", m.body_iquat), ("pos", m.body_pos), ("quat", m.body_quat)):
      if k in o: _put(dst[b], o[k])
  for o in numbers.get("joints", []):
    if o["name"]:
      j = find(m, T.mjOBJ_JOINT, m.njnt, prefix + o["name"])
    else:
      b = find(m, T.mjOBJ_BODY, m.nbody, prefix + o["body"])
      j = int(m.body_jntadr[b]) if b >= 0 and m.body_jntnum[b] > 0 else -1
    if j < 0:
      miss(o, f"joint {o['name']} of body {o['body']}"); continue
    nd = {0: 6, 1: 3}.get(int(m.jnt_type[j]), 1)
    d0 = int(m.jnt_dofadr[j])
    for k, dst in (("range", m.jnt_range[j]), ("pos", m.jnt_pos[j]), ("axis", m.jnt_axis[j]), ("solref", m.jnt_solref[j]), ("solimp", m.jnt_solimp[j])):
      if k in o: _put(dst, o[k])
    if "stiffness" in o: m.jnt_stiffness[j] = o["stiffness"]
    if "margin" in o: m.jnt_margin[j] = o["margin"]
    for k, dst in (("damping", m.dof_damping), ("armature", m.dof_armature), ("frictionloss", m.dof_frictionloss)):
      if k in o: dst[d0:d0 + nd] = o[k][:nd]
  for name, o in numbers.get("actuators", {}).items():
    a = find(m, T.mjOBJ_ACTUATOR, m.nu, prefix + name)
    if a < 0:
      miss(o, f"actuator {name}"); continue
    for k, dst in (("gainprm", m.actuator_gainprm[a]), ("biasprm", m.actuator_biasprm[a]), ("ctrlrange", m.actuator_ctrlrange[a]),
                   ("forcerange", m.actuator_forcerange[a]), ("gear", m.actuator_gear[a])):
      if k in o: _put(dst, o[k])
  for name, o in numbers.get("sites", {}).items():
    s = find(m, T.mjOBJ_SITE, m.nsite, prefix + name)
    if s < 0:
      miss(o, f"site {name}"); continue
    for k, dst in (("pos", m.site_pos[s]), ("quat", m.site_quat[s])):
      if k in o: _put(dst, o[k])
  for o in numbers.get("geoms", []):
    if o.get("name"):
      g = find(m, T.mjOBJ_GEOM, m.ngeom, prefix + o["name"])
      what = f"geom {o['name']}"
    else:
      b = 0 if o["body"] == "world" else find(m, T.mjOBJ_BODY, m.nbody, prefix + o["body"])
      g = int(m.body_geomadr[b]) + o["index"] if b >= 0 and o["index"] < m.body_geomnum[b] else -1
      what = f"geom {o['index']} of body {o['body']}"
    if g < 0 or int(m.geom_type[g]) != o["type"]:
      miss(o, what); continue
    m.geom_margin[g] = o["margin"]
    m.geom_gap[g] = o["gap"]
    if o.get("visual"):
      continue
    for k, dst in (("pos", m.geom_pos[g]), ("quat", m.geom_quat[g]), ("size", m.geom_size[g]), ("friction", m.geom_friction[g]),
                   ("solref", m.geom_solref[g]), ("solimp", m.geom_solimp[g])):
      if k in o: _put(dst, o[k])
    if "solmix" in o: m.geom_solmix[g] = o["solmix"]
  return missing
