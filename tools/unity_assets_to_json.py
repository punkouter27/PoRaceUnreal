"""Slice 0.7: convert the Unity MapDefinition / CreatureDefinition assets to plain JSON.

    uv run --no-project --with pyyaml python tools/unity_assets_to_json.py

Reads  reference/unity/Assets/Resources/{Maps,Creatures}/*.asset
Writes training/tracks/<name>.json and training/characters/<name>.json

Field names and values are kept as Unity stored them (metres, MuJoCo frame: x forward, y left).
Animation curves become lists of keys {t, v, in, out} (Hermite tangents, as Unity evaluates them).
References to Unity objects (prefabs, clips) become null: the art is re-linked on the Unreal side.
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "reference" / "unity" / "Assets" / "Resources"
JOBS = [("Maps", ROOT / "training" / "tracks"), ("Creatures", ROOT / "training" / "characters")]


def load_unity_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    # Drop the %YAML / %TAG header and the "--- !u!114 &id" document tag, which PyYAML cannot parse.
    body = "\n".join(l for l in text.splitlines() if not l.startswith("%") and not l.startswith("--- "))
    return yaml.safe_load(body)["MonoBehaviour"]


def convert(v):
    if isinstance(v, dict):
        if "m_Curve" in v:
            return [{"t": k["time"], "v": k["value"], "in": k["inSlope"], "out": k["outSlope"]} for k in v["m_Curve"] or []]
        if "fileID" in v:
            return None
        return {k: convert(x) for k, x in v.items()}
    if isinstance(v, list):
        return [convert(x) for x in v]
    return v


def slug(name: str) -> str:
    # Map03_BankedOval -> banked_oval, Creature02_Matt -> matt
    tail = name.split("_", 1)[1] if "_" in name else name
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", tail).lower()


def main() -> int:
    n = 0
    for folder, out_dir in JOBS:
        out_dir.mkdir(parents=True, exist_ok=True)
        for asset in sorted((SRC / folder).glob("*.asset")):
            mb = load_unity_yaml(asset)
            data = {"id": slug(mb["m_Name"]), "unityName": mb["m_Name"]}
            data.update({k: convert(v) for k, v in mb.items() if not k.startswith("m_")})
            out = out_dir / f"{data['id']}.json"
            out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
            print(f"{asset.relative_to(ROOT)} -> {out.relative_to(ROOT)} ({len(data)} fields)")
            n += 1
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
