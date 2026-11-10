#!/usr/bin/env bash
# Unattended checkpoint grader (CPU, beside a GPU run): every new checkpoint at least EVERY steps past the last graded
# one -> params.pkl (private copy) -> ladder up to the child tier for Grandma. One summary line per grade on stdout
# (a Monitor turns them into notifications) and appended to runs/<run>_grades.txt. Ends when the run's container stops.
#   bash training/grade_loop.sh <run> <container> [every_steps=24000000] [creature=grandma] [start_step=0]
RUN=$1; C=$2; EVERY=${3:-24000000}; WHO=${4:-grandma}
cd "$(dirname "$0")"
last=${5:-0}   # resume after a step already graded
while true; do
  running=$(docker inspect -f '{{.State.Status}}' "$C" 2>/dev/null)
  for d in $(ls runs/$RUN/checkpoints 2>/dev/null | grep -E '^[0-9]+$' | sort); do
    s=$((10#$d))
    [ -f "runs/$RUN/checkpoints/$d/commit_success.txt" ] || continue
    if [ $((s - last)) -ge "$EVERY" ] || { [ "$running" != "running" ] && [ "$s" -gt "$last" ]; }; then
      P=$(bash cpu.sh python ckpt_params.py runs/$RUN "$s" | tail -1)
      R=$(bash cpu.sh python matt/sim.py ladder --params "$P" --creature "$WHO" --upto child --seeds 10 | grep -E '^MATT-' \
          | sed -E 's/^MATT-(TODDLER|CHILD|LADDER):? ?//; s/ -> (PASS|FAIL)//; s/\(need [0-9]+\)//' | awk '{printf "%s | ", $0}')
      line="$RUN @ $(awk "BEGIN{printf \"%.1f\", $s/1e6}")M: $R"
      echo "$line" | tee -a "runs/${RUN}_grades.txt"
      last=$s
    fi
  done
  [ "$running" != "running" ] && { echo "$RUN grader done (container $running)"; exit 0; }
  sleep 60
done
