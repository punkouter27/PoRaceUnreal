"""Every racer model compiles with MuJoCo 4.0.0 and steps without NaN; every shipped brain loads in onnxruntime."""

import json
from pathlib import Path

import mujoco
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
TRACKS = sorted((ROOT / "training" / "models" / "tracks").glob("*_fingerprint.json"))
BRAINS = sorted((ROOT / "training" / "models" / "brains").glob("*.onnx"))


@pytest.mark.parametrize("fp", TRACKS, ids=lambda p: p.stem)
def test_track_model_steps_without_nan(fp):
    model_path = ROOT / json.loads(fp.read_text(encoding="utf-8"))["model"]
    m = mujoco.MjModel.from_xml_path(str(model_path))
    d = mujoco.MjData(m)
    mujoco.mj_resetData(m, d)
    for _ in range(250):  # 1 s at the race's 4 ms step, zero controls: everything falls / settles
        mujoco.mj_step(m, d)
    assert np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all()
    assert m.opt.gravity[2] == pytest.approx(-9.81)


@pytest.mark.parametrize("onnx_path", BRAINS, ids=lambda p: p.stem)
def test_brain_loads_and_runs(onnx_path):
    ort = pytest.importorskip("onnxruntime")
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    feeds = {}
    for inp in sess.get_inputs():
        shape = [d if isinstance(d, int) else 1 for d in inp.shape]
        feeds[inp.name] = np.zeros(shape, np.float32)
    outs = sess.run(None, feeds)
    assert outs and all(np.isfinite(o).all() for o in outs)
