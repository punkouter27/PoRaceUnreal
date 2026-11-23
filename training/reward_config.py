"""The one source of reward penalty weights and curriculum thresholds (training/reward_config.json).

The trainers (go2/joystick.py, matt/env.py, eval.py) read these values; the Unreal DataAsset URaceRewardConfig mirrors
them and tests/test_reward_config.py keeps the two in step. Importable without JAX.
"""

import json
import math
from pathlib import Path

PATH = Path(__file__).resolve().parent / "reward_config.json"
PENALTY_KEYS = ("torque_sq", "joint_ang_vel_sq", "action_rate_sq", "foot_slip")
# The per-step reward metric (reward/<name>, already weighted) each env reports for a penalty, in order of preference:
# go2/joystick.py names them action_rate / feet_slip; matt/env.py (and Grandma) has the config's foot_slip and the stock
# pelvis-based feet_slip, so foot_slip is looked up first. The stroller (wheels, no feet) has only action_rate.
PENALTY_METRICS = {
    "torque_sq": ("torque_sq",),
    "joint_ang_vel_sq": ("joint_ang_vel_sq",),
    "action_rate_sq": ("action_rate",),
    "foot_slip": ("foot_slip", "feet_slip"),
}
EVAL_PREFIX = "eval/episode_reward/"  # brax's evaluator: eval/episode_<state.metrics key>, summed over an episode


def load(path: Path = PATH) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    pen = cfg["penalties"]
    missing = [k for k in PENALTY_KEYS if k not in pen]
    if missing:
        raise ValueError(f"{path}: penalties missing {missing}")
    for k in PENALTY_KEYS:
        w = float(pen[k])
        if not math.isfinite(w) or w > 0:
            raise ValueError(f"{path}: penalty {k} must be a finite weight <= 0, got {w}")
    for stage in cfg["curriculum"]:
        if not 0.0 < float(stage["threshold"]) <= 1.0:
            raise ValueError(f"{path}: stage {stage['stage']} threshold must be in (0, 1]")
    return cfg


def penalty_log(metrics: dict, prefix: str = EVAL_PREFIX) -> dict[str, float]:
    """One value per penalty term, as pen_<term> (pen_torque_sq, pen_joint_ang_vel_sq, pen_action_rate_sq, pen_foot_slip):
    the weighted penalty the metrics carry for it (an eval episode's sum for brax eval metrics, a step's value for
    state.metrics with prefix "reward/"). Terms an env does not compute are left out, never reported as 0."""
    out = {}
    for term in PENALTY_KEYS:
        for name in PENALTY_METRICS[term]:
            if prefix + name in metrics:
                out[f"pen_{term}"] = float(metrics[prefix + name])
                break
    return out


def penalties() -> dict[str, float]:
    return {k: float(v) for k, v in load()["penalties"].items() if k in PENALTY_KEYS}


def stage_threshold(stage: str) -> float:
    for s in load()["curriculum"]:
        if s["stage"] == stage:
            return float(s["threshold"])
    raise KeyError(f"no curriculum stage {stage!r} in {PATH.name}")


def stage_need(stage: str, seeds: int, round_up: bool = False) -> int:
    """Episodes out of `seeds` that must pass the rung: threshold * seeds, rounded down (the rung evals) or up (the
    steeplechase graduation gate). The epsilon absorbs float noise (0.9 * 10 = 9.000000000000002)."""
    x = stage_threshold(stage) * seeds
    return math.ceil(x - 1e-9) if round_up else math.floor(x + 1e-9)
