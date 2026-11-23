# Diagnostics overlay, idle demo mode and editor-exposed reward config

Po Game Standard C9 / C10 / C12 / C13. Code: `Source/PoRaceUnreal/RaceShowcase.*` and `RaceRewardConfig.*` (this repo's own copy).

## Diagnostics overlay (Tab)
`Tab` (or the 44 px "i" button top-right on touch devices; `-ShowcaseTouch` shows it on desktop) toggles an opaque
panel (#121826, text #e6e9f2, ~14:1) with FPS, the current episode reward, inference latency (rolling mean of the last
60 policy steps, ms) and the curriculum stage. `-DiagOverlay` starts with it open.

The overlay's **Benchmark sim speed (sim steps/s)** button steps a private copy of the loaded MuJoCo model (one
environment, no policy, no rendering) on this CPU for at most `BenchmarkMaxSeconds` (1 s) / `BenchmarkMaxSteps`
(20 000) and shows steps per second and the real-time factor. It measures CPU simulation speed, which bounds a CPU
rollout; it is not the GPU (MJX / Brax) trainer's throughput, and the result line says so. `-ShowcaseBench` runs it once
3 s after start and logs `Showcase: benchmark ...`.

Game hook: ARaceHUD (`RaceHUD.cpp`): the leader's distance as the reward proxy, brain inference time measured around `FRaceBrain::Run` on the physics thread, the leader's brain matched to a curriculum rung. In the menu, demo mode starts a race with the current choices; races follow each other until input.

## Idle demo mode
After `IdleSeconds` (30 s) without keyboard, mouse, touch or gamepad input: the HUD hides, every agent runs on its
trained policy (inference only) and the showcase cameras cycle every `CameraDwellSeconds` (7 s): Broadcast, Follow, Orbit (ARaceDirector camera modes). Any input
returns control and restores the HUD, mode and camera. A small "Demo - press any key" hint stays at the bottom.
Frames longer than `MaxIdleFrameSeconds` (0.25 s: level loads, shader compiles) do not count as idle time. Demo mode
never starts under `-RaceUiTest` or `-NoDemo`, so it cannot take over a UI test.

## Editor-first config
- `URaceShowcaseConfig` (DataAsset): idle threshold, long-frame cut-off, camera list, dwell time, overlay key, latency
  window, benchmark bounds, touch button.
- `URaceRewardConfig` (DataAsset): penalty weights `TorqueSqWeight`, `JointAngVelSqWeight`, `ActionRateSqWeight`,
  `FootSlipWeight` and the curriculum stages (name, threshold, metric).
- The assets in use are `/Game/Project/DataAssets/DA_RaceShowcaseConfig` and `DA_RaceRewardConfig`, picked in
  `Config/DefaultGame.ini` (Project Settings > Game > Race Showcase); empty = the C++ defaults.
- The defaults mirror `training/reward_config.json`, which the Python trainer reads; a pytest (`test_unreal_reward_mirror.py`) fails when the
  two differ. Change both together.

Shipped brains (training/final, Content/Brains) predate `torque_sq` / `joint_ang_vel_sq` and the humans' action-rate / foot-slip weights: they were NOT retrained. Changing a weight only affects future training runs.

## Unattended check
`UnrealEditor.exe <uproject> -game -windowed -ResX=1600 -ResY=900 -ShowcaseCapture=<dir> -ShowcaseTouch` writes
`overlay_on.png`, `overlay_off.png`, `demo_a.png`, `demo_b.png` into `<dir>` (demo shots after 35 s and one dwell later),
then quits. `-ShowcaseIdle=<s>` overrides the idle threshold.

## Gaze
The physics bodies have no neck joint, so gaze is render-only: `ARacerVisual` turns the Head bone of a human racer's
skin toward the nearest rival ahead within `GazeRange` (8 m), else straight ahead, at most `GazeMaxDegrees` (60) off the
torso, eased at `GazeSpeed`. The simulation is untouched; the log line `racer visual matt_: gaze target ...` reports it.

## Tests for the idle clock and the penalty log
- `PoRace.Showcase.IdleClock` (Source/PoRaceUnreal/RaceShowcaseTests.cpp, run rendered: see AGENTS.md "Verify") feeds
  the clock 45 s, 15 s and 0.26 s frames and checks they never count as idle time; 30 s of normal frames start demo mode.
- The trainer logs each penalty term on its own (`training/train.py` progress: TensorBoard `penalty/pen_torque_sq`,
  `penalty/pen_joint_ang_vel_sq`, `penalty/pen_action_rate_sq`, `penalty/pen_foot_slip`, also printed per eval), from
  `reward_config.penalty_log`; tests in `tests/test_reward_config.py` and `tests/test_reward_terms.py` (no training run).

## Web policy viewer (/viewer)
The showcase site's `/viewer` runs the racers' shipped ONNX brains in the browser (onnxruntime-web 1.20.1, WASM, one
thread) on recorded CPU MuJoCo races (`docs/parity/*.json`: Go2 walk / fast / steeple, Matt) and checks every output
against the recorded action; the console logs `[policy] <brain>.onnx (<racer>) inference in the browser ...`. The
bodies replay the recording (no physics in the page). Tab or the "i" button shows FPS, inference latency, policy vs
recorded, a reward proxy (metres travelled: the recordings store no reward), the curriculum stage and the mode, with a
line saying what each number measures. 30 s without input starts demo mode (`web/idle.js`, frames > 0.25 s ignored,
tested by `web/idle.test.mjs` through `tests/test_web_idle.py`).
