#!/usr/bin/env bash
# Background GPU training from Git Bash: training/launch.sh <name> <train.py args...>
#   writes training/runs/<name>.log (Warp solver warnings filtered), container name porace_<name>
#   when the container exits (finished, stopped or crashed) benchmark/runs.py records the run on this host (machine,
#   commit, how it ended) and rebuilds training/runs/runs.html; that step can never fail or change the run.
set -uo pipefail
export MSYS_NO_PATHCONV=1
NAME=$1; shift
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; W="$(cygpath -w "$ROOT")"
docker run --rm --init --log-driver none --gpus all --name "porace_$NAME" \
  -v "$W\training:/work" -v "$W\docs:/docs" -v "$W\Assets:/assets" porace-trainer \
  python -u train.py --logdir "runs/$NAME" "$@" 2>&1 \
  | grep --line-buffered -v -E 'iterations limit reached|iterationtions|iteratioations|linesearch|To disable the print|warning: m.opt|^\s*$|NVIDIA|container image|nvidia.com|license|By pulling|convenience' \
  > "$ROOT/training/runs/$NAME.log"
CODE=${PIPESTATUS[0]}
echo "exit $CODE" >> "$ROOT/training/runs/$NAME.log"
# Training runs grid, with the host's Python (the machine is Windows', not the container's). Never fatal.
PY=(python); command -v uv > /dev/null 2>&1 && PY=(uv run --no-project --python 3.12 python)
timeout 120 "${PY[@]}" "$W\benchmark\runs.py" --record "$NAME" --ended "exit $CODE" --launcher training/launch.sh \
  "--args=$*" || echo "runs grid not rebuilt"
