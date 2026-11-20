"""Checkpoint step -> params.pkl, from a private copy (a reader holding files in the live checkpoints folder made the
trainer's next save fail on the Windows bind mount, see matt/probe_ckpts.py). Then grade it with matt/sim.py.
  python ckpt_params.py runs/g2 31948800            -> runs/g2/params_000031948800.pkl
  python ckpt_params.py runs/g2 latest              -> the newest finished checkpoint"""

import shutil
import sys
import tempfile
from pathlib import Path

from brax.io import model
from brax.training.agents.ppo import checkpoint as ck

run = Path(sys.argv[1])
step = sys.argv[2]
steps = sorted(
    p.name for p in (run / "checkpoints").iterdir() if p.name.isdigit() and (p / "commit_success.txt").exists()
)
step = steps[-1] if step == "latest" else f"{int(step):012d}"
out = run / f"params_{step}.pkl"
if not out.exists():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "ckpt"
        shutil.copytree(run / "checkpoints" / step, tmp)
        model.save_params(str(out), ck.load(str(tmp)))
print(out)
