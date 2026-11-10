# CLAUDE.md

@AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# PoRace agent directives (Unity)

Read `docs/` and `tasks.md` before starting a task. `AGENTS.md` holds the same rules for other agents; keep the two in sync.

## Commands
- Editor automation (Git Bash, editor open): `source tools/ed.sh`, then `recompile`, `ueval 'C#;'`, `ulog <substr>`, `ubuild Build/X/PoRace.exe '["Assets/Scenes/A.unity"]'`.
- Player build, editor closed: `Unity.exe -batchmode -quit -projectPath . -executeMethod BuildCli.Windows [-buildPath Build/PoRace/PoRace.exe] [-scenes A.unity,B.unity]` (the first scene is the start scene). Unity 6000.6.0f1.
- Headless race test: `Build/PoRace/PoRace.exe -batchmode -nographics -raceTest -menuMap 0 [-timeScale 4] [-seed 7] [-matt] [-grandma] [-laps 2] [-noTactics] [-yellowFlag] [-contactGate]`. Whole grid in parallel, optionally against a baseline player: `tools/regress.sh Build/PoRace/PoRace.exe [Build/Baseline/PoRace.exe]`. Other probes: `-replay <json>` (parity), `-parityDir <dir>`, `-shots <dir>`, `-frameProbe 20`, `-gfx mobile|pc`. Game flow: a plain launch opens the menu; `-autoplay` runs race after race; `-noIntro` skips the racer intro; `-autoOk <s>` presses OK on the results card (with `-menuMap` it loops menu → race); menu idle 30 s starts arcade demo races (`-attractAfter <s>`, `-noAttract`); `-tournamentAuto` plays the 16-slot tournament unattended (with `-autoOk`).
- Editor tests: `Assets/Tests/Editor` (`NoPhysXTest`); run them with Unity's `-runTests -testPlatform EditMode -testFilter <Name>`.
- Trainer (Docker image `porace-trainer`): `docker run --rm --init --log-driver none --gpus all -v <repo>\training:/work porace-trainer python train.py --env joystick --logdir runs/<name>`. Use `--init --log-driver none`, because without them the container became an unkillable zombie. Humans: `bash matt/launch.sh <run>` / `bash grandma/launch.sh <run>` (each its own recipe and brain). `train.py` runs `preflight.py` first: it writes `tags.json` (physics, interface, creature) and refuses a cross-creature restore.
- Unity while the GPU trains: use `-batchmode -nographics` (compile, builders, player builds and race tests all work); only `-shots` captures need the GPU.
- Purge: `python tools/prune.py [--apply]` (dry run by default; keeps runs written in the last 24 h or referenced in the log).
- Gate a run (export ONNX, eval, reference, Unity replay): `training/gate.sh runs/<name>`. Variants: `gate100.sh`, `gatespeed.sh`, `gateall.sh`. Humans: `python matt/sim.py ladder|graduate|record --params runs/<run>/params.pkl [--creature grandma]` (CPU), ladder probe `training/matt/probe_ckpts.py`.
- Human body pipeline: `blender -b --factory-startup -P tools/blender/grandma_rig.py` (AccuRig FBX -> 22-bone rig), `blender -b Assets/Art/Raw/<name>.blend -P tools/blender/matt_mjcf.py -- --creature <name>`, then in the trainer `python matt/check_model.py --creature <name> --fix-keys` and `python matt/model_info.py --creature <name>` (with `-v <repo>\docs:/docs -v <repo>\Assets:/assets`).

