"""The role interface must cover every body this repo races and reproduce each creature's golden.

The goldens are written by ``global/UNITE/tools/role_obs.py`` — the reference this module has to agree with to
1e-5. A checkout without ``global/`` skips instead of inventing a layout, and a body with no contract is a
reported gap (R28), not something to special-case.
"""

import json
import pathlib
import types

import numpy as np
import pytest
from racelib import role_obs

ROOT = pathlib.Path(__file__).resolve().parents[1]
FINGERPRINTS = sorted((ROOT / "training" / "models").glob("*_fingerprint.json"))
# R28: bodies this repo races that global/UNITE has no creature for. Reported, never invented.
EXPECTED_WITHOUT_CONTRACT = {"stroller_fingerprint.json"}
TOLERANCE = 1e-5

pytestmark = pytest.mark.skipif(not role_obs.available(), reason="global/UNITE is not present in this checkout")

CREATURES = ("g1", "go2", "grandma", "matthew", "streetball_humanoid", "unitree_r1_a5")


@pytest.fixture(scope="module")
def joint_names():
    return {cid: [j["name"] for j in role_obs.contract_for(cid)["morphology"]["joints"]] for cid in CREATURES}


@pytest.mark.parametrize("cid", CREATURES)
def test_reproduces_the_golden(cid, joint_names):
    gold = role_obs.CREATURES / cid / "golden_role_obs.npz"
    if not gold.is_file():
        pytest.skip(f"no golden_role_obs.npz for {cid}")
    contract = role_obs.contract_for(cid)
    iface = role_obs.RoleInterface(contract, joint_names[cid])
    z = np.load(gold)
    assert str(z["interface_sha256_16"][0]) == contract["hashes"]["interface_sha256_16"]
    index = {n: i for i, n in enumerate(joint_names[cid])}
    worst = 0.0
    for i in range(z["obs"].shape[0]):
        state = role_obs.RoleState(
            q=np.zeros(len(index)),
            dq=np.zeros(len(index)),
            imu_quat=np.asarray(z["pelvis_quat"][i], dtype=np.float64),
            gyro=np.asarray(z["pelvis_angvel"][i], dtype=np.float64),
        )
        for name, value in json.loads(z["joint_pos_json"][i]).items():
            state.q[index[name]] = value
        for name, value in json.loads(z["joint_vel_json"][i]).items():
            state.dq[index[name]] = value
        got = iface.build(
            state,
            np.asarray(z["prev_action"][i], dtype=np.float64),
            np.asarray(z["command"][i], dtype=np.float64),
            t=float(z["gait_phase"][i]) * role_obs.DEFAULT_GAIT_PERIOD_S,
        )
        worst = max(worst, float(np.max(np.abs(got - z["obs"][i]))))
    assert worst <= TOLERANCE, f"{cid}: max deviation {worst:.3g}"


def test_every_raced_body_maps_to_a_contract():
    """Every body fingerprint must resolve to a contract, except the ones listed as an R28 gap."""
    assert FINGERPRINTS, "no *_fingerprint.json under training/models"
    missing = []
    for path in FINGERPRINTS:
        fp = json.loads(path.read_text(encoding="utf-8"))
        try:
            role_obs.RoleInterface.from_fingerprint(fp)
        except role_obs.ContractMismatch:
            missing.append(path.name)
    assert set(missing) == EXPECTED_WITHOUT_CONTRACT, f"unexpected contract gaps: {sorted(set(missing))}"


def test_masked_roles_are_zero(joint_names):
    contract = role_obs.contract_for("matthew")
    iface = role_obs.RoleInterface(contract, joint_names["matthew"])
    n = len(joint_names["matthew"])
    state = role_obs.RoleState(
        q=np.full(n, 0.4), dq=np.full(n, 1.0), imu_quat=np.array([1.0, 0, 0, 0]), gyro=np.zeros(3)
    )
    obs = iface.build(state, np.ones(28))
    mask = iface.obs.slice_of(obs, "role_mask")
    assert int(mask.sum()) == sum(contract["roles"]["mask"])
    for i, k in enumerate(contract["roles"]["mask"]):
        if k == 0:
            for slot in ("joint_pos_rel", "joint_vel", "prev_action"):
                assert iface.obs.slice_of(obs, slot)[i] == 0.0
    assert abs(float(iface.obs.slice_of(obs, "morphology_onehot").sum()) - 1.0) < 1e-6


def test_zero_action_holds_the_nominal_pose(joint_names):
    contract = role_obs.contract_for("go2")
    iface = role_obs.RoleInterface(contract, joint_names["go2"])
    q = iface.targets(np.zeros(28))
    assert np.allclose(q, iface.action.q_default)


def test_action_is_clipped_to_soft_limits(joint_names):
    contract = role_obs.contract_for("go2")
    iface = role_obs.RoleInterface(contract, joint_names["go2"])
    q = iface.targets(np.full(28, 5.0))
    amap = iface.action
    assert np.all(q >= amap.lo - 1e-12) and np.all(q <= amap.hi + 1e-12)


def _fake_policy(tmp_path, contract, *, corrupt=False, name="policy"):
    import hashlib

    onnx = tmp_path / f"{name}.onnx"
    onnx.write_bytes(b"stub weights; only the hash is checked at load")
    sc = {
        "policy_name": name,
        "creature": contract["creature"],
        "n_obs": 131,
        "n_action": 28,
        "interface_sha256": contract["hashes"]["interface_sha256"],
        "morphology_sha256": contract["hashes"]["morphology_sha256"],
        "physics_sha256": contract["hashes"]["physics_sha256"],
        "policy_sha256": hashlib.sha256(onnx.read_bytes()).hexdigest(),
    }
    if corrupt:
        sc["interface_sha256"] = "0" * 64
    onnx.with_suffix(".json").write_text(json.dumps(sc), encoding="utf-8")
    return types.SimpleNamespace(path=onnx, num_obs=131, num_actions=28)


def test_conforming_policy_is_accepted(tmp_path, joint_names):
    contract = role_obs.contract_for("go2")
    assert role_obs.for_policy(_fake_policy(tmp_path, contract), joint_names["go2"], contract).n_obs == 131


def test_stale_sidecar_is_refused(tmp_path, joint_names):
    contract = role_obs.contract_for("go2")
    with pytest.raises(role_obs.ContractMismatch):
        role_obs.for_policy(_fake_policy(tmp_path, contract, corrupt=True), joint_names["go2"], contract)


def test_foreign_brain_is_loadable_but_flagged(tmp_path, joint_names):
    contract = role_obs.contract_for("go2")
    nn = _fake_policy(tmp_path, contract, name="foreign")
    sc = json.loads(nn.path.with_suffix(".json").read_text(encoding="utf-8"))
    sc["creature"] = "unitree_r1_a5"
    sc["morphology_sha256"] = "a" * 64
    nn.path.with_suffix(".json").write_text(json.dumps(sc), encoding="utf-8")
    iface = role_obs.for_policy(nn, joint_names["go2"], contract)
    assert iface.foreign and iface.trained_for == "unitree_r1_a5"


def test_wrong_shape_is_refused(joint_names):
    contract = role_obs.contract_for("go2")
    nn = types.SimpleNamespace(path=pathlib.Path("nope.onnx"), num_obs=83, num_actions=24)
    with pytest.raises(role_obs.ContractMismatch):
        role_obs.for_policy(nn, joint_names["go2"], contract)
