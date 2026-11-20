"""The generated contract files (fingerprints, RaceContract.gen.h) match the trainer's constants and models."""

import mujoco


def test_mujoco_is_the_contract_version():
    import contract

    assert mujoco.__version__ == contract.MUJOCO_VERSION == "4.0.0"


def test_generated_contract_is_current(run_training):
    p = run_training("contract.py", "--check")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "STALE" not in p.stdout
