"""Every reward penalty (torque^2, joint angular velocity^2, action rate, foot slip) is actually charged by the trainers.

A few environment steps with random actions on a forward command (CPU, jit): each penalty's per-step reward metric
must be non-zero and negative. Shipped brains predate some of these terms (see docs/showcase.md); nothing is trained.
"""

import pytest

pytest.importorskip("mujoco_playground")
jax = pytest.importorskip("jax")
jp = jax.numpy


def _go2():
    from go2 import joystick

    return joystick.Joystick(), ("torque_sq", "joint_ang_vel_sq", "action_rate", "feet_slip")


def _matt():
    from matt import env as matt_env

    return matt_env.MattJoystick(), ("torque_sq", "joint_ang_vel_sq", "action_rate", "foot_slip")


@pytest.mark.parametrize("make", [_go2, _matt], ids=["go2", "matt"])
def test_every_penalty_is_charged(make):
    env, terms = make()
    reset, step = jax.jit(env.reset), jax.jit(env.step)
    state = reset(jax.random.PRNGKey(0))
    state.info["command"] = jp.array([1.0, 0.0, 0.0])
    key = jax.random.PRNGKey(1)
    total = dict.fromkeys(terms, 0.0)
    for _ in range(30):
        key, k = jax.random.split(key)
        state = step(state, jax.random.uniform(k, (env.action_size,), minval=-1.0, maxval=1.0))
        for t in terms:
            total[t] += float(state.metrics[f"reward/{t}"])
    for t in terms:
        assert total[t] < 0.0, f"{t} was never charged: {total}"
