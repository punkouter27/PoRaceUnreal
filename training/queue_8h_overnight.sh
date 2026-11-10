#!/usr/bin/env bash
# Unattended 8-Hour Multi-Agent RL Optimization Loop (~480 minutes / 1.3B+ steps across 9 sequential runs).
# Priority order (AGENTS.md & docs/20261109/training_8h.md):
#   1. Grandma (Urgent: push 84/100 graduation past the >=90/100 ONNX gate, soften walking foot force <3.0 BW, add turn + slope)
#   2. Matt (Adult 10% uphill slope, 15 deg banked turns, and aerial-clearance jog)
#   3. Dog / Go2 (impratio=1 shared-model margin and steeplechase 95%+ polish)
# Waits cleanly for any active porace_* GPU container (e.g. porace_g13) before starting each run.

set -uo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
LOG="$ROOT/training/runs/queue_8h_overnight.log"

log() {
  echo "[$(date -u +'%Y-%m-%d %H:%M:%S UTC')] $*" | tee -a "$LOG"
}

wait_for_gpu_idle() {
  while true; do
    active=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^porace_' || true)
    if [ -z "$active" ] && { [ -f "runs/g13/params.pkl" ] || grep -q "^exit " "runs/g13.log" 2>/dev/null; }; then
      break
    fi
    log "Waiting for active GPU container(s) (${active:-g13}) to finish..."
    sleep 60
  done
}

best_grandma_params() {
  # Pick the highest-graded Grandma params in final/
  for f in final/grandma_g16_*.pkl final/grandma_g15_*.pkl final/grandma_g14_*.pkl final/grandma_g13_*.pkl final/grandma_g12_grad71_params.pkl; do
    if [ -f "$f" ]; then
      echo "$f"
      return
    fi
  done
  echo "runs/g13/params.pkl"
}

refresh_reports() {
  log "Refreshing TensorBoard dump and HTML reports..."
  python tb_dump.py runs/session8h_tb.json g1 g2 g3 g4 g5 g6 g7 g8 g9 g10 g11 g12 g13 g14 g15 g16 g17 m25 m26 m27 m28 r10_imp1 s11_steeple 2>&1 | tee -a "$LOG" || true
  python report_8h.py --tb runs/session8h_tb.json --points ../docs/20261109/grandma_ladder_points.json --status ../docs/20261109/agent_status.json --out ../docs/report/training_8h_20261109.html 2>&1 | tee -a "$LOG" || true
  cp -f ../docs/report/training_8h_20261109.html ../SCREENSHOTS/training_8h_report.html 2>/dev/null || true
}

grade_and_promote_human() {
  local run=$1
  local who=$2
  if [ -f "runs/$run/params.pkl" ]; then
    log "Grading final checkpoint of $run ($who)..."
    bash cpu.sh python matt/sim.py ladder --params "runs/$run/params.pkl" --creature "$who" --upto adult --seeds 10 | tee -a "runs/${run}_grades.txt" "$LOG" || true
    grad_line=$(bash cpu.sh python matt/sim.py graduate --params "runs/$run/params.pkl" --creature "$who" --episodes 100 | grep -E 'MATT-GRADUATE' | tail -1 || true)
    log "$run graduation: $grad_line"
    echo "$run final: $grad_line" >> "runs/${run}_grades.txt"
    cp -f "runs/$run/params.pkl" "final/${who}_${run}_params.pkl" 2>/dev/null || true
  fi
  refresh_reports
}

run_human_stage() {
  local name=$1
  local who=$2
  shift 2
  wait_for_gpu_idle
  if [ -f "runs/$name/params.pkl" ]; then
    log "Stage $name already completed (runs/$name/params.pkl exists); skipping."
    return
  fi
  log "=== STARTING GPU RUN: $name ($who) args: $* ==="
  bash launch.sh "$name" "$@" &
  local train_pid=$!
  sleep 15
  bash grade_loop.sh "$name" "porace_$name" 24000000 "$who" 0 >> "$LOG" 2>&1 &
  wait $train_pid || true
  grade_and_promote_human "$name" "$who"
  log "=== FINISHED GPU RUN: $name ==="
}

log "8-Hour Overnight Multi-Agent RL Queue initialized."
wait_for_gpu_idle
# Wait an extra 90s after g13 ends so any external grader finishes cleanly
sleep 90
refresh_reports

