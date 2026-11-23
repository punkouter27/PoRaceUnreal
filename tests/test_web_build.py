"""web/build.py builds the showcase (into a temp dir) and every /diag check points at a file it built."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_web_build_check():
    p = subprocess.run(
        [sys.executable, "web/build.py", "--check"], cwd=ROOT, capture_output=True, text=True, timeout=120, check=False
    )
    assert p.returncode == 0, p.stdout + p.stderr
    assert "web build OK (v" in p.stdout


def test_web_build_x_commit_off_and_phone_stamp(tmp_path):
    """Every response carries X-Commit = HEAD; switched-off services show a neutral "Off"; phones get the stamp after
    the content (static footer)."""
    spec = importlib.util.spec_from_file_location("web_build", ROOT / "web" / "build.py")
    web_build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(web_build)
    dist = tmp_path / "dist"
    web_build.build(dist)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    swa = json.loads((dist / "staticwebapp.config.json").read_text(encoding="utf-8"))
    assert swa["globalHeaders"]["x-commit"] == head.strip()
    js = (dist / "diag.js").read_text(encoding="utf-8")
    assert 'show(li, "Off", null' in js and "Not used" not in js
    css = (dist / "style.css").read_text(encoding="utf-8")
    assert "@media (max-width: 600px)" in css and ".foot { position: static; }" in css


def test_viewer_ships_brains_and_recordings(tmp_path):
    """/viewer: every replay ships its ONNX brain and the recorded obs/action it is checked against (the build already
    ran the brain with onnxruntime on CPU: pyMaxDiff), the page imports the onnxruntime-web build /diag probes, every page
    has the icon (no console 404) and the commit stamp /diag compares, and the title is shown once (top bar only)."""
    spec = importlib.util.spec_from_file_location("web_build", ROOT / "web" / "build.py")
    web_build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(web_build)
    dist = tmp_path / "dist"
    web_build.build(dist)
    replays = json.loads((dist / "data" / "replays.json").read_text(encoding="utf-8"))
    assert {r["brain"] for r in replays} >= {"go2_loco", "matt_loco"}
    for r in replays:
        assert (dist / r["policy"]).is_file()
        data = json.loads((dist / "data" / f"{r['name']}.json").read_text(encoding="utf-8"))
        assert len(data["obs"]) == len(data["action"]) == len(data["frames"]) == r["frames"] > 0
        assert len(data["obs"][0]) == r["obsDim"] and len(data["action"][0]) == r["actionDim"]
        assert r["pyMaxDiff"] < web_build.MAX_POLICY_DIFF
    assert web_build.ORT_URL in (dist / "viewer.js").read_text(encoding="utf-8")
    checks = json.loads((dist / "diag_checks.json").read_text(encoding="utf-8"))["checks"]
    assert any(c["kind"] == "inference" and c["url"] == web_build.ORT_URL for c in checks)
    assert (dist / "favicon.svg").is_file()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    for page in ("index.html", "diag.html", "viewer.html"):
        text = (dist / page).read_text(encoding="utf-8")
        assert 'rel="icon" href="/favicon.svg"' in text, page
    assert f'name="po-commit" content="{head.strip()}"' in (dist / "diag.html").read_text(encoding="utf-8")
    index = (dist / "index.html").read_text(encoding="utf-8")
    body = index.split("<body>", 1)[1]
    assert "<h1>PoRace</h1>" not in body and body.count(">PoRace<") == 1
