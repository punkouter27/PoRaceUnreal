#!/usr/bin/env bash
# Parallel headless regression races (proposals r3 D9; AGENTS.md "re-run every policy's regression scenarios").
#   tools/regress.sh [player exe] [baseline exe]          e.g. tools/regress.sh Build/PoRace/PoRace.exe Build/Baseline/PoRace.exe
# Runs every scenario below as its own -batchmode -nographics player, JOBS at a time (CPU only: safe next to a GPU
# training run), then prints one line per scenario: exit code and the [Race4] finish line, plus the [ContactAudit]
# summary. With a baseline exe it runs the same grid on it and marks each scenario SAME / DIFF on the finish line.
# Logs: Logs/regress/<tag>_<scenario>.log.
set -uo pipefail
EXE=${1:-Build/PoRace/PoRace.exe}; BASE=${2:-}; JOBS=${JOBS:-4}
SCENARIOS=(   # one dog (Blue) since 2026-11-09; the humans race the flat maps only
  "blue_sprint_s7|-menuMap 0 -seed 7"
  "blue_oval_s3|-menuMap 1 -seed 3"
  "blue_bank_s2|-menuMap 2 -seed 2"
  "blue_steeple_s1|-menuMap 3 -seed 1"
  "matt_sprint_s7|-menuMap 0 -seed 7 -matt"
  "matt_oval_s3|-menuMap 1 -seed 3 -matt"
  "grandma_sprint_s7|-menuMap 0 -seed 7 -grandma"
  "humans_oval_s5|-menuMap 1 -seed 5 -matt -grandma"
)
mkdir -p Logs/regress
run_grid() {   # $1 exe, $2 tag
  local n=0
  for s in "${SCENARIOS[@]}"; do
    local name=${s%%|*} args=${s#*|}
    ( "$1" -batchmode -nographics -raceTest -timeScale 4 $args -logFile "Logs/regress/$2_$name.log" >/dev/null 2>&1
      echo $? > "Logs/regress/$2_$name.exit" ) &
    n=$((n + 1)); if (( n % JOBS == 0 )); then wait; fi
  done
  wait
}
finish() { grep -m1 -E "^\[Race4\]" "$1" 2>/dev/null | sed -E 's/^\[Race4\] //' | cut -c1-240; }
run_grid "$EXE" new
[ -n "$BASE" ] && run_grid "$BASE" base
printf "%-20s %-5s %-5s %s\n" scenario exit match finish
for s in "${SCENARIOS[@]}"; do
  name=${s%%|*}; f=Logs/regress/new_$name.log; ex=$(cat Logs/regress/new_$name.exit 2>/dev/null)
  m="-"; if [ -n "$BASE" ]; then [ "$(finish $f)" == "$(finish Logs/regress/base_$name.log)" ] && m=SAME || m=DIFF; fi
  printf "%-20s %-5s %-5s %s\n" "$name" "$ex" "$m" "$(finish $f)"
  grep -m1 "\[ContactAudit\]" "$f" | sed -E 's/\(limit[^)]*\)//g' | cut -c1-200 | sed 's/^/                       /'
done
