# PoRaceUnreal — Todo

Mark `[x]` when done. One task = one commit. Details and pass conditions: `tasks/plan.md`.

Plan approved 2026-11-10.

## Slice 0 — Salvage and repo
- [x] 0.1 `git init` on `master`; `.gitignore` (Unreal + Python), `.gitattributes` (LFS), `.editorconfig`
- [x] 0.2 Copy `training/` (all), `tools/blender`, `tools/prune.py`, `tools/android`
- [x] 0.3 Copy brains (`Assets/Policies`, `training/final`) to `training/models/brains`
- [x] 0.4 Copy art (`Assets/Art/Raw`, `Assets/Art/Exports/GLB`, `GrandmaRiggedUnity.*`) to `Content/Art/`
- [x] 0.5 Copy `docs/`, `rl_optimization_log.md`, `tasks.md`, `SCREENSHOTS/`, `privacy-policy.html`
- [x] 0.6 Copy Unity C# (`Assets/Scripts`, `Assets/Editor`, `Assets/Tests`) and flattened MJCF to `reference/unity/`
- [x] 0.7 Convert `Maps/*.asset` and `Creatures/*.asset` to `training/tracks/*.json` and `training/characters/*.json`
- [x] 0.8 (skipped, owner's call) Unity baseline run
- [x] 0.9 `tools/salvage_check.py`: hashes, ONNX shapes, MJCF compile, `check_model.py` for each creature
- [x] 0.10 First commit; salvage check 48/48 → owner may delete `PoRace/`

## Slice 1 — Physics parity for Blue
- [ ] 1.1 Create `PoRaceUnreal.uproject` (UE 5.8, C++ module, plugins as PoSlapUnreal)
- [ ] 1.0 Trainer to MuJoCo 4.0.0; re-run Blue's ladder rungs in Python; retrain any brain that fails
- [ ] 1.2 `Scripts/setup_urlab.ps1`: clone URLab, apply `urlab_porace.patch`, MuJoCo 4.0.0, build third party
- [ ] 1.3 `training/contract.py` + generator for `RaceContract.gen.h`
- [ ] 1.4 Import Go2 into a testbed level by script; marker check
- [ ] 1.5 Model readback against the source model
- [ ] 1.6 `URacerController` + `Go2Brain` + `URaceBrainIO` (hold home pose, then ONNX)
- [ ] 1.7 Zero-brain hold gate
- [ ] 1.8 Replay gate (`-Replay`)
- [ ] 1.9 Closed-loop gate
- [ ] 1.10 No-Chaos assert; `Scripts/verify_all.ps1 -Only parity`

## Slice 2 — One race, one racer
- [ ] 2.1 `training/build_track_model.py` (centre line → rails) and `Scripts/build_track.py`
- [ ] 2.2 `training/race.py` reference: countdown, steering, splits, finish
- [ ] 2.3 `URaceOrchestrator` (same rules), `UTrackDefinition`
- [ ] 2.4 Get-up switch, `URaceAutoReset`
- [ ] 2.5 `-RaceTest` result line, `Scripts/regress.ps1`
- [ ] 2.6 Build stamp on the HUD

## Slice 3 — Matt and mixed fields
- [ ] 3.1 Matt MJCF import, `HumanBrain`, parity gates
- [ ] 3.2 `ARacerVisual` skinned mesh following physics
- [ ] 3.3 Combined model (track + every ready racer), parking of unpicked racers
- [ ] 3.4 Flat Oval; laps; seeded lane draw and speed spread
- [ ] 3.5 `UCreatureDefinition` + registry

## Slice 4 — Game loop
- [ ] 4.1 `ARaceHUD` corners and standings
- [ ] 4.2 Menu: track, roster, laps, eligibility
- [ ] 4.3 Intro, countdown, results card, pause sheet
- [ ] 4.4 Follow camera
- [ ] 4.5 `-RaceUiTest`, `-Shots`, `-AutoOk`; UI report

## Slice 5 — Race rules complete
- [ ] 5.1 Tactics (pass, block, lateral cap) in reference and Unreal
- [ ] 5.2 Yellow flag
- [ ] 5.3 Finish window and DNF classification
- [ ] 5.4 Handicap, unstick
- [ ] 5.5 `UContactAudit`, `-ContactGate`

## Slice 6 — All four tracks
- [ ] 6.1 Banked surface geoms and visuals
- [ ] 6.2 Steeplechase obstacles and visuals
- [ ] 6.3 Per-track brain selection; parity for bank and steeple brains
- [ ] 6.4 Regression on maps 2 and 3

## Slice 7 — Broadcast: cameras and signals
- [ ] 7.1 `URaceSensors`, `UContactImpulse`, `UStrainMonitor`
- [ ] 7.2 `URaceDirector` and manual camera
- [ ] 7.3 Wobble warning, recovery countdown
- [ ] 7.4 `UGateTiming`
- [ ] 7.5 Intent markers, `UPipCam`, `UCommentary`
- [ ] 7.6 Telemetry corner

## Slice 8 — Desktop presentation
- [ ] 8.1 Lumen, Nanite, virtual shadow maps; track and trackside materials
- [ ] 8.2 Niagara effects and scuff decals
- [ ] 8.3 MetaSounds: footsteps, motors, modal impacts, crowd
- [ ] 8.4 Colour grade, strain glow
- [ ] 8.5 Quality governor; `-FrameProbe`; report

## Slice 9 — Replay, ghost and records
- [ ] 9.1 `URaceReplay`
- [ ] 9.2 Ghost
- [ ] 9.3 `URaceTelemetry`, stats card
- [ ] 9.4 Persistent records; no writes under `-RaceTest`

## Slice 10 — Modes
- [ ] 10.1 `UTournament`
- [ ] 10.2 `USeasonMode`
- [ ] 10.3 `UAgentElo`
- [ ] 10.4 Attract mode and self-running loop; soak

## Slice 11 — Weather
- [ ] 11.1 `UTrackWeather` fetch and offline flag
- [ ] 11.2 Friction scaling, wind through `URaceExternalForces`
- [ ] 11.3 Rain visuals, conditions chip

## Slice 12 — Android
- [ ] 12.1 `export_cpu_brains.py`, Basic CPU path, `-RaceBasicCpu`
- [ ] 12.2 Mobile renderer, device profile, mobile levels
- [ ] 12.3 Portrait HUD pass, haptics
- [ ] 12.4 Device test

## Slice 13 — Browser
- [ ] 13.1 `Web/` loader and sim with `contract.gen.js`
- [ ] 13.2 Race view, HUD, menu, results
- [ ] 13.3 `Web/check.mjs`
- [ ] 13.4 Deploy workflow

## Slice 14 — Growth recipes and close-out
- [ ] 14.1 Racer and track onboarding docs and script
- [ ] 14.2 Full regression grid, CI workflows
- [ ] 14.3 `CLAUDE.md`, `AGENTS.md`
- [ ] 14.4 Remove `reference/unity/`
