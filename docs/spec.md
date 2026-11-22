# PoRaceUnreal — Technical Specification

Status: draft for approval, 2026-11-10. Product requirements: `docs/PRD.md`. Build order: `docs/tasks/plan.md`.
Pattern reference: `../PoSlapUnreal` (same engine, plugin and three-runtime layout).

One rule above all: **MuJoCo moves the racers; Unreal only draws them.** Chaos never simulates a racer, rail, obstacle or floor.

## 1. Technical assumptions

| Area | Decision | Basis |
|---|---|---|
| Engine | Unreal Engine 5.8, C++ module `PoRaceUnreal` | Installed at `C:\Program Files\Epic Games\UE_5.8`; PoSlapUnreal uses it |
| Physics | MuJoCo through the URLab plugin (`Plugins/UnrealRoboticsLab`, cloned and patched, not tracked) | PoSlapUnreal pattern; patch kept as `Plugins/urlab_porace.patch` |
| MuJoCo version | **4.0.0** in the trainer, URLab, Android and web (`mujoco`, `mujoco-warp` 4.0.0; needs Python 3.11+) | Owner's call 2026-11-10. Brains were trained on 3.15.0: each is re-gated on 4.0.0 and retrained only if it fails. All salvaged models compile on 4.0.0 |
| Brains | ONNX. Windows: NNE ONNX Runtime. Android: NNE Basic CPU with weights exported to `.bin` | PoSlapUnreal: UE 5.8 has no ONNX runtime on Android |
| Trainer | PoRace's Docker trainer moved as is (`mujoco_playground` on MuJoCo Warp, Brax PPO) | Graduated brains and gates depend on it |
| Reference runtime | Python CPU MuJoCo race (`training/race.py`), new, ported from `MultiRaceOrchestrator` | Makes the rules testable without Unreal and gives the browser a second implementation to check against |
| Browser | Separate lightweight app in `Web/`: MuJoCo WASM + onnxruntime-web + three.js | PoSlapUnreal pattern; Unreal does not target the browser |
| Rendering | Windows: Lumen, Nanite, virtual shadow maps, Niagara. Android: mobile renderer, baked or simple lighting, device profiles | PRD H1, H2 |
| UI | C++ HUD (Canvas) following `SlapHUD*`, portrait first | PoSlapUnreal pattern; scriptable and testable from the command line |
| Scene authoring | Python editor scripts in `scripts/`, run with `UnrealEditor-Cmd -run=pythonscript`. No hand-built levels | AGENTS.md automation rule |
| Platforms | Win64, Android arm64 (min SDK 28), browser | PRD |
| Repo | New git repo, `master`, Git LFS for binaries, same `.gitattributes` and `.editorconfig` as other Po repos | Po conventions |

**Open risks**

1. **MuJoCo 4.0.0.** A major version step on three fronts. (a) PoSlap's URLab is pinned to 3.10.0 and must build against 4.0.0; API changes may need plugin patches. (b) The trainer moves from `playground` 0.2.0 to the release that pairs with MuJoCo 4 (1.0.1), which may change the env and PPO APIs. (c) Brains trained on 3.15.0 may behave differently; Slice 1 re-runs each brain's ladder in Python on 4.0.0 first, and a brain that fails is retrained (owner approved retraining).
2. **URLab rebuilds the model.** PoSlapUnreal found that URLab's rebuilt model differs from the source XML by float residues. The parity check therefore steps URLab's compiled `.mjb`, not the XML.
3. **Mixed step settings.** Blue uses `impratio 100, iterations 1`; Matt's model sets its own options. One MuJoCo model has one option block. The Unity version already ran them together, so the combined option values are copied from it and recorded in `training/contract.py`.
4. **Roster selection.** URLab imports a model at edit time, so racers cannot be added at run time. Each track level contains every ready racer; unpicked racers are parked off track with contacts off and their brain idle, as the Unity version did.
5. **Mesh geoms on banked and obstacle tracks.** Banked Oval uses 324 convex mesh pieces. URLab's import of these needs checking in Slice 6.

## 2. Architecture

```
PoRaceUnreal/
  PoRaceUnreal.uproject
  Source/PoRaceUnreal/        C++ game module
  Plugins/                    UnrealRoboticsLab (cloned) + urlab_porace.patch
  Content/
    Art/Raw/                  .blend sources
    Art/Exports/              FBX / GLB / textures
    Project/                  every Unreal asset (/Game/Project): Agents/Racers, Environments/{Levels,Tracks,MuJoCoImports},
                              RL_Policies/Brains, DataAssets (reward + showcase config)
    Data/                     staged as non-UFS files in packaged builds
  Config/
  scripts/                    Unreal editor Python: build_track.py, set_brain.py, setup_urlab.ps1, verify_all.ps1
  training/                   Docker trainer, envs, gates, race.py (reference), models/, final/
  tools/blender/              rig and prop scripts
  tests/                      pytest suite (contract, rng, models + brains, rules self-test, reference race, rewards)
  web/                        static showcase site + /diag (web/build.py), deployed to swa-poraceunreal
  docs/                       PRD, this spec, parity references, ladders, dated session logs
  docs/tasks/                 plan.md, todo.md
```

