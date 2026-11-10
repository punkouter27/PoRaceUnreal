#!/usr/bin/env bash
# Matt's training recipe (m20, the shipped policy), reconstructed from rl_optimization_log.md 2026-10-28 so later runs
# start from the same settings. Run inside the trainer container (cwd /work):
#   bash matt/launch.sh <run name> [extra train.py args, e.g. --restore_params final/matt_m20_params.pkl --set k=v]
# m14: tracking_lin_vel 2.5 + realism (gait -0.5 torso -0.2 arm -0.1 heat -0.05 delay 0.3 ramp 6); m16: lin 3.0, ang 2.0,
# ang_wide 1.0; m18: pose -0.015; m19: stand_still -2; m20: gait_symmetry -1.5. 1024 envs on the 6 GB RTX 2060.
set -euo pipefail
NAME=$1; shift
exec python train.py --env matt --num_envs 1024 --lr 1e-4 --logdir "runs/$NAME" \
  --set realism.gait_symmetry=-1.5 --set realism.torso_ang_acc=-0.2 --set realism.arm_swing=-0.1 \
  --set realism.heat=-0.05 --set realism.action_delay_prob=0.3 --set realism.cmd_accel=6.0 \
  --set reward_config.scales.tracking_lin_vel=3.0 --set reward_config.scales.tracking_ang_vel=2.0 \
  --set reward_config.scales.tracking_ang_vel_wide=1.0 --set reward_config.scales.pose=-0.015 \
  --set reward_config.scales.stand_still=-2.0 "$@"
