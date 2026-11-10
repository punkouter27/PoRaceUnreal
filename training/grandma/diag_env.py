"""The real training env on the GPU (MuJoCo Warp), a few worlds, zero policy action: for each control step, which
stock termination fires (fell / foot contact sensors / non-finite), pelvis height, contacts used vs the per-env cap.
Compare creatures: python grandma/diag_env.py [grandma|matt] [worlds]"""
import sys
import jax
import jax.numpy as jp
import numpy as np
sys.path.insert(0, ".")
import train

who = sys.argv[1] if len(sys.argv) > 1 else "grandma"
W = int(sys.argv[2]) if len(sys.argv) > 2 else 16
env, cfg = train.make_env(who, num_worlds=W)
m = env.mj_model
reset, step = jax.jit(jax.vmap(env.reset)), jax.jit(jax.vmap(env.step))
st = reset(jax.random.split(jax.random.PRNGKey(0), W))
adr = {n: int(m.sensor_adr[m.sensor(n).id]) for n in ("right_foot_left_foot_found", "left_foot_right_shin_found", "right_foot_left_shin_found")}
print(f"{who}: {W} worlds, naconmax {cfg.naconmax} ({cfg.naconmax // W}/env), action size {env.action_size}")
zero = jp.zeros((W, env.action_size))
alive = np.ones(W, bool)
for k in range(1, 26):
  st = step(st, zero)
  d = st.data
  q = np.asarray(d.qpos); sd = np.asarray(d.sensordata); done = np.asarray(st.done) > 0
  nan = ~np.isfinite(q).all(1) | ~np.isfinite(np.asarray(d.qvel)).all(1)
  fired = {n: int((sd[:, a] > 0).sum()) for n, a in adr.items()}
  up = np.asarray(jax.vmap(lambda dd: env.get_gravity(dd, "torso"))(d))[:, -1]
  ncon = np.asarray(d.nacon) if hasattr(d, "nacon") else None
  if k <= 6 or k % 5 == 0:
    print(f"step {k:2d}: done {done.sum():2d}/{W}  nan {nan.sum():2d}  gravity-z<0 {(up < 0).sum():2d}  sensors {fired}  "
          f"pelvis z min/med {q[:, 2].min():.3f}/{np.median(q[:, 2]):.3f}  contacts {ncon if ncon is None else ncon.ravel()[:1]}")
bad = {kk: v for kk, v in st.metrics.items() if not np.isfinite(np.asarray(v)).all()}
print("non-finite metrics:", list(bad) or "none")