### 2.1 Three runtimes, one contract

| Runtime | Where | Role |
|---|---|---|
| Python CPU MuJoCo | `training/race.py` | **Reference.** Race rules, director inputs, state machine. Writes race logs |
| Unreal (URLab + NNE) | `Source/PoRaceUnreal/` | The game on Windows and Android |
| Browser (MuJoCo WASM) | `Web/` | Spectator site |

Constants shared by all three (step, decimation, observation layouts, joint order, tactic limits, reset timers) live in `training/contract.py`. A script generates `Source/PoRaceUnreal/RaceContract.gen.h` and `Web/contract.gen.js` from it, and `verify_all.ps1` fails if the generated files are stale. This replaces the hand-duplicated constants that PoSlapUnreal carries.

### 2.2 Physics contract (carried from PoRace, frozen)

| Item | Blue (Go2) | Matt | Grandma |
|---|---|---|---|
| Physics step | 4 ms (250 Hz) | 4 ms | 4 ms |
| Brain rate | 50 Hz (every 5th step) | 50 Hz | 50 Hz |
| Actuators | 12 | 29 | 29 |
| Observation | 48 (42 for get-up) | 103 | 103 |
| Name prefix | none | `matt_` | `gm_` |
| Brains | loco, fast, bank, steeple, getup | loco (m20) | g14 (graduation run 94/100; not yet verified in a game) |

Blue: PD gain 35, force range ±24, joint damping 0.5, Euler integrator, pyramidal cone. Coordinates: MuJoCo metres, right-handed, Z up → Unreal centimetres, left-handed (`x·100, −y·100, z·100`), converted by URLab and verified with three markers in Slice 1.

### 2.3 Unreal module layout

| Unit | Responsibility | Ported from (Unity) |
|---|---|---|
| `RaceContract.gen.h` | Generated constants | `Go2Model`, `MattSpec`, `HumanSpec` |
| `URacerController` (URLab `MjArticulationController`) + `Go2Brain`, `HumanBrain` | Build observations, run the brain every 5th step, write controls, switch loco ↔ get-up | `Go2Controller`, `MattController`, `PolicyRunner` |
| `URaceBrainIO` | NNE ORT on Windows, Basic CPU on Android | PoSlap `SlapBrainIO` |
| `URaceOrchestrator` | Countdown, steering along the centre line, laps, splits, tactics, yellow flag, finish window, seed | `MultiRaceOrchestrator` |
| `URaceAutoReset`, `URaceExternalForces` | Reset rules; single writer of wind forces | `AutoReset`, `ExternalForces` |
| `UTrackDefinition`, `UCreatureDefinition` (data assets) + registries | Tracks and racers as data | `MapDefinition`, `CreatureDefinition` |
| `ARacerVisual` | Copy MuJoCo body poses to skeleton bones or rigid parts | `MattSkin`, PoSlap `SlapAthleteVisual` |
| `URaceSensors`, `UContactImpulse`, `UStrainMonitor`, `UContactAudit` | Read-only signals from `mjData` | same names |
| `URaceDirector`, `UPipCam`, `URaceReplay` | Cameras, replay, ghost | same names |
| `ARaceHUD` (+ `Menu`, `Standings`, `Results`, `Tourney`, `Panels`) | All UI, build stamp | `Hud`, `MenuController`, `Broadcast/UI/*` |
| `URaceAudio`, `URaceFx` | MetaSounds and Niagara driven by contact impulses | `RaceAudio`, `ModalImpact`, `ImpactFx` |
| `UTournament`, `USeasonMode`, `UAgentElo`, `URaceTelemetry`, `UGateTiming`, `URecoveryRace`, `UTrackWeather`, `UCommentary` | Game modes and records | same names |
| `URaceTests` | Command-line probes | `Probes/*` |

Dropped from the port: `ChatLink`, `HazardDesk`, `NudgeVote`, `CubePool`, `Shove` (audience interference; PRD out of scope).

### 2.4 Command-line switches (parity with the Unity build)

`-RaceTest -Map=<n> -Seed=<n> -Laps=<n> -Racers=<mask> -TimeScale=<n> -NoTactics -YellowFlag -ContactGate`, `-Replay=<json>`, `-ParityDir=<dir>`, `-Shots=<dir>`, `-FrameProbe=<s>`, `-Gfx=mobile|pc`, `-Autoplay`, `-NoIntro`, `-AutoOk=<s>`, `-AttractAfter=<s>`, `-NoAttract`, `-TournamentAuto`, `-Weather="rain=2,wind=7,dir=270"`, `-NoWeather`, `-RaceBasicCpu`.

A race test prints one result line per race in the Unity format (`FINISHED|DNF map=… seed=… | name time lane v resets unstuck`) so old and new results can be diffed.

## 3. Data model

**Creature card** (`training/characters/<name>.json`, imported to `UCreatureDefinition`): id, display name, kind (dog / human / robot), height, mass, colour, name prefix, actuator count, observation size, brains by skill, cruise speed range, max yaw rate, eligible track kinds, ready flag, traits, sound bank.