## Codebase map
- `Assets/Scripts/Core/`: runtime. `Go2Controller` / `MattController` (any human: `human` picks `HumanSpec.Matt` or `.Grandma`; Grandma's MuJoCo names carry `gm_`) / `G1Controller` (obs build, 50 Hz policy on `MjScene.ctrlCallback`), `PolicyRunner` (ONNX), `MultiRaceOrchestrator` (one dog, Blue, plus Matt and Grandma on flat maps, in one MuJoCo model; tactics, yellow flag), `MapDefinition` + `CreatureDefinition` registries (`Assets/Resources/{Maps,Creatures}`; the creature card holds personality traits). `Probes/`: test harnesses (ShotProbe, FrameProbe, ReplayHarness, ParityRecorder, ModelCheck, UiSelfTest). `Broadcast/`: spectator layer (director cams, strain, wobble, hazards/chat, weather, replay, telemetry, audio incl. `ModalImpact`, VFX, `QualityGovernor`, `ContactAudit`); `Broadcast/UI/` incl. `HudCorners`.
- `Assets/Editor/`: CLI builders (`TrackBuilder`, `BroadcastBuilder`, `CreatureBuilder`, `MenuBuilder`, `BuildCli`, `WebGLBuild`). Scenes are composed by these, not by hand.
- `Assets/MuJoCo/`: Unity-flattened MJCF (`training/flatten_for_unity.py`). `Assets/Policies/`: shipped ONNX.
- `training/`: Docker trainer (`train.py --env ...`, `eval.py --rung ...`, `export_onnx.py`, `preflight.py`), Go2 envs in `go2/`, Matt in `matt/` (also the shared human tools: sim, check_model, model_info), Grandma in `grandma/` (env = Matt's on her body + her character card), G1 in `g1/`. Runs land in `training/runs/` (gitignored). History and decisions: `rl_optimization_log.md`.
- Gates: replay parity < 1e-4 (`ReplayHarness`), `NoPhysXTest`, headless race tests (`PoRace.exe -batchmode -nographics -raceTest`).
- Proposals backlog: `docs/proposals_*.md`.

## Workflow
- Work on `master`. Stage and commit pending work before any git pull/sync.
- Build watermark: show an automated `YYMMDD` build-date watermark in the bottom-right of the HUD.
- Keep Unity's **Run In Background** enabled. Drive headless runs and automation through the Unity CLI (`tools/ed.sh`, `-batchmode` player builds).
- Build scenes, prefabs and hierarchies with CLI automation and headless Blender (or Blender MCP).
- Blender source files go in `Assets/Art/Raw/`. Runtime GLB/FBX exports go in `Assets/Art/Exports/GLB/`.
- For UI changes, export an HTML change report with annotated before/after captures to `SCREENSHOTS/`.

## Physics & realism
- Train in MuJoCo (Docker trainer in `training/`). Unity never simulates with PhysX: use `org.mujoco` (`mjModel`/`mjData`) plus ONNX inference (Unity Inference Engine / Sentis).
- Primitive colliders only (capsule/sphere/box), never visual meshes. Non-adjacent parts collide with each other. Zero penetration at rest, at joint limits and through motion.
- Gravity −9.81 m/s², anatomical mass, realistic joint, torque and speed limits. Skeleton joints, joint frames and bone orientations match between the 3D files and the MJCF.
- Rewards carry action-rate/jerk penalties (or low-pass filtering): fluid motion, no jitter.

## Policy architecture & retraining
- A few small policies, one per motor skill family (locomotion, balance/get-up, task skills). Cover variants with command inputs (velocity, gait, target, style), not new policies.
- Layered rule-based directors (game flow → body → skill) switch policies on physical state (contacts, centre of mass, falls) through one transition table, mirrored in every runtime (Python env and Unity controllers). Policies never pick each other.
- Hand-overs: all policies of a body share observation layout, joint order, action map, timing and motion-style reward. Preload every policy. Pass on the last action; never snap poses or blend outputs. Train each policy on the states it inherits (get-up from real falls).
- Frozen interface: append inputs only at the end, with zero-initialised weights; never reorder or remove them. If the interface must break, distil the old policy into the new layout.
- One brain per character: every new character gets its own training run and policies, even when bodies are similar. Personality comes from the character card's traits and its own style reward weights, learned in training; directors don't script it.
- Each character trains from scratch, passes every ladder level and the gate, and trains against the existing roster. Once trained, avoid retraining it fully.
- Before any change: list the policies it touches (body physics → that body's; rules → the policies acting under them; new skill → its policy plus director rows; visuals → none) and log it in `docs/`. Afterwards re-run every policy's regression scenarios (task + realism). Tag each checkpoint with its interface and physics versions.

## Training, gates & reports
- Close the Unity editor for runs over 30 min or when free RAM drops below 4 GB. Save and commit first.
- Delete failed runs, short tests (< 5,000 steps) and unneeded checkpoints. Never delete a run written to in the last 24 h or one a queue will resume.
- Export ONNX only after graduation: target score held for 100 straight episodes, zero NaN gradients.
- Run TensorBoard with every run. Log metrics and progress to `docs/<YYYYMMDD>/` so later agents can pick up where a run left off.
- Runs over 30 min get an HTML report with metric charts and run-over-run deltas. Estimate training time at startup. Send hourly updates (status grid, key improvements, short summary).

## Output
- After changes over 100 lines, propose 3 optional high-level questions (product direction, architecture, roadmap).
- End any reply over 100 words with a ~20-word TL;DR.
- End with a proposed fix for the app's main open issue and ask before acting on it.
