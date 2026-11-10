"""CPU MuJoCo reference for the Go2: the observation, action map and timing every runtime must reproduce.

Only needs mujoco, numpy and onnxruntime (no JAX), so it runs on Windows outside the trainer image.
Used by version_check.py and by the reference race (race.py). The Unreal controller mirrors this file.

Control step (50 Hz), in this order:
  1. slew the command toward its target (CMD_SLEW)
  2. build the observation from the state *before* the step
  3. action = clip(policy(obs), -1, 1)
  4. ctrl = default pose + ACTION_SCALE * action   (get-up: current joint angles + ACTION_SCALE * action)
  5. DECIMATION physics steps
"""
from pathlib import Path

import mujoco
import numpy as np

from . import constants as C

Q, V = slice(7, C.NQ_ROBOT), slice(6, C.NV_ROBOT)
DEFAULT = np.array(C.DEFAULT_POSE, np.float32)
BRAINS = C.ROOT_PATH / "models" / "brains"


class Policy:
  """An exported ONNX brain: float32 obs (1, n) -> float32 action (12,)."""

  def __init__(self, path):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = 1   # deterministic and fast enough for a 3-layer MLP
    self.session = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
    self.input = self.session.get_inputs()[0].name
    self.obs_size = int(self.session.get_inputs()[0].shape[-1])

  def __call__(self, obs):
    return self.session.run(None, {self.input: obs.reshape(1, -1).astype(np.float32)})[0].reshape(-1)


class Go2Sim:
  def __init__(self, scene=C.SCENE_XML):
    self.m = mujoco.MjModel.from_xml_path(str(scene))
    self.d = mujoco.MjData(self.m)
    self.imu = self.m.site(C.IMU_SITE).id
    self.base = self.m.body(C.ROOT_BODY).id
    self.adr_linvel = int(self.m.sensor_adr[self.m.sensor(C.LOCAL_LINVEL_SENSOR).id])
    self.adr_gyro = int(self.m.sensor_adr[self.m.sensor(C.GYRO_SENSOR).id])
    self.reset()

  def reset(self):
    mujoco.mj_resetDataKeyframe(self.m, self.d, 0)
    mujoco.mj_forward(self.m, self.d)
    self.d.ctrl[:] = DEFAULT
    self.last_action = np.zeros(C.NU, np.float32)
    self.command = np.zeros(3, np.float32)

  # --- state -----------------------------------------------------------------------------------------------------
  def gravity(self):
    """World down (0, 0, -1) in the imu frame; z = -1 standing upright, > 0 upside down."""
    return self.d.site_xmat[self.imu].reshape(3, 3).T @ np.array([0.0, 0.0, -1.0])

  def upright(self):
    return float(-self.gravity()[2])

  def local_linvel(self):
    return self.d.sensordata[self.adr_linvel:self.adr_linvel + 3]

  def gyro(self):
    return self.d.sensordata[self.adr_gyro:self.adr_gyro + 3]

  # --- observations ----------------------------------------------------------------------------------------------
  def obs_joystick(self):
    d = self.d
    return np.concatenate([self.local_linvel(), self.gyro(), self.gravity(), d.qpos[Q] - DEFAULT, d.qvel[V],
                           self.last_action, self.command]).astype(np.float32)

  def obs_getup(self):
    d = self.d
    return np.concatenate([self.gyro(), self.gravity(), d.qpos[Q] - DEFAULT, d.qvel[V], self.last_action]).astype(np.float32)

  # --- stepping --------------------------------------------------------------------------------------------------
  def physics(self, n=C.DECIMATION):
    for _ in range(n):
      mujoco.mj_step(self.m, self.d)

  def step_joystick(self, policy, command_target):
    target = np.asarray(command_target, np.float32)
    self.command = self.command + np.clip(target - self.command, -C.CMD_SLEW_STEP, C.CMD_SLEW_STEP)
    obs = self.obs_joystick()
    action = np.clip(policy(obs), -1, 1).astype(np.float32)
    self.d.ctrl[:] = (DEFAULT + C.ACTION_SCALE * action).astype(np.float32)
    self.physics()
    self.last_action = action
    return obs, action

  def step_getup(self, policy):
    obs = self.obs_getup()
    action = np.clip(policy(obs), -1, 1).astype(np.float32)
    self.d.ctrl[:] = (self.d.qpos[Q].astype(np.float32) + C.ACTION_SCALE * action).astype(np.float32)
    self.physics()
    self.last_action = action
    return obs, action


def brain(name) -> Policy:
  p = Path(name)
  return Policy(p if p.suffix == ".onnx" and p.exists() else BRAINS / f"{name}.onnx")
