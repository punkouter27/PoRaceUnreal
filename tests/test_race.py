"""End to end: the tactics / yellow-flag self-test and one seeded reference race on CPU MuJoCo with the real brains."""

import pytest


def test_rules_selftest(run_training):
    p = run_training("selftest.py")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    assert "[SelfTest] all passed" in p.stdout


def test_reference_race_finishes(run_training):
    pytest.importorskip("onnxruntime")
    p = run_training("race.py", "planar_sprint", "--seed", "1", timeout=900)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    line = next(x for x in p.stdout.splitlines() if x.startswith("[Race] FINISHED"))
    assert "falls=0" in line
