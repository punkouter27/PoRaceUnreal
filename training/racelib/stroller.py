"""The stroller (a wheeled racer) in a shared race model: one rolling brain, no get-up (a tipped stroller is reset after
5 s, like any fallen racer). Source/PoRaceUnreal/RacerStroller.cpp is the same class line for line.

Brain loop = training/stroller/env.py's step: the observation from the state before this decision, action clipped to
[-1, 1], ctrl = action x (steer max, wheel torque, wheel torque), held for DECIMATION physics steps. The race's command
is slewed into the one the brain sees (it trained on jumps; slewing only makes the race gentler).
Same call order as Go2Racer: update_state() (the race), then control().
"""

import math

import mujoco
import numpy as np
from go2.sim import find

from racelib.go2racer import FALLEN, FALLEN_STEPS, RACING, STALL_SPEED, STALL_STEPS, STUMBLE, STUMBLE_Z

T = mujoco.mjtObj
DECIMATION = 5
CMD_SLEW_STEP = 6.0 * 0.004 * DECIMATION  # 6 m/s^2 (and rad/s^2), per decision
WHEEL_OBS_SCALE = 0.1
TIP_UP_Z = 0.5  # chassis up z below this = tipped over (training ended the episode there)
WHEELS = ("wheel_front", "wheel_rear_l", "wheel_rear_r")
ACTUATORS = ("steer", "wheel_rear_l", "wheel_rear_r")


class StrollerRacer:
    def __init__(self, m, d, prefix, card, loco):
        self.m, self.d, self.prefix, self.loco = m, d, prefix, loco
        f = lambda t, n, name: find(m, t, n, prefix + name)  # noqa: E731
        self.act = np.array([f(T.mjOBJ_ACTUATOR, m.nu, a) for a in ACTUATORS])
        self.act_scale = np.array([card["steerMax"], card["wheelTorque"], card["wheelTorque"]], np.float32)
        steer = f(T.mjOBJ_JOINT, m.njnt, "steer")
        wheels = [f(T.mjOBJ_JOINT, m.njnt, w) for w in WHEELS]
        self.steer_q, self.steer_v = int(m.jnt_qposadr[steer]), int(m.jnt_dofadr[steer])
        self.wheel_v = m.jnt_dofadr[wheels]
        self.qadr = np.array([self.steer_q] + list(m.jnt_qposadr[wheels]))
        self.vadr = np.array([self.steer_v] + list(self.wheel_v))
        self.base = f(T.mjOBJ_BODY, m.nbody, card["rootBody"])
        root = m.body_jntadr[self.base]
        self.root_q, self.root_v = int(m.jnt_qposadr[root]), int(m.jnt_dofadr[root])
        self.imu = f(T.mjOBJ_SITE, m.nsite, "imu")
        sensor = lambda n: int(m.sensor_adr[f(T.mjOBJ_SENSOR, m.nsensor, n)])  # noqa: E731
        self.adr_linvel, self.adr_gyro, self.adr_up = sensor("local_linvel"), sensor("gyro"), sensor("upvector")
        assert min(steer, min(wheels), self.act.min(), self.base, self.imu) >= 0, (
            f"model has no stroller with prefix {prefix!r}"
        )
        self.home_height = card["homeHeight"]
        self.spawn = (0.0, 0.0, self.home_height)
        self.spawn_yaw = 0.0
        self.target = np.zeros(3, np.float64)
        self.resets = 0
        self._clear()

    def _clear(self):
        self.mode = "roll"
        self.cmd = np.zeros(3, np.float32)
        self.last_action = np.zeros(3, np.float32)
        self.obs = np.zeros(20, np.float32)
        self.phase = 0
        self.fallen_steps = 0
        self.stalled_steps = 0
        self.state = RACING

    # --- state -------------------------------------------------------------------------------------------------------
    def up_z(self):
        return float(self.d.sensordata[self.adr_up + 2])

    def pos(self):
        return float(self.d.qpos[self.root_q]), float(self.d.qpos[self.root_q + 1])

    def yaw(self):
        w, x, y, z = (float(v) for v in self.d.qpos[self.root_q + 3 : self.root_q + 7])
        return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))

    def planar_speed2(self):
        vx, vy = float(self.d.qvel[self.root_v]), float(self.d.qvel[self.root_v + 1])
        return vx * vx + vy * vy

    @property
    def locomoting(self):
        return True

    def update_state(self):
        """Tipped (up z below 0.5) counts as fallen; reset after 5 s tipped or 10 s stalled. True = it reset."""
        up = self.up_z()
        self.state = FALLEN if up < TIP_UP_Z else STUMBLE if up < STUMBLE_Z else RACING
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
        if self.phase % DECIMATION == 0:
            self.decide()
        self.phase += 1

    def decide(self):
        d = self.d
        tgt = self.target.astype(np.float32)
        tgt[1] = 0.0  # wheels cannot strafe; the brain never saw a sideways command
        self.cmd = (self.cmd + np.clip(tgt - self.cmd, -CMD_SLEW_STEP, CMD_SLEW_STEP)).astype(np.float32)
        lin, gyro = d.sensordata[self.adr_linvel : self.adr_linvel + 3], d.sensordata[self.adr_gyro : self.adr_gyro + 3]
        obs = np.concatenate(
            [
                lin,
                gyro,
                self.gravity(),
                d.qpos[self.steer_q : self.steer_q + 1],
                d.qvel[self.steer_v : self.steer_v + 1],
                d.qvel[self.wheel_v] * WHEEL_OBS_SCALE,
                self.last_action,
                self.cmd,
            ]
        ).astype(np.float32)
        self.obs = obs
        action = np.clip(self.loco(obs), -1, 1).astype(np.float32)
        d.ctrl[self.act] = action * self.act_scale
        self.last_action = action

    # --- race hooks --------------------------------------------------------------------------------------------------
    def reset_to_spawn(self):
        """Back on its wheels at the spawn point (the last checkpoint), still, steering straight; the brain starts fresh."""
        m, d = self.m, self.d
        d.qvel[self.root_v : self.root_v + 6] = 0
        d.qvel[self.vadr] = 0
        x, y, z = self.spawn
        d.qpos[self.root_q : self.root_q + 7] = [
            x,
            y,
            z,
            math.cos(self.spawn_yaw * 0.5),
            0.0,
            0.0,
            math.sin(self.spawn_yaw * 0.5),
        ]
        d.qpos[self.qadr] = 0
        d.ctrl[self.act] = 0
        self._clear()
        mujoco.mj_forward(m, d)

    def knock_over(self):
        """Tip onto its side in place (the race's -flip-at test: it lies there until the 5 s reset)."""
        d = self.d
        d.qpos[self.root_q + 2] = 0.45
        d.qpos[self.root_q + 3 : self.root_q + 7] = [math.cos(math.pi / 4), math.sin(math.pi / 4), 0.0, 0.0]
        d.qvel[self.root_v : self.root_v + 6] = 0
        mujoco.mj_forward(self.m, d)

    def restart_command_ramp(self):
        self.cmd[:] = 0