# 1. Grandma g14 (~45 min, 120M steps): fine-tune from best g13 checkpoint at lr 5e-5 to push graduation >= 90/100
G13_BEST=$(best_grandma_params)
run_human_stage g14 grandma \
  --env grandma --num_envs 1024 --timesteps 120000000 --lr 5e-5 --entropy 0.005 \
  --restore_params "$G13_BEST" \
  --set realism.gait_symmetry=-4.5 --set realism.torso_ang_acc=-0.4 --set realism.arm_swing=-0.1 \
  --set realism.heat=-0.1 --set realism.action_delay_prob=0.3 --set realism.cmd_accel=6.0 \
  --set reward_config.scales.tracking_lin_vel=3.5 --set reward_config.scales.tracking_lin_vel_wide=4.5 \
  --set reward_config.scales.tracking_ang_vel=2.0 --set reward_config.scales.tracking_ang_vel_wide=1.0 \
  --set reward_config.scales.pose=-0.015 --set reward_config.scales.stand_still=-0.5 \
  --set reward_config.scales.alive=5.0 --set reward_config.scales.action_rate=-0.1 --set positive_reward=False

# 2. Grandma g15 (~45 min, 120M steps): foot-force softening (< 3.0 BW walking) + action smoothness
G14_BEST=$(best_grandma_params)
run_human_stage g15 grandma \
  --env grandma --num_envs 1024 --timesteps 120000000 --lr 5e-5 --entropy 0.005 \
  --restore_params "$G14_BEST" \
  --set realism.gait_symmetry=-4.5 --set realism.torso_ang_acc=-0.4 --set realism.arm_swing=-0.1 \
  --set realism.heat=-0.1 --set realism.action_delay_prob=0.3 --set realism.cmd_accel=6.0 \
  --set reward_config.scales.tracking_lin_vel=3.5 --set reward_config.scales.tracking_lin_vel_wide=4.5 \
  --set reward_config.scales.tracking_ang_vel=2.0 --set reward_config.scales.tracking_ang_vel_wide=1.0 \
  --set reward_config.scales.pose=-0.015 --set reward_config.scales.stand_still=-0.5 \
  --set reward_config.scales.alive=5.0 --set reward_config.scales.action_rate=-0.12 \
  --set reward_config.scales.contact_force=-0.015 --set positive_reward=False

# 3. Grandma g16 (~55 min, 150M steps): Adult brisk speed (1.35 m/s) & tighter yaw tracking
G15_BEST=$(best_grandma_params)
run_human_stage g16 grandma \
  --env grandma --num_envs 1024 --timesteps 150000000 --lr 5e-5 --entropy 0.005 \
  --restore_params "$G15_BEST" \
  --set realism.gait_symmetry=-4.5 --set realism.torso_ang_acc=-0.4 --set realism.arm_swing=-0.1 \
  --set realism.heat=-0.1 --set realism.action_delay_prob=0.3 --set realism.cmd_accel=6.0 \
  --set reward_config.scales.tracking_lin_vel=3.5 --set reward_config.scales.tracking_lin_vel_wide=4.5 \
  --set reward_config.scales.tracking_ang_vel=2.5 --set reward_config.scales.tracking_ang_vel_wide=1.5 \
  --set reward_config.scales.pose=-0.015 --set reward_config.scales.stand_still=-0.5 \
  --set reward_config.scales.alive=5.0 --set reward_config.scales.action_rate=-0.12 --set positive_reward=False

# 4. Grandma g17 (~55 min, 150M steps): Adult 10% slope / banked track robustness
G16_BEST=$(best_grandma_params)
run_human_stage g17 grandma \
  --env grandma --num_envs 1024 --timesteps 150000000 --lr 5e-5 --entropy 0.005 --tilt_max 8 \
  --restore_params "$G16_BEST" \
  --set realism.gait_symmetry=-4.5 --set realism.torso_ang_acc=-0.4 --set realism.arm_swing=-0.1 \
  --set realism.heat=-0.1 --set realism.action_delay_prob=0.3 --set realism.cmd_accel=6.0 \
  --set reward_config.scales.tracking_lin_vel=3.5 --set reward_config.scales.tracking_lin_vel_wide=4.5 \
  --set reward_config.scales.tracking_ang_vel=2.5 --set reward_config.scales.tracking_ang_vel_wide=1.5 \
  --set reward_config.scales.pose=-0.015 --set reward_config.scales.stand_still=-0.5 \
  --set reward_config.scales.alive=5.0 --set reward_config.scales.action_rate=-0.12 --set positive_reward=False

