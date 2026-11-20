import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TRAINING = ROOT / "training"


@pytest.fixture
def run_training():
    """Run a training/ script the way its docstring says (cwd training/), returning the CompletedProcess."""

    def run(*args, timeout=600):
        return subprocess.run(
            [sys.executable, *args], cwd=TRAINING, capture_output=True, text=True, timeout=timeout, check=False
        )

    return run
