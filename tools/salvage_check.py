"""Slice 0.9: prove the salvage from the Unity project is complete and usable.

    uv run --no-project --python 3.12 --with mujoco==4.0.0 --with onnxruntime --with numpy \
        python tools/salvage_check.py [--source <PoRace checkout or export>]

Checks, each printed as one OK / FAIL row:
  1. (with --source) every salvaged file is byte-identical to its source
  2. every brain loads in onnxruntime with the expected input / output sizes
  3. every MuJoCo model compiles, with the expected actuator count
  4. the converted track and character cards are present and well formed
Exit code 1 if any row fails.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# source (relative to the Unity project) -> destination (relative to this repo)
TREES = [
    ("training", "training"),
    ("tools/blender", "tools/blender"),
    ("tools/android", "tools/android"),
    ("Assets/Policies", "training/models/brains"),
    ("Assets/MuJoCo", "training/models/unity_flat"),
    ("Assets/Art/Raw", "Content/Art/Raw"),
    ("Assets/Art/Exports/GLB", "Content/Art/Exports"),
    ("docs", "docs"),
    ("SCREENSHOTS", "docs/unity_screens"),
    ("Assets/Scripts", "reference/unity/Assets/Scripts"),
    ("Assets/Editor", "reference/unity/Assets/Editor"),
    ("Assets/Tests", "reference/unity/Assets/Tests"),
    ("Assets/Resources", "reference/unity/Assets/Resources"),
    ("Assets/Generated", "reference/unity/Assets/Generated"),
    ("Assets/Shaders", "reference/unity/Assets/Shaders"),
]
FILES = [
    ("GrandmaRiggedUnity.fbx", "Content/Art/Raw/Grandma/GrandmaRiggedUnity.fbx"),
    ("GrandmaRiggedUnity.json", "Content/Art/Raw/Grandma/GrandmaRiggedUnity.json"),
    ("GrandmaRiggedUnity_ExpressionFrameMap.ini", "Content/Art/Raw/Grandma/GrandmaRiggedUnity_ExpressionFrameMap.ini"),
    ("rl_optimization_log.md", "docs/rl_optimization_log.md"),
    ("tasks.md", "docs/unity_tasks.md"),
    ("tools/prune.py", "tools/prune.py"),
    ("privacy-policy.html", "privacy-policy.html"),
]
SKIP_PARTS = {"__pycache__", ".venv", "runs"}
SKIP_SUFFIX = {".meta", ".pyc"}

# brain -> (observation size, action size)
BRAINS = {
    "training/models/brains/go2_loco.onnx": (48, 12),
    "training/models/brains/go2_loco_fast.onnx": (48, 12),
    "training/models/brains/go2_loco_bank.onnx": (48, 12),
    "training/models/brains/go2_loco_steeple.onnx": (48, 12),
    "training/models/brains/go2_getup.onnx": (42, 12),
    "training/models/brains/zero_policy.onnx": (48, 12),
    "training/models/brains/matt_loco.onnx": (103, 29),
    "training/final/matt_m20.onnx": (103, 29),
    "training/final/grandma_g14.onnx": (103, 29),
}
# model -> actuator count
MODELS = {
    "training/assets/go2/scene_porace.xml": 12,
    "training/assets/go2/scene_steeple.xml": 12,
    "training/matt/assets/matt_porace.xml": 29,
    "training/grandma/assets/grandma_porace.xml": 29,
    "training/g1/assets/g1_porace.xml": None,
    "training/models/unity_flat/go2_unity.xml": 12,
    "training/models/unity_flat/matt/matt_unity.xml": None,
    "training/models/unity_flat/grandma/grandma_unity.xml": None,
    "training/models/unity_flat/g1/g1_unity.xml": None,
}
TRACKS = ["planar_sprint", "flat_oval", "banked_oval", "steeplechase"]
CHARACTERS = ["go2", "matt", "grandma"]

rows, failed = [], 0


def row(group, name, ok, note=""):
    global failed
    failed += 0 if ok else 1
    rows.append((group, name, "OK" if ok else "FAIL", note))


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wanted(rel: Path) -> bool:
    return not (set(rel.parts) & SKIP_PARTS) and rel.suffix not in SKIP_SUFFIX


def check_copies(source: Path):
    for s, d in TREES:
        src, dst = source / s, ROOT / d
        files = [p for p in src.rglob("*") if p.is_file() and wanted(p.relative_to(src))]
        bad = [str(p.relative_to(src)) for p in files
               if not (dst / p.relative_to(src)).is_file() or sha(p) != sha(dst / p.relative_to(src))]
        row("copy", f"{s} -> {d}", bool(files) and not bad, f"{len(files)} files" + (f", differ/missing: {bad[:3]}" if bad else ""))
    for s, d in FILES:
        ok = (source / s).is_file() and (ROOT / d).is_file() and sha(source / s) == sha(ROOT / d)
        row("copy", f"{s} -> {d}", ok)


def check_brains():
    import numpy as np
    import onnxruntime as ort
    for rel, (n_obs, n_act) in BRAINS.items():
        try:
            s = ort.InferenceSession(str(ROOT / rel), providers=["CPUExecutionProvider"])
            i = s.get_inputs()[0]
            out = s.run(None, {i.name: np.zeros((1, n_obs), np.float32)})[0]
            ok = out.shape[-1] == n_act and bool(np.isfinite(out).all())
            row("brain", rel, ok, f"{i.shape[-1]} -> {out.shape[-1]}")
        except Exception as e:  # noqa: BLE001 - report any load failure as a row
            row("brain", rel, False, f"{type(e).__name__}: {str(e)[:120]}")


def check_models():
    import mujoco
    for rel, nu in MODELS.items():
        try:
            m = mujoco.MjModel.from_xml_path(str(ROOT / rel))
            d = mujoco.MjData(m)
            mujoco.mj_forward(m, d)
            ok = nu is None or m.nu == nu
            row("model", rel, ok, f"nu={m.nu} nq={m.nq} nbody={m.nbody} dt={m.opt.timestep}")
        except Exception as e:  # noqa: BLE001
            row("model", rel, False, f"{type(e).__name__}: {str(e)[:120]}")
    row("model", "mujoco version", True, mujoco.__version__)


def check_cards():
    for name in TRACKS:
        p = ROOT / "training" / "tracks" / f"{name}.json"
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
            ok = len(t["centerline"]) >= 2 and t["halfWidth"] > 0
            row("card", str(p.relative_to(ROOT)), ok, f"{t['displayName']}, {len(t['centerline'])} points, closed={t['closed']}")
        except Exception as e:  # noqa: BLE001
            row("card", f"training/tracks/{name}.json", False, f"{type(e).__name__}: {e}")
    for name in CHARACTERS:
        p = ROOT / "training" / "characters" / f"{name}.json"
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
            row("card", str(p.relative_to(ROOT)), bool(c["displayName"]), f"{c['displayName']}, raceable={c.get('raceable')}")
        except Exception as e:  # noqa: BLE001
            row("card", f"training/characters/{name}.json", False, f"{type(e).__name__}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, help="the Unity project (or an export of it) to compare hashes against")
    a = ap.parse_args()
    if a.source:
        check_copies(a.source)
    check_brains()
    check_models()
    check_cards()
    w = max(len(r[1]) for r in rows)
    for g, n, s, note in rows:
        print(f"{g:6} {n:{w}}  {s:4}  {note}")
    print(f"\n{len(rows) - failed}/{len(rows)} OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
