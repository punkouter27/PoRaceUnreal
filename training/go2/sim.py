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
        so.intra_op_num_threads = 1  # deterministic and fast enough for a 3-layer MLP
        self.session = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        self.obs_size = int(self.session.get_inputs()[0].shape[-1])

    def __call__(self, obs):
        return self.session.run(None, {self.input: obs.reshape(1, -1).astype(np.float32)})[0].reshape(-1)


def find(m, objtype, count, short):
    """Id of the object named `short`, or carrying it as a "_"-suffix (URLab prefixes names with the actor's). -1 = none."""
    for i in range(count):
        name = mujoco.mj_id2name(m, objtype, i) or ""
        if name == short or name.endswith("_" + short):
            return i
    return -1


def qpos_slot(m, slot):
    """qpos address of a slot as contract.py names it: "joint", "joint[k]" or "@body[k]" (RaceNames.h QposSlot)."""
    base, k = (slot[: slot.rindex("[")], int(slot[slot.rindex("[") + 1 : -1])) if slot.endswith("]") else (slot, 0)
    if base.startswith("@"):
        b = find(m, mujoco.mjtObj.mjOBJ_BODY, m.nbody, base[1:])
        j = m.body_jntadr[b] if b >= 0 and m.body_jntnum[b] > 0 else -1
    else:
        j = find(m, mujoco.mjtObj.mjOBJ_JOINT, m.njnt, base)
    return int(m.jnt_qposadr[j]) + k if j >= 0 else -1


class Go2Sim:
    def __init__(self, scene=C.SCENE_XML, model=None, home=None):
        """`model`: a compiled model to drive instead of the scene file (URLab's .mjb, names prefixed).
        `home`: {qpos address: value} start pose for a model without the "home" keyframe."""
        self.m = model if model is not None else mujoco.MjModel.from_xml_path(str(scene))
        m, T = self.m, mujoco.mjtObj
        self.d = mujoco.MjData(m)
        self.home = home
        self.imu = find(m, T.mjOBJ_SITE, m.nsite, C.IMU_SITE)
        self.act = np.array([find(m, T.mjOBJ_ACTUATOR, m.nu, a) for a in C.ACTUATOR_NAMES])
        joints = [find(m, T.mjOBJ_JOINT, m.njnt, j) for j in C.JOINT_NAMES]
        self.qadr, self.vadr = m.jnt_qposadr[joints], m.jnt_dofadr[joints]
        root = m.body_jntadr[find(m, T.mjOBJ_BODY, m.nbody, C.ROOT_BODY)]
        self.root_q, self.root_v = int(m.jnt_qposadr[root]), int(m.jnt_dofadr[root])
        self.adr_linvel = int(m.sensor_adr[find(m, T.mjOBJ_SENSOR, m.nsensor, C.LOCAL_LINVEL_SENSOR)])
        self.adr_gyro = int(m.sensor_adr[find(m, T.mjOBJ_SENSOR, m.nsensor, C.GYRO_SENSOR)])
        assert min(self.imu, self.act.min(), min(joints), root) >= 0, "model is missing a contract name"
        self.reset()

    def reset(self):
        if self.home is None:
            mujoco.mj_resetDataKeyframe(self.m, self.d, 0)
        else:
            mujoco.mj_resetData(self.m, self.d)
            for adr, value in self.home.items():
                self.d.qpos[adr] = value
        self.d.ctrl[self.act] = DEFAULT
        mujoco.mj_forward(self.m, self.d)
        self.last_action = np.zeros(C.NU, np.float32)
        self.command = np.zeros(3, np.float32)

    # --- state -----------------------------------------------------------------------------------------------------
    def gravity(self):
        """World down (0, 0, -1) in the imu frame; z = -1 standing upright, > 0 upside down."""
        return self.d.site_xmat[self.imu].reshape(3, 3).T @ np.array([0.0, 0.0, -1.0])

    def upright(self):
        return float(-self.gravity()[2])

    def local_linvel(self):
        return self.d.sensordata[self.adr_linvel : self.adr_linvel + 3]

    def gyro(self):
        return self.d.sensordata[self.adr_gyro : self.adr_gyro + 3]

    # --- observations ----------------------------------------------------------------------------------------------
    def obs_joystick(self):
        d = self.d
        return np.concatenate(
            [
                self.local_linvel(),
                self.gyro(),
                self.gravity(),
                d.qpos[self.qadr] - DEFAULT,
                d.qvel[self.vadr],
                self.last_action,
                self.command,
            ]
        ).astype(np.float32)

    def obs_getup(self):
        d = self.d
        return np.concatenate(
            [self.gyro(), self.gravity(), d.qpos[self.qadr] - DEFAULT, d.qvel[self.vadr], self.last_action]
        ).astype(np.float32)

    # --- stepping --------------------------------------------------------------------------------------------------
    def physics(self, n=C.DECIMATION):
        for _ in range(n):
            mujoco.mj_step(self.m, self.d)

    def step_joystick(self, policy, command_target):
        target = np.asarray(command_target, np.float32)
        self.command = self.command + np.clip(target - self.command, -C.CMD_SLEW_STEP, C.CMD_SLEW_STEP)
        obs = self.obs_joystick()
        action = np.clip(policy(obs), -1, 1).astype(np.float32)
        self.d.ctrl[self.act] = (DEFAULT + C.ACTION_SCALE * action).astype(np.float32)
        self.physics()
        self.last_action = action
        return obs, action

    def step_getup(self, policy):
        obs = self.obs_getup()
        action = np.clip(policy(obs), -1, 1).astype(np.float32)
        self.d.ctrl[self.act] = (self.d.qpos[self.qadr].astype(np.float32) + C.ACTION_SCALE * action).astype(np.float32)
        self.physics()
        self.last_action = action
        return obs, action


def brain(name) -> Policy:
    p = Path(name)
    return Policy(p if p.suffix == ".onnx" and p.exists() else BRAINS / f"{name}.onnx")
