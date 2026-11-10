#!/usr/bin/env bash
# Run a command in the trainer image on the CPU (no GPU: safe beside a training run), training/ at /work, docs/ at /docs.
#   bash training/cpu.sh python matt/sim.py ladder --params runs/g2/params.pkl --creature grandma
ROOT=$(cd "$(dirname "$0")/.." && pwd -W 2>/dev/null || pwd)
MSYS_NO_PATHCONV=1 docker run --rm --init --log-driver none -e JAX_PLATFORMS=cpu \
  -v "$ROOT/training:/work" -v "$ROOT/docs:/docs" -w /work porace-trainer "$@" 2>&1 \
  | grep -v -E 'NVIDIA|CUDA Version|^==|cloud-native|Container Toolkit|icense|Copyright|governed|this container|^$'