**Track definition** (`training/tracks/<name>.json`, imported to `UTrackDefinition`): id, display name, centre-line polyline (metres, MuJoCo frame), closed flag, width, bank profile, obstacles, lap range, eligible kinds, grid slots, checkpoint spacing.

**Saved state** (`Saved/PoRace/`): `elo.json`, `season.json`, `tournament.json`, `splits_<track>_L<laps>.json`, `getup_records.json`, `ghost_<track>.bin`, race logs `Logs/Race/<YYMMDD>/*.jsonl`. Never written under `-RaceTest`.

## 4. Pipelines

**Body:** Blender source → `tools/blender/*` → MJCF in `training/models/<name>/` → `training/check_model.py` gate → `training/build_track_model.py` composes track + every ready racer into one MJCF → `scripts/build_track.py` imports it through URLab into `/Game/Project/Environments/Levels/L_<Track>`.

**Brain:** `training/train.py` → ladder → graduation (100 straight trials) → `export_onnx.py` → `training/models/brains/<name>_<skill>.onnx` → `export_cpu_brains.py` → `Content/Data/Brains/*.bin` → `scripts/set_brain.py`.

**Track:** track JSON → `build_track_model.py` (rails, obstacles, bank as MuJoCo geoms) → `scripts/build_track.py` (level, visual meshes, lighting, trackside props).

## 5. Verification

| Gate | Pass condition | Tool |
|---|---|---|
| Model readback | Compiled `.mjb` matches the source model field by field | `training/compare_models.py` |
| Zero-brain hold | 2 s home pose, max joint difference < 1e-6 | `-ParityDir`, `training/zero_brain.py` |
| Replay | Recorded actions: every body within 1 mm at every step; brain output difference < 1e-4 | `-Replay`, `training/replay_check.py` |
| Closed loop | 5 s live: base within 1 cm, same fall outcome | `training/compare_closed_loop.py` |
| Race regression | Per track, seeds 1–5: finishers, times, resets against the Python reference race and the Unity times logged in `docs/unity_tasks.md` | `scripts/regress.ps1` |
| No Chaos | No racer, rail or obstacle has a simulating physics body | `-RaceTest` startup assert |
| Contact audit | Deepest penetration per contact class under limit | `-ContactGate` |
| UI | Every HUD binding resolves; no corner groups overlap at 16:9 to 21:9 | `-RaceUiTest`, `-Shots` |
| Frame time | Windows ≥ 30 fps at p95; Android 60 fps on Pixel 9 Pro | `-FrameProbe` |
| Browser | One race to the finish in Node | `node Web/check.mjs` |

`scripts/verify_all.ps1` runs every gate that needs no window. CI follows the Po convention: push to `master`, self-hosted runner, no `pull_request` trigger.

## 6. What is salvaged from the Unity project

| From `PoRace/` | To `PoRaceUnreal/` | Notes |
|---|---|---|
| `training/` (all) | `training/` | Trainer, envs, gates, `final/` checkpoints and `matt_m20.onnx` |
| `Assets/Policies/*.onnx` | `training/models/brains/` | 5 Go2 brains, Matt, zero policy |
| `Assets/MuJoCo/**` | `training/models/unity_flat/` | Reference only; Unreal imports from the trainer's source MJCF |
| `Assets/Art/Raw/*` | `Content/Art/Raw/` | `.blend` sources, `Matt.glb` |
| `Assets/Art/Exports/GLB/*` | `Content/Art/Exports/` | Matt, Grandma, grandstand, barrier, hurdle, step, rubble, textures |
| `GrandmaRiggedUnity.*` (repo root) | `Content/Art/Raw/Grandma/` | AccuRig source, expression map |
| `Assets/Resources/Maps/*.asset`, `Creatures/*.asset` | `training/tracks/*.json`, `training/characters/*.json` | Converted from Unity YAML |
| `tools/blender/`, `tools/prune.py`, `tools/android/` | `tools/` | |
| `docs/` (all), `rl_optimization_log.md`, `tasks.md` | `docs/`, `docs/unity_tasks.md` | Parity references, ladders, proposals, history |
| `Assets/Scripts/**`, `Assets/Editor/**`, `Assets/Tests/**` | (was `reference/unity/`) | Read-only source for the port; removed 2026-11-20 (git history keeps it) |
| `SCREENSHOTS/` | `docs/unity_screens/` | Visual reference for UI parity |
| `privacy-policy.html`, `.editorconfig`, `.gitattributes` | repo root | |

Not taken: `Packages/`, `ProjectSettings/`, `.meta` files, Unity scenes and prefabs, materials, `Assets/Plugins/` (Unity-specific builds), `.git` history.

No Unity baseline run is recorded (owner's call 2026-11-10). Race regression compares Unreal with the Python reference race, and with the Unity times already logged in `docs/unity_tasks.md` and `docs/rl_optimization_log.md`.

Salvaged from `origin/master` at `29b2302` (2026-11-10), one commit newer than the local checkout: it adds Grandma's g14 brain (94/100 graduation run), `tools/blender/track_meshes.py` and the 8-hour training report. Check: `tools/salvage_check.py`.
