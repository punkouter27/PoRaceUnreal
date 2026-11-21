# Diagnostics overlay, idle demo mode and editor-exposed reward config

Po Game Standard C9 / C10 / C12 / C13. Code: `Source/PoRaceUnreal/RaceShowcase.*` and `RaceRewardConfig.*` (this repo's own copy).

## Diagnostics overlay (Tab)
`Tab` (or the 44 px "i" button top-right on touch devices; `-ShowcaseTouch` shows it on desktop) toggles an opaque
panel (#121826, text #e6e9f2, ~14:1) with FPS, the current episode reward, inference latency (rolling mean of the last
60 policy steps, ms) and the curriculum stage. `-DiagOverlay` starts with it open.

Game hook: ARaceHUD (`RaceHUD.cpp`): the leader's distance as the reward proxy, brain inference time measured around `FRaceBrain::Run` on the physics thread, the leader's brain matched to a curriculum rung. In the menu, demo mode starts a race with the current choices; races follow each other until input.

## Idle demo mode
After `IdleSeconds` (30 s) without keyboard, mouse, touch or gamepad input: the HUD hides, every agent runs on its
trained policy (inference only) and the showcase cameras cycle every `CameraDwellSeconds` (7 s): Broadcast, Follow, Orbit (ARaceDirector camera modes). Any input
returns control and restores the HUD, mode and camera. A small "Demo - press any key" hint stays at the bottom.

## Editor-first config
- `URaceShowcaseConfig` (DataAsset): idle threshold, camera list, dwell time, overlay key, latency window, touch button.
- `URaceRewardConfig` (DataAsset): penalty weights `TorqueSqWeight`, `JointAngVelSqWeight`, `ActionRateSqWeight`,
  `FootSlipWeight` and the curriculum stages (name, threshold, metric).
- Pick the assets in Project Settings > Game > Race Showcase; empty = the C++ defaults.
- The defaults mirror `training/reward_config.json`, which the Python trainer reads; a pytest (`test_unreal_reward_mirror.py`) fails when the
  two differ. Change both together.

Shipped brains (training/final, Content/Brains) predate `torque_sq` / `joint_ang_vel_sq` and the humans' action-rate / foot-slip weights: they were NOT retrained. Changing a weight only affects future training runs.

## Unattended check
`UnrealEditor.exe <uproject> -game -windowed -ResX=1600 -ResY=900 -ShowcaseCapture=<dir> -ShowcaseTouch` writes
`overlay_on.png`, `overlay_off.png`, `demo_a.png`, `demo_b.png` into `<dir>` (demo shots after 35 s and one dwell later),
then quits. `-ShowcaseIdle=<s>` overrides the idle threshold.
