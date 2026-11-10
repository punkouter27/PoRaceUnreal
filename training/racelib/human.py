"""A human racer (Matt; later Grandma) in a shared race model: the G1-layout walking brain, the gait clock, and the
race's handling of a fall. Source/PoRaceUnreal/RacerHuman.cpp is the same class line for line.

The brain loop is training/g1/sim.py's control_step (what the brain was trained and graduated on):
  slew the command; build the observation (phase from BEFORE this step's advance); act (actions are NOT clipped);
  ctrl = default + 0.5 * action; physics; then advance the gait phase by this step's command (not on the first step).
Around it, the Unity race's MattController rules:
  down  = pelvis below fallenPelvisZ, or the torso's up z below fallenUpZ (checked each decision)
  limp  = down for more than limpAfterDecisions decisions: targets follow the joints (no getup brain), last action 0,
          until the 5 s fall reset puts him back at the last checkpoint
Same call order as Go2Racer: update_state() (the race), then control().
"""
import math

import mujoco
import numpy as np

from go2.sim import find
from racelib.go2racer import FALLEN, FALLEN_STEPS, RACING, STALL_SPEED, STALL_STEPS, STUMBLE, STUMBLE_Z

T = mujoco.mjtObj
SIM_DT, DECIMATION, ACTION_SCALE = 0.004, 5, 0.5
CTRL_DT = SIM_DT * DECIMATION
CMD_SLEW_STEP = 6.0 * CTRL_DT
LOCO, LIMP = "loco", "limp"


def wrap(p):
  """(p + pi) mod 2 pi - pi, Python's float modulo (RacerHuman.cpp does fmod, then adds 2 pi to a negative)."""
  return (p + np.pi) % (2 * np.pi) - np.pi


