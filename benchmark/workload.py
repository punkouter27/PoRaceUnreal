"""PoRaceUnreal Workload: the real training/train.py (Brax PPO on MuJoCo Warp) with the Grandma g14 recipe.

g14 is the latest graduated training run (docs/rl_optimization_log.md, "Grandma g14"; its exact command is the g14
stage of training/queue_8h_overnight.sh): grandma env, 1024 envs, lr 5e-5, fine-tuned from final/grandma_g13_grad84
_params.pkl (the g13 @ 24.1M params it was restored from).

The trainer runs in the porace-trainer Docker image (training/Dockerfile), as training/launch.sh runs it, so this
script has two halves:
  host   (default; started by serve.py with any Python): makes the Meter (Machine and Machine load are read on
         Windows, not inside the container), starts the container and feeds the Meter the blocks it reports.
  inner  (--inner, inside the container): runs train.py via runpy and reports one block per PPO training step.
Brax jits a whole training step (env rollout + SGD) into one program, so Sim vs Learn time is not observable: each
block is fed as sim = the step's wall time, learn = 0, and the Workload says so (split).
"""

from __future__ import annotations

import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "porace-trainer"
CONTAINER = "porace_benchmark"  # porace_* = a GPU run that training/queue_8h_overnight.sh waits for
LOGDIR = "runs/_benchmark"  # throwaway; training/runs/ is gitignored and no real run uses this name
RESTORE = "final/grandma_g13_grad84_params.pkl"
# preflight.py guesses an untagged params file's character from its file name, and "g13" contains "g1", so it stops
# the g14 recipe ("looks like g1's policy"). The benchmark restores a byte-identical copy under a neutral name.
RESTORE_COPY = "runs/_benchmark_init/grandma_start_params.pkl"
# Same settings as the g14 run (training/queue_8h_overnight.sh). Change these and the Workload ID changes.
ARGS = [
    "--env", "grandma", "--num_envs", "1024", "--timesteps", "120000000", "--lr", "5e-5", "--entropy", "0.005",
    "--restore_params", RESTORE,
    "--set", "realism.gait_symmetry=-4.5", "--set", "realism.torso_ang_acc=-0.4", "--set", "realism.arm_swing=-0.1",
    "--set", "realism.heat=-0.1", "--set", "realism.action_delay_prob=0.3", "--set", "realism.cmd_accel=6.0",
    "--set", "reward_config.scales.tracking_lin_vel=3.5", "--set", "reward_config.scales.tracking_lin_vel_wide=4.5",
    "--set", "reward_config.scales.tracking_ang_vel=2.0", "--set", "reward_config.scales.tracking_ang_vel_wide=1.0",
    "--set", "reward_config.scales.pose=-0.015", "--set", "reward_config.scales.stand_still=-0.5",
    "--set", "reward_config.scales.alive=5.0", "--set", "reward_config.scales.action_rate=-0.1",
    "--set", "positive_reward=False",
]  # fmt: skip
# Warp prints a solver warning per step; the same filter as training/launch.sh keeps the page's log readable.
NOISE = re.compile(
    r"iterations limit reached|iterationtions|iteratioations|linesearch|To disable the print|warning: m.opt|^\s*$"
    r"|ls_iterations|^To dis|NVIDIA|container image|nvidia.com|license|By pulling|convenience|CUDA"
)


# ---------------------------------------------------------------- inner (in the container)


