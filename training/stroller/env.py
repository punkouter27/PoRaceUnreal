"""Stroller joystick env: a wheeled racer learns to roll at the commanded speed and turn rate (no legs, no gait).

Model: training/stroller/assets/scene_stroller.xml (make_model.py), the race's options at impratio 1 (at 100 the stiff
friction under the race's 1-iteration solver binds the three wheels and steering does nothing; see make_model.py).
Action (3, in [-1, 1]): front steer target (x STEER_MAX rad, position servo), left and right rear wheel torque
(x WHEEL_TORQUE N.m). Commands: forward speed and yaw rate (the sideways command is always 0: wheels cannot strafe).
Obs 'state' (20): local linvel 3, gyro 3, gravity 3, steer angle 1, steer rate 1, wheel speeds 3 (x 0.1),
last action 3, command 3. racelib/stroller.py and RacerStroller.cpp build the same 20 numbers.
"""

from pathlib import Path
from typing import Any

import jax
import jax.numpy as jp
import mujoco
from ml_collections import config_dict
from mujoco import mjx
from mujoco.mjx._src import math
from mujoco_playground._src import mjx_env

from stroller import make_model as M

SCENE = Path(__file__).resolve().parent / "assets" / "scene_stroller.xml"
SIM_DT, CTRL_DT = 0.004, 0.02
WHEEL_OBS_SCALE = 0.1
CONTACTS_PER_ENV = 16  # 6 wheel contacts rolling; a tipped frame adds a few


def default_config() -> config_dict.ConfigDict:
    return config_dict.create(
        ctrl_dt=CTRL_DT,
        sim_dt=SIM_DT,
        episode_length=1000,
        action_repeat=1,
        impratio=1.0,
        noise_config=config_dict.create(
            level=1.0, scales=config_dict.create(linvel=0.05, gyro=0.05, gravity=0.02, steer=0.01, wheel=0.2)
        ),
        reward_config=config_dict.create(
            scales=config_dict.create(
                tracking_lin_vel=1.5,
                tracking_ang_vel=1.0,
                side_slip=-0.5,
                orientation=-5.0,
                action_rate=-0.02,
                torques=-0.002,
                termination=-1.0,
            ),
            tracking_sigma=0.25,
        ),
        # uniform in [lo, a]; each axis zeroed with probability 1 - b at a resample (Go2 joystick sampler)
        command_config=config_dict.create(a=[2.5, 0.0, 1.2], lo=[-1.0, 0.0, -1.2], b=[0.9, 0.0, 0.6]),
        tip_up_z=0.5,  # chassis up-vector z below this = tipped over (episode ends)
        impl="warp",
        naconmax=CONTACTS_PER_ENV * 8192,
        njmax=64,
    )


