"""Reward terms under a trained checkpoint (deterministic policy) in the real GPU env: per living step, each scaled
term, the share of steps whose living reward is negative (zeroed by positive_reward), and episode length.
  python grandma/diag_policy.py runs/g3/params_000042598400.pkl [grandma] [KEY=VALUE ...]   (ckpt_params.py makes it)"""

import ast
import sys

import jax
import jax.numpy as jp
import numpy as np
from brax.io import model as brax_model

sys.path.insert(0, ".")
import train
from export_onnx import NORM_EPS, unpack_params

ckpt, who, sets = (
    sys.argv[1],
    (sys.argv[2] if len(sys.argv) > 2 and "=" not in sys.argv[2] else "grandma"),
    [a for a in sys.argv[2:] if "=" in a],
)


def tweak(cfg):
    for kv in sets:
        key, val = kv.split("=", 1)
        *path, leaf = key.split(".")
        node = cfg
        for p in path:
            node = node[p]
        node[leaf] = ast.literal_eval(val)
    return cfg


W, T = 128, 400
env, cfg = train.make_env(who, num_worlds=W, tweak=tweak)
mean, std, layers = unpack_params(
    brax_model.load_params(ckpt)
)  # the exported graph: deterministic tanh(mlp(norm(obs)))


def _pi(obs):
    x = ((obs["state"] if isinstance(obs, dict) else obs) - mean) / (std + NORM_EPS)
    for i, (w, b) in enumerate(layers):
        x = x @ w + b
        if i < len(layers) - 1:
            x = x * jax.nn.sigmoid(x)
    return jp.tanh(x)


policy = jax.jit(_pi)
reset, step = jax.jit(jax.vmap(env.reset)), jax.jit(jax.vmap(env.step))
st = reset(jax.random.split(jax.random.PRNGKey(0), W))
alive = np.ones(W, bool)
n = 0
neg = 0
terms = {}
length = np.zeros(W)
vx = []
for t in range(T):
    act = policy(st.obs)
    st = step(st, act)
    done = np.asarray(st.done) > 0
    total = sum(
        np.asarray(v) for kk, v in st.metrics.items() if kk.startswith("reward/") and kk != "reward/termination"
    )
    n += alive.sum()
    neg += (alive & (total < 0)).sum()
    length += alive
    for kk, v in st.metrics.items():
        if kk.startswith("reward/"):
            terms[kk[7:]] = terms.get(kk[7:], 0.0) + float(np.asarray(v)[alive].sum())
    v = np.asarray(jax.vmap(lambda dd: env.get_local_linvel(dd, "pelvis"))(st.data))[:, 0]
    if t >= 100:
        vx.extend(v[alive].tolist())
    alive &= ~done
print(
    f"forward speed after 2 s (living worlds): mean {np.mean(vx) if vx else float('nan'):.2f} m/s, p10/p90 {np.percentile(vx, 10) if vx else float('nan'):.2f}/{np.percentile(vx, 90) if vx else float('nan'):.2f}"
)
print(
    f"{ckpt}: {W} worlds x {T} steps | episode length (capped {T}) mean {length.mean():.0f} | living steps with a negative total "
    f"(floored to 0): {neg / max(n, 1):.0%}"
)
for v, kk in sorted((v / max(n, 1), kk) for kk, v in terms.items()):
    if abs(v) > 0.005:
        print(f"  {kk:24s} {v:+9.3f} per living step")