class HumanRacer:
  def __init__(self, m, d, prefix, card, fingerprint, loco):
    self.m, self.d, self.prefix, self.loco = m, d, prefix, loco
    f = lambda t, n, name: find(m, t, n, prefix + name)  # noqa: E731
    joints = fingerprint["joints"]
    self.nu = len(joints)
    self.default = np.array(fingerprint["default_pose"], np.float32)
    self.act = np.array([f(T.mjOBJ_ACTUATOR, m.nu, a) for a in fingerprint["actuators"]])
    jid = [f(T.mjOBJ_JOINT, m.njnt, j) for j in joints]
    self.qadr, self.vadr = m.jnt_qposadr[jid], m.jnt_dofadr[jid]
    self.base = f(T.mjOBJ_BODY, m.nbody, fingerprint["root_body"])
    root = m.body_jntadr[self.base]
    self.root_q, self.root_v = int(m.jnt_qposadr[root]), int(m.jnt_dofadr[root])
    s = card["sensors"]
    self.imu = f(T.mjOBJ_SITE, m.nsite, s["imu"])
    sensor = lambda n: int(m.sensor_adr[f(T.mjOBJ_SENSOR, m.nsensor, n)])  # noqa: E731
    self.adr_linvel, self.adr_gyro, self.adr_up = sensor(s["linvel"]), sensor(s["gyro"]), sensor(s["up"])
    assert min(min(jid), self.act.min(), self.base, self.imu) >= 0, f"model has no human with prefix {prefix!r}"
    g = card["gait"]
    self.gait_hz, self.gait_slope, self.gait_v0 = g["hz"], g["slope"], g["v0"]
    self.fallen_pelvis_z, self.fallen_up_z, self.limp_after = card["fallenPelvisZ"], card["fallenUpZ"], card["limpAfterDecisions"]
    self.home_height = card["homeHeight"]
    self.spawn = (0.0, 0.0, self.home_height)
    self.spawn_yaw = 0.0
    self.target = np.zeros(3, np.float64)
    self.resets = 0
    self._clear()

  def _clear(self):
    self.mode = LOCO
    self.cmd = np.zeros(3, np.float32)
    self.last_action = np.zeros(self.nu, np.float32)
    self.phase = 0.0
    self.decisions = 0          # control steps since the last reset (the phase does not advance on the first)
    self.step_phase = 0         # physics steps since the last reset: a decision when step_phase % DECIMATION == 0
    self.down_decisions = 0
    self.upright = True
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
    return True   # one brain: limp is a state of the body, not a mode change (Unity: Locomoting = has a policy)

  def update_state(self):
    """Unity AutoReset for a human: fallen = up z below 0 or down at the last decision."""
    up = self.up_z()
    self.state = FALLEN if up < 0.0 or not self.upright else STUMBLE if up < STUMBLE_Z else RACING
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
    if self.step_phase % DECIMATION == 0:
      self.decide()
    self.step_phase += 1

  def decide(self):
    d = self.d
    down = float(d.qpos[self.root_q + 2]) < self.fallen_pelvis_z or self.up_z() < self.fallen_up_z
    self.down_decisions = self.down_decisions + 1 if down else 0
    self.upright = not down
    tgt = self.target.astype(np.float32)
    self.cmd = (self.cmd + np.clip(tgt - self.cmd, -CMD_SLEW_STEP, CMD_SLEW_STEP)).astype(np.float32)
    q, v = d.qpos[self.qadr], d.qvel[self.vadr]
    pl, pr = float(wrap(self.phase)), float(wrap(np.pi + self.phase))
    clock = [math.cos(pl), math.cos(pr), math.sin(pl), math.sin(pr)]   # the C library's cos / sin, as RacerHuman.cpp
    obs = np.concatenate([d.sensordata[self.adr_linvel:self.adr_linvel + 3], d.sensordata[self.adr_gyro:self.adr_gyro + 3],
                          self.gravity(), self.cmd, q - self.default, v, self.last_action, clock]).astype(np.float32)
    self.obs = obs
    if self.down_decisions > self.limp_after:
      self.mode = LIMP
      self.last_action = np.zeros(self.nu, np.float32)
      d.ctrl[self.act] = q.astype(np.float32)
    else:
      self.mode = LOCO
      action = self.loco(obs).astype(np.float32)   # the trainer does not clip actions
      d.ctrl[self.act] = (self.default + ACTION_SCALE * action).astype(np.float32)
      self.last_action = action
    if self.decisions >= 1:
      dphi = 2 * np.pi * CTRL_DT * (self.gait_hz + self.gait_slope * max(0.0, abs(float(self.cmd[0])) - self.gait_v0))
      self.phase = wrap(self.phase + dphi)
    self.decisions += 1

  # --- race hooks --------------------------------------------------------------------------------------------------
  def reset_to_spawn(self):
    """On his feet at the spawn point in the knees-bent pose, still; the brain and the gait clock start fresh."""
    m, d = self.m, self.d
    d.qvel[self.root_v:self.root_v + 6] = 0
    d.qvel[self.vadr] = 0
    x, y, z = self.spawn
    d.qpos[self.root_q:self.root_q + 7] = [x, y, z, math.cos(self.spawn_yaw * 0.5), 0.0, 0.0, math.sin(self.spawn_yaw * 0.5)]
    d.qpos[self.qadr] = self.default
    d.ctrl[self.act] = self.default
    self._clear()
    mujoco.mj_forward(m, d)

  def knock_over(self):
    """Onto his back in place (the race's -flip-at test), as the Unity MattController: pelvis at 0.35 m, pitched 90 degrees
    back. (Upside down like the Go2 put a 1.9 m body's legs into the floor, and the solver threw him off the track.)"""
    d = self.d
    d.qpos[self.root_q + 2] = 0.35
    d.qpos[self.root_q + 3:self.root_q + 7] = [math.cos(math.pi / 4), 0.0, -math.sin(math.pi / 4), 0.0]
    d.qvel[self.root_v:self.root_v + 6] = 0
    mujoco.mj_forward(self.m, d)

  def restart_command_ramp(self):
    self.cmd[:] = 0
