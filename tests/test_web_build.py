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