class StrollerJoystick(mjx_env.MjxEnv):
    def __init__(
        self,
        config: config_dict.ConfigDict = None,
        config_overrides: dict[str, str | int | list[Any]] | None = None,
    ):
        super().__init__(config or default_config(), config_overrides)
        self._mj_model = mujoco.MjModel.from_xml_path(str(SCENE))
        self._mj_model.opt.impratio = self._config.impratio
        assert abs(self._mj_model.opt.timestep - self._config.sim_dt) < 1e-12
        assert self._mj_model.opt.disableflags & mujoco.mjtDisableBit.mjDSBL_EULERDAMP, (
            "the race runs with Euler damping off"
        )
        self._mjx_model = mjx.put_model(self._mj_model, impl=self._config.impl)
        self._xml_path = str(SCENE)
        m = self._mj_model
        self._init_q = jp.array(m.keyframe("home").qpos)
        self._imu = m.site("imu").id
        self._steer_q = m.jnt_qposadr[m.joint("steer").id]
        self._steer_v = m.jnt_dofadr[m.joint("steer").id]
        self._wheel_v = jp.array([m.jnt_dofadr[m.joint(n).id] for n in ("wheel_front", "wheel_rear_l", "wheel_rear_r")])
        self._cmd_a = jp.array(self._config.command_config.a)
        self._cmd_lo = jp.array(self._config.command_config.lo)
        self._cmd_b = jp.array(self._config.command_config.b)
        self._act_scale = jp.array([M.STEER_MAX, M.WHEEL_TORQUE, M.WHEEL_TORQUE])

    # --- sensors -------------------------------------------------------------------------------------------------------
    def local_linvel(self, data):
        return mjx_env.get_sensor_data(self.mj_model, data, "local_linvel")

    def gyro(self, data):
        return mjx_env.get_sensor_data(self.mj_model, data, "gyro")

    def upvector(self, data):
        return mjx_env.get_sensor_data(self.mj_model, data, "upvector")

    def gravity(self, data):
        return data.site_xmat[self._imu].T @ jp.array([0.0, 0.0, -1.0])

    def reset(self, rng: jax.Array) -> mjx_env.State:
        qpos = self._init_q
        rng, k1, k2, k3, k4, k5 = jax.random.split(rng, 6)
        qpos = qpos.at[0:2].set(jax.random.uniform(k1, (2,), minval=-0.5, maxval=0.5))
        yaw = jax.random.uniform(k2, (1,), minval=-3.14, maxval=3.14)
        qpos = qpos.at[3:7].set(math.axis_angle_to_quat(jp.array([0.0, 0.0, 1.0]), yaw))
        qvel = jp.zeros(self.mjx_model.nv)
        v0 = jax.random.uniform(k3, (), minval=-0.5, maxval=1.5)  # sometimes rolling already
        qvel = qvel.at[0:2].set(v0 * jp.array([jp.cos(yaw[0]), jp.sin(yaw[0])]))
        data = mjx_env.make_data(
            self.mj_model,
            qpos=qpos,
            qvel=qvel,
            ctrl=jp.zeros(self.mjx_model.nu),
            impl=self.mjx_model.impl.value,
            naconmax=self._config.naconmax,
            njmax=self._config.njmax,
        )
        data = mjx.forward(self.mjx_model, data)
        info = {
            "rng": rng,
            "command": jax.random.uniform(k4, shape=(3,), minval=self._cmd_lo, maxval=self._cmd_a),
            "steps_until_next_cmd": jp.round(jax.random.exponential(k5) * 5.0 / self.dt).astype(jp.int32),
            "last_act": jp.zeros(self.mjx_model.nu),
        }
        metrics = {f"reward/{k}": jp.zeros(()) for k in self._config.reward_config.scales.keys()}
        metrics["nan_resets"] = jp.zeros(())
        return mjx_env.State(data, self._get_obs(data, info), jp.zeros(()), jp.zeros(()), metrics, info)

    def step(self, state: mjx_env.State, action: jax.Array) -> mjx_env.State:
        action = jp.clip(action, -1.0, 1.0)
        data = mjx_env.step(self.mjx_model, state.data, action * self._act_scale, self.n_substeps)
        up = self.upvector(data)
        done = up[-1] < self._config.tip_up_z
        rewards = self._get_reward(data, action, state.info, done)
        rewards = {k: v * self._config.reward_config.scales[k] for k, v in rewards.items()}
        reward = jp.clip(sum(rewards.values()) * self.dt, 0.0, 10000.0)
        bad = (
            jp.isnan(data.qpos).any()
            | jp.isnan(data.qvel).any()
            | (jp.abs(data.qvel).max() > 500.0)
            | (jp.abs(data.qpos[:3]).max() > 100.0)
        )
        done = done | bad
        obs = jax.tree_util.tree_map(
            lambda o: jp.clip(jp.nan_to_num(o), -100.0, 100.0), self._get_obs(data, state.info)
        )
        reward = jp.where(bad, 0.0, reward)

        state.info["last_act"] = action
        state.info["steps_until_next_cmd"] -= 1
        state.info["rng"], k1, k2 = jax.random.split(state.info["rng"], 3)
        resample = state.info["steps_until_next_cmd"] <= 0
        state.info["command"] = jp.where(
            resample, self.sample_command(k1, state.info["command"]), state.info["command"]
        )
        state.info["steps_until_next_cmd"] = jp.where(
            done | resample,
            jp.round(jax.random.exponential(k2) * 5.0 / self.dt).astype(jp.int32),
            state.info["steps_until_next_cmd"],
        )
        for k, v in rewards.items():
            state.metrics[f"reward/{k}"] = jp.nan_to_num(v)
        state.metrics["nan_resets"] = bad.astype(jp.float32)
        return state.replace(data=data, obs=obs, reward=reward, done=done.astype(reward.dtype))

    def _noisy(self, info, x, scale):
        info["rng"], k = jax.random.split(info["rng"])
        return x + (2 * jax.random.uniform(k, shape=x.shape) - 1) * self._config.noise_config.level * scale

    def _get_obs(self, data, info) -> dict[str, jax.Array]:
        ns = self._config.noise_config.scales
        linvel, gyro, grav = self.local_linvel(data), self.gyro(data), self.gravity(data)
        steer = data.qpos[self._steer_q : self._steer_q + 1]
        steer_v = data.qvel[self._steer_v : self._steer_v + 1]
        wheels = data.qvel[self._wheel_v] * WHEEL_OBS_SCALE
        state = jp.hstack(
            [
                self._noisy(info, linvel, ns.linvel),
                self._noisy(info, gyro, ns.gyro),
                self._noisy(info, grav, ns.gravity),
                self._noisy(info, steer, ns.steer),
                steer_v,
                self._noisy(info, wheels, ns.wheel * WHEEL_OBS_SCALE),
                info["last_act"],
                info["command"],
            ]
        )
        privileged = jp.hstack(
            [
                state,
                linvel,
                gyro,
                grav,
                wheels,
                data.actuator_force,
                mjx_env.get_sensor_data(self.mj_model, data, "global_linvel"),
            ]
        )
        return {"state": state, "privileged_state": privileged}

    def _get_reward(self, data, action, info, done):
        sig = self._config.reward_config.tracking_sigma
        cmd = info["command"]
        v, w = self.local_linvel(data), self.gyro(data)
        grav = self.gravity(data)
        return {
            "tracking_lin_vel": jp.exp(-((cmd[0] - v[0]) ** 2 + v[1] ** 2) / sig),
            "tracking_ang_vel": jp.exp(-((cmd[2] - w[2]) ** 2) / sig),
            "side_slip": v[1] ** 2,
            "orientation": jp.sum(grav[:2] ** 2),
            "action_rate": jp.sum((action - info["last_act"]) ** 2),
            "torques": jp.sum((action[1:] * self._act_scale[1:]) ** 2),
            "termination": done.astype(jp.float32),
        }

    def sample_command(self, rng, x_k):
        rng, y_rng, w_rng, z_rng = jax.random.split(rng, 4)
        y_k = jax.random.uniform(y_rng, shape=(3,), minval=self._cmd_lo, maxval=self._cmd_a)
        z_k = jax.random.bernoulli(z_rng, self._cmd_b, shape=(3,))
        w_k = jax.random.bernoulli(w_rng, 0.5, shape=(3,))
        return x_k - w_k * (x_k - y_k * z_k)

    @property
    def xml_path(self) -> str:
        return self._xml_path

    @property
    def action_size(self) -> int:
        return self._mjx_model.nu

    @property
    def mj_model(self) -> mujoco.MjModel:
        return self._mj_model

    @property
    def mjx_model(self) -> mjx.Model:
        return self._mjx_model
