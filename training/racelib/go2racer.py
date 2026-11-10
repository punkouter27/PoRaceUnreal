"""One Go2 in a shared race model: its two brains, the get-up switch and the auto-reset.

Source/PoRaceUnreal/RacerGo2.cpp is the same class line for line. The brain loop is go2/sim.py's (the parity gate
proved it equal to training); this adds what a race needs around it. Call order per physics step, before mj_step:
  1. update_state()  (the race does this, then its rules, which may reset or re-command the racer)
  2. control()       (a brain decision every DECIMATION steps, counted from the last reset)
"""
import math

import mujoco
import numpy as np

from go2 import constants as C
from go2.sim import DEFAULT, Policy, find

T = mujoco.mjtObj

RACING, STUMBLE, FALLEN = "RACING", "STUMBLE", "FALLEN"
LOCO, GETUP = "loco", "getup"

# Timers in physics steps (4 ms). Unity counted float seconds; whole steps make both runtimes count alike.
FALLEN_STEPS = 1250        # 5 s down -> reset to the last checkpoint
STALL_STEPS = 2500         # 10 s barely moving while asked to move -> reset
STALL_SPEED = 0.05         # m/s
UPRIGHT_DECISIONS = 25     # get-up hands back to locomotion after 25 straight decisions (0.5 s) with up_z > 0.9
UPRIGHT_Z = 0.9
STUMBLE_Z = 0.7


