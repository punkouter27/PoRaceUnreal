"""training/reward_config.json is valid and is what the trainers use (no duplicated literals)."""

import json
from pathlib import Path

import pytest
import reward_config

ROOT = Path(__file__).resolve().parent.parent


def test_file_is_valid():
    cfg = reward_config.load()
    assert set(reward_config.PENALTY_KEYS) <= set(cfg["penalties"])
    stages = [s["stage"] for s in cfg["curriculum"]]
    assert len(stages) == len(set(stages))
    raw = json.loads((ROOT / "training" / "reward_config.json").read_text(encoding="utf-8"))
    assert reward_config.penalties() == {k: float(raw["penalties"][k]) for k in reward_config.PENALTY_KEYS}


@pytest.mark.parametrize(
    ("stage", "seeds", "round_up", "need"),
    [("r0", 10, False, 10), ("r1", 10, False, 10), ("r2", 10, False, 9), ("bank", 10, False, 9),
     ("steeple", 100, True, 90), ("steeple", 300, True, 270), ("steeple", 7, True, 7)],
)  # fmt: skip
def test_rung_pass_counts(stage, seeds, round_up, need):
    assert reward_config.stage_need(stage, seeds, round_up=round_up) == need


def test_bad_weight_rejected(tmp_path):
    raw = json.loads(reward_config.PATH.read_text(encoding="utf-8"))
    raw["penalties"]["torque_sq"] = 0.5
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        reward_config.load(bad)


def test_trainers_read_the_file():
    pytest.importorskip("mujoco_playground")
    from go2 import joystick
    from grandma import env as grandma_env
    from matt import env as matt_env

    pen = reward_config.penalties()
    go2 = joystick.default_config().reward_config.scales
    assert (go2.torque_sq, go2.joint_ang_vel_sq, go2.action_rate, go2.feet_slip) == (
        pen["torque_sq"],
        pen["joint_ang_vel_sq"],
        pen["action_rate_sq"],
        pen["foot_slip"],
    )
    for human in (matt_env.default_config(), grandma_env.default_config()):
        s = human.reward_config.scales
        assert (s.torque_sq, s.joint_ang_vel_sq, s.action_rate, s.foot_slip) == (
            pen["torque_sq"],
            pen["joint_ang_vel_sq"],
            pen["action_rate_sq"],
            pen["foot_slip"],
        )