def inner() -> None:
    """Runs train.py with ARGS; prints @@WORKLOAD once ppo.train is called, then @@BLOCK <seconds> <steps> per PPO
    training step. A block that follows an eval / checkpoint save is not reported (it is not training work)."""
    import importlib.metadata as md

    from brax.training import acting, logger
    from brax.training.agents.ppo import train as ppo_train

    def version(pkg: str) -> str | None:
        try:
            return md.version(pkg)
        except md.PackageNotFoundError:
            return None

    clock = {"t": None, "skip": False, "num_envs": 1}
    train = ppo_train.train

    def train_(**kw):
        logdir = Path(LOGDIR)
        ppo_params = json.loads((logdir / "ppo_params.json").read_text())
        env_cfg = json.loads((logdir / "checkpoints" / "config.json").read_text())
        net = kw["network_factory"].keywords
        clock["num_envs"] = kw["num_envs"]
        workload = dict(
            repo="PoRaceUnreal",
            trainer=f"brax {version('brax')} ppo (jax {version('jax')}, mujoco_warp {version('mujoco-warp')})",
            script="training/train.py (docker image porace-trainer, training/Dockerfile)",
            args=" ".join(ARGS),
            recipe="Grandma g14 (docs/rl_optimization_log.md; training/queue_8h_overnight.sh)",
            num_envs=kw["num_envs"],
            horizon=kw["unroll_length"],
            batch=f"{kw['batch_size']} x {kw['num_minibatches']} minibatches x {kw['num_updates_per_batch']} updates",
            net=list(net.get("policy_hidden_layer_sizes", [])),
            value_net=list(net.get("value_hidden_layer_sizes", [])),
            config_hash=core.workload_id({"ppo": ppo_params, "env": env_cfg}),
            split="not observable (jitted): sim_ms = whole Step, learn_ms = 0",
            restore_note=f"restores a copy of {RESTORE} named {Path(RESTORE_COPY).name} (preflight name check)",
        )
        versions = dict(
            python=sys.version.split()[0],
            jax=version("jax"),
            brax=version("brax"),
            mujoco=version("mujoco"),
            mujoco_warp=version("mujoco-warp"),
            playground=version("playground"),
        )
        print("@@WORKLOAD " + json.dumps({"workload": workload, "versions": versions}), flush=True)
        sys.stdin.readline()  # the host reads Machine load before the run, then says go
        clock["t"] = time.monotonic()
        return train(**kw)

    update = logger.EpisodeMetricsLogger.update_episode_metrics

    def update_(self, episode_metrics, dones, train_metrics):
        # Called from the jitted training step (jax.debug.callback) once per PPO training step, after its SGD update.
        update(self, episode_metrics, dones, train_metrics)
        now = time.monotonic()
        if not clock["skip"]:
            steps = int(dones.size) / clock["num_envs"]
            print(f"@@BLOCK {now - clock['t']:.6f} {steps:g}", flush=True)
        clock["t"], clock["skip"] = now, False

    run_eval = acting.Evaluator.run_evaluation

    def run_eval_(self, *a, **k):
        clock["skip"] = True
        return run_eval(self, *a, **k)

    ppo_train.train = train_
    logger.EpisodeMetricsLogger.update_episode_metrics = update_
    acting.Evaluator.run_evaluation = run_eval_
    os.chdir("/work")
    sys.path.insert(0, "/work")
    shutil.rmtree(LOGDIR, ignore_errors=True)
    Path(RESTORE_COPY).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RESTORE, RESTORE_COPY)
    sys.argv = ["train.py", *[RESTORE_COPY if x == RESTORE else x for x in ARGS], "--logdir", LOGDIR]
    try:
        runpy.run_path("train.py", run_name="__main__")
    except BaseException as e:  # noqa: BLE001 - every failure becomes a failed row
        print("@@FAIL " + core.fail_text(e), flush=True)
        raise


# ---------------------------------------------------------------- host


def docker(*a: str) -> str:
    return core._run(["docker", *a], timeout=30).strip()


def host() -> None:
    meter: core.Meter | None = None
    fail = None

    def finish_failed(error: str) -> None:
        nonlocal meter
        if meter is None:
            meter = core.Meter({"repo": "PoRaceUnreal", "args": " ".join(ARGS)}, {"python": sys.version.split()[0]})
        meter.finish(ok=False, error=error)

    if not docker("image", "inspect", IMAGE, "--format", "{{.Id}}"):
        finish_failed(f"docker image {IMAGE} missing or Docker not running (benchmark.ps1 builds it)")
    docker("rm", "-f", CONTAINER)  # a leftover from a killed Benchmark
    cmd = ["docker", "run", "--rm", "--init", "-i", "--log-driver", "none", "--gpus", "all", "--name", CONTAINER]
    cmd += ["-v", f"{ROOT / 'training'}:/work", "-v", f"{ROOT / 'benchmark'}:/bench:ro"]
    cmd += [IMAGE, "python", "-u", "/bench/workload.py", "--inner"]
    core.say("starting the trainer container (JAX compiles the training step: a minute or more)")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    try:
        for raw in proc.stdout:
            line = raw.rstrip()
            if line.startswith("@@BLOCK ") and meter is not None:
                seconds, steps = (float(x) for x in line.split()[1:3])
                meter.block(seconds, 0.0, steps)
            elif line.startswith("@@WORKLOAD "):
                info = json.loads(line[len("@@WORKLOAD ") :])
                info["versions"]["image"] = docker("image", "inspect", IMAGE, "--format", "{{.Id}}")[7:19]
                meter = core.Meter(info["workload"], info["versions"], warmup_blocks=2)
                meter.on_exit.append(lambda: docker("kill", CONTAINER))
                proc.stdin.write("go\n")
                proc.stdin.flush()
            elif line.startswith("@@FAIL "):
                fail = line[len("@@FAIL ") :]
            elif not NOISE.search(line):
                print(line, flush=True)
        code = proc.wait()
        finish_failed(fail or f"trainer exited (code {code}) before the measured window ended")
    except BaseException as e:  # noqa: BLE001 - every failure becomes a failed row, never a silent miss
        docker("kill", CONTAINER)
        finish_failed(core.fail_text(e))


if __name__ == "__main__":
    inner() if "--inner" in sys.argv else host()
