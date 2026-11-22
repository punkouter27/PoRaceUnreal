"""The race models obey the articulated-agent physics rules (what Unreal runs: URLab imports these same MJCFs).

Earth gravity; every limb joint limited (only the stroller's free-spinning wheels are not); limb actuators are PD
position servos (kp, -kp, -kv bias) with force limits; MuJoCo's parent-child contact filter is on (no self-collision
between connected bones); every geom has ground friction.
"""

import json
from pathlib import Path

import mujoco
import pytest

ROOT = Path(__file__).resolve().parent.parent
TRACKS = sorted((ROOT / "training" / "models" / "tracks").glob("*_fingerprint.json"))
WHEELS = {"stroller_wheel_front", "stroller_wheel_rear_l", "stroller_wheel_rear_r"}
# the stroller is a vehicle: its steering servo and wheel motors are bounded by ctrlrange, not forcerange
VEHICLE_ACTUATORS = {"stroller_steer", "stroller_wheel_rear_l", "stroller_wheel_rear_r"}


def _model(fp):
    return mujoco.MjModel.from_xml_path(str(ROOT / json.loads(fp.read_text(encoding="utf-8"))["model"]))


def _name(m, kind, i):
    return mujoco.mj_id2name(m, kind, i) or ""


@pytest.mark.parametrize("fp", TRACKS, ids=lambda p: p.stem)
def test_articulated_physics_rules(fp):
    m = _model(fp)
    assert tuple(m.opt.gravity) == pytest.approx((0.0, 0.0, -9.81))
    assert not m.opt.disableflags & mujoco.mjtDisableBit.mjDSBL_FILTERPARENT

    # compare as int: enum == numpy int is False on Linux (CI) but True on Windows
    limb_types = (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE))
    hinges = [j for j in range(m.njnt) if int(m.jnt_type[j]) in limb_types]
    unlimited = {_name(m, mujoco.mjtObj.mjOBJ_JOINT, j) for j in hinges if not m.jnt_limited[j]}
    assert hinges and unlimited <= WHEELS, unlimited

    limb_pd = 0
    for a in range(m.nu):
        name = _name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, a)
        assert m.actuator_ctrllimited[a], name
        if name in VEHICLE_ACTUATORS:
            continue
        kp, bias = m.actuator_gainprm[a, 0], m.actuator_biasprm[a]
        assert kp > 0 and bias[1] == pytest.approx(-kp) and bias[2] <= 0, f"{name}: not a PD position servo"
        assert m.actuator_forcelimited[a], f"{name}: no force limit"
        limb_pd += 1
    assert limb_pd >= 12

    assert (m.geom_friction[:, 0] > 0.3).all()