# 5. Matt m26 (~55 min, 150M steps): Adult 10% uphill grade & banked slope mastery from shipped matt_m20
run_human_stage m26 matt \
  --env matt --num_envs 1024 --timesteps 150000000 --lr 5e-5 --tilt_max 8 \
  --restore_params final/matt_m20_params.pkl \
  --set realism.gait_symmetry=-1.5 --set realism.torso_ang_acc=-0.2 --set realism.arm_swing=-0.1 \
  --set realism.heat=-0.05 --set realism.action_delay_prob=0.3 --set realism.cmd_accel=6.0 \
  --set reward_config.scales.tracking_lin_vel=3.0 --set reward_config.scales.tracking_ang_vel=2.0 \
  --set reward_config.scales.tracking_ang_vel_wide=1.0 --set reward_config.scales.pose=-0.015 \
  --set reward_config.scales.stand_still=-2.0

# 6. Matt m27 (~55 min, 150M steps): Adult 15 deg Banked Oval mastery
M26_PARAMS="final/matt_m20_params.pkl"
[ -f "runs/m26/params.pkl" ] && M26_PARAMS="runs/m26/params.pkl"
run_human_stage m27 matt \
  --env matt --num_envs 1024 --timesteps 150000000 --lr 5e-5 --tilt_max 15 \
  --restore_params "$M26_PARAMS" \
  --set realism.gait_symmetry=-1.5 --set realism.torso_ang_acc=-0.2 --set realism.arm_swing=-0.1 \
  --set realism.heat=-0.05 --set realism.action_delay_prob=0.3 --set realism.cmd_accel=6.0 \
  --set reward_config.scales.tracking_lin_vel=3.0 --set reward_config.scales.tracking_ang_vel=2.0 \
  --set reward_config.scales.tracking_ang_vel_wide=1.0 --set reward_config.scales.pose=-0.015 \
  --set reward_config.scales.stand_still=-2.0

# 7. Matt m28 (~55 min, 150M steps): Adult Jog with high swing clearance (0.16 m) & gait clock v2
run_human_stage m28 matt \
  --env matt --num_envs 1024 --timesteps 150000000 --lr 5e-5 --swing 0.16 \
  --restore_params final/matt_m20_params.pkl \
  --set lin_vel_x="[-0.3, 2.5]" --set realism.gait_hz_slope=0.25 --set realism.gait_hz_v0=1.2 \
  --set realism.gait_symmetry=-1.5 --set realism.torso_ang_acc=-0.2 --set realism.arm_swing=-0.1 \
  --set realism.heat=-0.05 --set realism.action_delay_prob=0.3 --set realism.cmd_accel=6.0 \
  --set reward_config.scales.tracking_lin_vel=3.5 --set reward_config.scales.tracking_ang_vel=2.0 \
  --set reward_config.scales.tracking_ang_vel_wide=1.0 --set reward_config.scales.pose=-0.01 \
  --set reward_config.scales.stand_still=-2.0

# 8. Dog / Go2 s11_steeple (~45 min, 150M steps): Steeplechase obstacle field 95%+ consistency fine-tune
wait_for_gpu_idle
if [ ! -f "runs/s11_steeple/params.pkl" ]; then
  log "=== STARTING GPU RUN: s11_steeple (Go2 Steeplechase polish) ==="
  bash launch.sh s11_steeple --env joystick --steeple --pert --dr --timesteps 150000000 --lr 3e-5 --entropy 0.005 \
    --restore_params final/go2_steeple_params.pkl --vx_max 2.0 --kick_max 7
  [ -f "runs/s11_steeple/params.pkl" ] && cp -f "runs/s11_steeple/params.pkl" "final/go2_s11_steeple_params.pkl"
  refresh_reports
fi

# 9. Dog / Go2 r10_imp1 (~45 min, 150M steps): High-speed sloped & flat push-recovery margin polish
wait_for_gpu_idle
if [ ! -f "runs/r10_imp1/params.pkl" ]; then
  log "=== STARTING GPU RUN: r10_imp1 (Go2 Locomotion & Banked margin polish) ==="
  bash launch.sh r10_imp1 --env joystick --pert --cubes --dr --timesteps 150000000 --lr 3e-5 --entropy 0.005 \
    --restore_params final/go2_loco_params.pkl --vx_max 2.0 --tilt_max 17 --kick_max 7
  [ -f "runs/r10_imp1/params.pkl" ] && cp -f "runs/r10_imp1/params.pkl" "final/go2_r10_loco_params.pkl"
  refresh_reports
fi

log "=== ALL 8-HOUR OVERNIGHT MULTI-AGENT RUNS COMPLETED ==="
refresh_reports
