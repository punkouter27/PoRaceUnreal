"""Is an untrained policy paid to end the episode? Real GPU env, W worlds, actions like a fresh PPO policy
(tanh of unit-normal samples), 50 control steps: mean reward per alive step, share terminated, and the biggest
per-step reward terms. A net-negative step reward against a ~-2 termination makes "fall at once" the optimum (Matt
m2-m4). Usage: python grandma/diag_reward.py <creature> [KEY=VALUE ...]   (the same overrides as train.py --set)"""
import ast
import sys
import jax
import jax.numpy as jp
import numpy as np
sys.path.insert(0, ".")
import train

who = sys.argv[1]
sets = sys.argv[2:]
def tweak(cfg):
  for kv in sets:
    key, val = kv.split("=", 1); *path, leaf = key.split("."); node = cfg
    for p in path: node = node[p]
    node[leaf] = ast.literal_eval(val)
  return cfg

W = 64
env, cfg = train.make_env(who, num_worlds=W, tweak=tweak)
reset, step = jax.jit(jax.vmap(env.reset)), jax.jit(jax.vmap(env.step))
st = reset(jax.random.split(jax.random.PRNGKey(0), W))
k = jax.random.PRNGKey(1)
alive = np.ones(W, bool); rsum = 0.0; n = 0; terms = {}
for i in range(50):
  k, a = jax.random.split(k)
  st = step(st, jp.tanh(jax.random.normal(a, (W, env.action_size))))
  r = np.asarray(st.reward); done = np.asarray(st.done) > 0
  rsum += r[alive].sum(); n += alive.sum()
  for kk, v in st.metrics.items():
    if kk.startswith("reward/"): terms[kk] = terms.get(kk, 0.0) + float(np.asarray(v)[alive].sum())
  alive &= ~done
scales = cfg.reward_config.scales
top = sorted(((v / max(n, 1), kk) for kk, v in terms.items()), key=lambda x: x[0])
print(f"{who} {' '.join(sets) or '(plain)'}\n  mean reward per alive step {rsum / max(n, 1):+.4f} | terminated within 50 steps {(~alive).mean():.0%}")
print("  most negative terms (metric per alive step):", ", ".join(f"{kk[7:]} {v:+.3f}" for v, kk in top[:6]))
print("  most positive:", ", ".join(f"{kk[7:]} {v:+.3f}" for v, kk in top[-4:]))
