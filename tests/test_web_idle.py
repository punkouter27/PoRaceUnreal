"""The policy viewer's demo-mode clock (web/idle.js): 30 s without input starts demo mode, frames longer than 0.25 s
do not count, input ends it. Runs web/idle.test.mjs with Node (GitHub's ubuntu runners have it)."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_demo_clock_ignores_long_frames():
    node = shutil.which("node")
    assert node, "Node.js is needed for web/idle.test.mjs"
    out = subprocess.run(
        [node, "--test", "--test-reporter=tap", str(ROOT / "web" / "idle.test.mjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert out.returncode == 0, out.stdout[-3000:] + out.stderr[-3000:]
    assert "# pass 5" in out.stdout and "# fail 0" in out.stdout, out.stdout[-3000:]
