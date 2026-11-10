#!/usr/bin/env bash
# Grandma's training runs (her own, from scratch): Matt's shared reward recipe (matt/launch.sh) on her env, plus her
# character card's style weights (grandma/env.py default_config and the --set below). Inside the trainer container:
#   bash grandma/launch.sh <run name> [extra train.py args]
set -euo pipefail
NAME=$1; shift
exec python train.py --env grandma --num_envs 1024 --logdir "runs/$NAME" \
  --set realism.gait_symmetry=-1.5 --set realism.torso_ang_acc=-0.4 --set realism.arm_swing=-0.1 \
  --set realism.heat=-0.1 --set realism.action_delay_prob=0.3 --set realism.cmd_accel=6.0 \
  --set reward_config.scales.tracking_lin_vel=3.0 --set reward_config.scales.tracking_ang_vel=2.0 \
  --set reward_config.scales.tracking_ang_vel_wide=1.0 --set reward_config.scales.pose=-0.015 \
  --set reward_config.scales.stand_still=-2.0 "$@"