class Go2Racer:
  def __init__(self, m, d, prefix, loco: Policy, getup: Policy, home_height=0.27):
    self.m, self.d, self.prefix = m, d, prefix
    self.loco, self.getup = loco, getup
    self.home_height = home_height
    f = lambda t, n, name: find(m, t, n, prefix + name)  # noqa: E731
    self.act = np.array([f(T.mjOBJ_ACTUATOR, m.nu, a) for a in C.ACTUATOR_NAMES])
    joints = [f(T.mjOBJ_JOINT, m.njnt, j) for j in C.JOINT_NAMES]
    self.qadr, self.vadr = m.jnt_qposadr[joints], m.jnt_dofadr[joints]
    self.base = f(T.mjOBJ_BODY, m.nbody, C.ROOT_BODY)
    root = m.body_jntadr[self.base]
    self.root_q, self.root_v = int(m.jnt_qposadr[root]), int(m.jnt_dofadr[root])
    self.imu = f(T.mjOBJ_SITE, m.nsite, C.IMU_SITE)
    self.adr_linvel = int(m.sensor_adr[f(T.mjOBJ_SENSOR, m.nsensor, C.LOCAL_LINVEL_SENSOR)])
    self.adr_gyro = int(m.sensor_adr[f(T.mjOBJ_SENSOR, m.nsensor, C.GYRO_SENSOR)])
    self.adr_up = int(m.sensor_adr[f(T.mjOBJ_SENSOR, m.nsensor, C.UPVECTOR_SENSOR)])
    assert min(min(joints), self.act.min(), self.base, self.imu) >= 0, f"model has no Go2 with prefix {prefix!r}"
    self.spawn = (0.0, 0.0, home_height)
    self.spawn_yaw = 0.0
    self.target = np.zeros(3, np.float64)   # the race's command (vx, vy, yaw rate); slewed into self.cmd
    self.resets = 0
    self._clear()

  def _clear(self):
    self.mode = LOCO
    self.cmd = np.zeros(3, np.float32)
    self.last_action = np.zeros(C.NU, np.float32)
    self.phase = 0              # physics steps since the last reset: a decision when phase % DECIMATION == 0
    self.upright_count = 0
    self.fallen_steps = 0
    self.stalled_steps = 0
    self.state = RACING

  # --- state -------------------------------------------------------------------------------------------------------
  def up_z(self):
    return float(self.d.sensordata[self.adr_up + 2])

  def pos(self):
    return float(self.d.qpos[self.root_q]), float(self.d.qpos[self.root_q + 1])

  def yaw(self):
    w, x, y, z = (float(v) for v in self.d.qpos[self.root_q + 3:self.root_q + 7])
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))

  def planar_speed2(self):
    vx, vy = float(self.d.qvel[self.root_v]), float(self.d.qvel[self.root_v + 1])
    return vx * vx + vy * vy

  @property
  def locomoting(self):
    return self.mode == LOCO

  def update_state(self):
    """Unity AutoReset: race state from the up vector; reset after 5 s down or 10 s stalled. True = it reset."""
    up = self.up_z()
    self.state = FALLEN if up <= 0.0 else STUMBLE if up < STUMBLE_Z else RACING
    self.fallen_steps = self.fallen_steps + 1 if self.state == FALLEN else 0
    t = self.target
    wants = float(t[0] * t[0] + t[1] * t[1] + t[2] * t[2]) > 0.01
    self.stalled_steps = self.stalled_steps + 1 if wants and self.planar_speed2() < STALL_SPEED * STALL_SPEED else 0
    nan = math.isnan(self.d.qpos[self.root_q + 2]) or math.isnan(self.d.qvel[self.root_v])
    if nan or self.fallen_steps > FALLEN_STEPS or self.stalled_steps > STALL_STEPS:
      self.reset_to_spawn()
      self.resets += 1
      return True
    return False

  # --- the brain ---------------------------------------------------------------------------------------------------
  def gravity(self):
    return self.d.site_xmat[self.imu].reshape(3, 3).T @ np.array([0.0, 0.0, -1.0])

  def control(self):
    if self.phase % C.DECIMATION == 0:
      self.decide()
    self.phase += 1

  def decide(self):
    d = self.d
    up = self.up_z()
    self.upright_count = self.upright_count + 1 if up > UPRIGHT_Z else 0
    if self.mode == LOCO and up <= 0.0:
      self.mode = GETUP
      self.last_action[:] = 0
      self.cmd[:] = 0
    elif self.mode == GETUP and self.upright_count >= UPRIGHT_DECISIONS:
      self.mode = LOCO
      self.last_action[:] = 0
    q, v = d.qpos[self.qadr], d.qvel[self.vadr]
    lin, gyro = d.sensordata[self.adr_linvel:self.adr_linvel + 3], d.sensordata[self.adr_gyro:self.adr_gyro + 3]
    if self.mode == LOCO:
      tgt = self.target.astype(np.float32)
      self.cmd = (self.cmd + np.clip(tgt - self.cmd, -C.CMD_SLEW_STEP, C.CMD_SLEW_STEP)).astype(np.float32)
      obs = np.concatenate([lin, gyro, self.gravity(), q - DEFAULT, v, self.last_action, self.cmd]).astype(np.float32)
      action = np.clip(self.loco(obs), -1, 1).astype(np.float32)
      d.ctrl[self.act] = (DEFAULT + C.ACTION_SCALE * action).astype(np.float32)
    else:
      obs = np.concatenate([gyro, self.gravity(), q - DEFAULT, v, self.last_action]).astype(np.float32)
      action = np.clip(self.getup(obs), -1, 1).astype(np.float32)
      d.ctrl[self.act] = (q.astype(np.float32) + C.ACTION_SCALE * action).astype(np.float32)
    self.last_action = action

  # --- race hooks --------------------------------------------------------------------------------------------------
  def reset_to_spawn(self):
    """Back on its feet at the spawn point (the last checkpoint), home pose, still; brains start fresh."""
    m, d = self.m, self.d
    d.qvel[self.root_v:self.root_v + 6] = 0
    d.qvel[self.vadr] = 0
    x, y, z = self.spawn
    d.qpos[self.root_q:self.root_q + 7] = [x, y, z, math.cos(self.spawn_yaw * 0.5), 0.0, 0.0, math.sin(self.spawn_yaw * 0.5)]
    d.qpos[self.qadr] = DEFAULT
    d.ctrl[self.act] = DEFAULT
    self._clear()
    mujoco.mj_forward(m, d)

  def knock_over(self):
    """Flip onto its back in place (the race's -flip-at test of the get-up)."""
    d = self.d
    d.qpos[self.root_q + 2] = 0.45
    d.qpos[self.root_q + 3:self.root_q + 7] = [0.0, 1.0, 0.0, 0.0]
    d.qvel[self.root_v:self.root_v + 6] = 0
    mujoco.mj_forward(self.m, d)

  def restart_command_ramp(self):
    """The slewed command back to 0: frees a racer that braced against a fast command from a standstill."""
    self.cmd[:] = 0
