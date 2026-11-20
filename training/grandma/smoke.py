"""Grandma env smoke (trainer container): preflight tags, then reset + 60 jitted steps with random actions on a few
worlds; every reward term finite, her clock and command range as the card says."""

import sys

import jax
import numpy as np

sys.path.insert(0, ".")
import preflight
import train

env, cfg = train.make_env("grandma", num_worlds=4)
preflight.check(env, cfg, None)
reset, step = jax.jit(jax.vmap(env.reset)), jax.jit(jax.vmap(env.step))
st = reset(jax.random.split(jax.random.PRNGKey(0), 4))
hz = np.asarray(st.info["phase_dt"]).ravel() / (2 * np.pi * env.dt)
print(
    "clock Hz",
    np.round(hz, 3),
    "cmd",
    np.round(np.asarray(st.info["cmd_target"] if "cmd_target" in st.info else st.info["command"]), 2).tolist(),
)
k = jax.random.PRNGKey(1)
for _i in range(60):
    k, a = jax.random.split(k)
    st = step(st, 0.3 * jax.random.normal(a, (4, env.action_size)))
bad = {kk: v for kk, v in st.metrics.items() if not np.isfinite(np.asarray(v)).all()}
print(
    "after 60 steps: reward",
    np.round(np.asarray(st.reward), 3),
    "pelvis z",
    np.round(np.asarray(st.data.qpos[:, 2]), 3),
    "non-finite metrics",
    list(bad) or "none",
)
