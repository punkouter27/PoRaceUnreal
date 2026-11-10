"""Grandma joystick env: Matt's env (training/matt/env.py: the stock G1 joystick on a human body in the G1 joint
layout, race physics, impratio 1, race-scale pushes, wide-sigma tracking, heading term, realism costs) on her body,
training/grandma/assets/grandma_porace.xml (tools/blender/grandma_rig.py -> matt_mjcf.py --creature grandma).

Her own brain: trained from scratch (AGENTS.md: no character reuses another's policy). Her personality is her
character card below, learned through her own command range, gait clock and style reward weights; the race
directors don't script any of it:
  - "unhurried": forward commands to 1.3 m/s (a brisk older walker), sideways +-0.3, yaw +-0.8
  - "short quick steps": stride clock U(0.95, 1.15) Hz (Unity runs 1.05; cadence ~110 steps/min), rising 0.2 Hz per m/s
    above 0.9 m/s (gait clock v2, proposals r3 D1)
  - "careful": swing foot target 7 cm (a low, shuffling clearance; Matt 12)
  - "steady": torso angular-acceleration cost x2 Matt's, arm swing as his
  - "saves her strength": motor heat budget 0.7 (Matt 1.0) and cost x2: she backs off before her joints run hot
Contact-force threshold at 1.53 x her body weight, as for Matt and the G1."""
from pathlib import Path

import jax
import jax.numpy as jp
from ml_collections import config_dict

from matt import env as matt

XML = Path(__file__).resolve().parent / "assets" / "grandma_porace.xml"
WEIGHT = 73.6 * 9.81   # N (check_model.py total mass)
CONTACTS_PER_ENV = matt.CONTACTS_PER_ENV


def default_config() -> config_dict.ConfigDict:
  cfg = matt.default_config()
  cfg.lin_vel_x = [-0.2, 1.3]
  cfg.lin_vel_y = [-0.3, 0.3]
  cfg.ang_vel_yaw = [-0.8, 0.8]
  cfg.reward_config.max_foot_height = 0.07
  cfg.reward_config.max_contact_force = 1.53 * WEIGHT
  cfg.push_config.magnitude_range = [0.1, 0.45]   # 30 N.s on 73.6 kg = 0.41 m/s (the race's shove bar)
  cfg.gait = config_dict.create(hz_lo=0.95, hz_hi=1.15)
  # character card: style weights (the shared Matt recipe in grandma/launch.sh sets the rest)
  cfg.realism.gait_hz_slope = 0.2
  cfg.realism.gait_hz_v0 = 0.9
  cfg.realism.heat_budget = 0.7
  # g1 (200M, from scratch, full launch recipe) learned to fall at once: eval episode 260 -> 3.7 control steps by 21M,
  # reward flat at -1.65. An untrained policy earns -0.38 per living step (plain recipe; -0.44 with her style costs:
  # foot contact force -18 / step vs alive +1, grandma/diag_reward.py), and a fall costs only -2 once. Floor each
  # step's living reward at 0 so staying up always pays at least as much as falling.
  cfg.positive_reward = True
  # g2 (floor alone) found the other way out: sit on the floor upright. The stock termination only ends an upside-down
  # torso, so sitting lived the whole episode on the alive bonus (978 / 1000 steps, toddler 0/10, zero foot force).
  # End the episode at the ladder's "fallen" height (matt/sim.py CREATURES: pelvis_min 0.54; standing ~0.75).
  cfg.fall_height = 0.54
  # g5 then kneeled / propped on a hand with the pelvis above 0.54 (toddler 0/10, 240-440 non-foot floor contacts):
  # a knee, elbow, wrist or the torso within 15 cm of the floor ends the episode too (her knee joint stands at ~0.42).
  cfg.low_body_height = 0.15
  return cfg


class GrandmaJoystick(matt.MattJoystick):
  XML_PATH = XML

  def reset(self, rng):
    rng, k = jax.random.split(rng)
    state = super().reset(rng)
    g = self._config.gait
    hz = jax.random.uniform(k, (1,), minval=g.hz_lo, maxval=g.hz_hi)   # her clock instead of the stock U(1.25, 1.5)
    state.info["phase_dt"] = 2 * jp.pi * self.dt * hz
    if self._rz.gait_hz_slope: state.info["phase_dt0"] = state.info["phase_dt"]
    return state
