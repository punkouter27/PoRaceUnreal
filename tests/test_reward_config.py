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


def test_penalty_log_one_value_per_term():
    """brax eval metrics -> pen_torque_sq, pen_joint_ang_vel_sq, pen_action_rate_sq, pen_foot_slip, each separately;
    the Go2's names (action_rate, feet_slip) map to the shared terms; terms an env lacks are left out, not zeroed."""
    go2 = {
        "eval/episode_reward": 12.0,
        "eval/episode_reward/torque_sq": -0.5,
        "eval/episode_reward/joint_ang_vel_sq": -0.25,
        "eval/episode_reward/action_rate": -0.125,
        "eval/episode_reward/feet_slip": -2.0,
        "eval/episode_reward/feet_slip_std": 9.0,
    }
    assert reward_config.penalty_log(go2) == {
        "pen_torque_sq": -0.5,
        "pen_joint_ang_vel_sq": -0.25,
        "pen_action_rate_sq": -0.125,
        "pen_foot_slip": -2.0,
    }
    matt = {"eval/episode_reward/foot_slip": -1.0, "eval/episode_reward/feet_slip": -7.0}
    assert reward_config.penalty_log(matt) == {"pen_foot_slip": -1.0}  # the config's term, not the stock pelvis slip
    stroller = {"eval/episode_reward/action_rate": -0.3, "eval/episode_reward/torques": -1.0}
    assert reward_config.penalty_log(stroller) == {"pen_action_rate_sq": -0.3}


def test_trainer_logs_every_penalty_term():
    """train.py's progress callback writes reward_config.penalty_log to TensorBoard (penalty/pen_<term>) and prints it
    (checked in the source: importing train.py needs the GPU trainer stack; nothing is trained)."""
    import ast

    tree = ast.parse((ROOT / "training" / "train.py").read_text(encoding="utf-8"))
    progress = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "progress")
    src = ast.unparse(progress)
    assert "reward_config.penalty_log(metrics)" in src
    assert "writer.add_scalar(f'penalty/{k}', v, num_steps)" in src
