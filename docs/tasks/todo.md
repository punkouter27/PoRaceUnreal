# PoRaceUnreal — Todo

Mark `[x]` when done. One task = one commit. Details and pass conditions: `docs/tasks/plan.md`.

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
- [x] 1.0 MuJoCo 4.0.0: all six Go2 brains pass their rungs on it in Python (`training/version_check.py`); no retraining needed
- [x] 1.1 `PoRaceUnreal.uproject` (UE 5.8, C++ module `PoRaceUnreal`, URLab + NNE ORT + Basic CPU)
- [x] 1.2 `scripts/setup_urlab.ps1` + `Plugins/urlab_porace.patch` (PoSlap's 8 patches + MuJoCo 4.0.0 pin + MuJoCo 4 API fixes)
- [x] 1.3 `training/contract.py` → `training/models/go2_fingerprint.json` + `Source/PoRaceUnreal/RaceContract.gen.h`
- [x] 1.4 Go2 imported into `/Game/Project/Environments/Levels/L_Testbed` by `scripts/build_testbed.py`
- [ ] 1.4b Coordinate marker check (MuJoCo → Unreal cm, Y mirrored): moved to Slice 2, where the visuals are first drawn
- [x] 1.5 Model readback: 140 physics arrays, 0 differ (after URacerController writes the training numbers back; see `docs/20261110/slice1.md`)
- [x] 1.6 `URacerController` (observation, brain via NNE ORT, action map; replay and recording)
- [x] 1.7 Hold gate: 0 difference over 2 s
- [x] 1.8 Replay gate: 0 difference over 5 s
- [x] 1.9 Closed-loop gate: 0.000 cm after 5 s; brain output identical to onnxruntime
- [x] 1.10 `scripts/verify_all.ps1 [-Unreal | -Only parity]`
- [ ] 1.10b Runtime no-Chaos assert (the testbed script turns Chaos off; nothing checks it at run time yet): moved to Slice 2

## Slice 2 — One race, one racer
- [x] 2.0 (from 1.4b, 1.10b) Coordinate marker check and run-time no-Chaos check, every race test (`ARaceDirector`)
- [x] 2.1 `training/build_track_model.py` (centre line → rails, racers attached with a name prefix) and `scripts/build_track.py` (`/Game/Project/Environments/Levels/L_PlanarSprint`)
- [x] 2.2 `training/race.py` + `training/racelib/` reference: countdown, steering, checkpoints, un-stick, off-track, finish. Split times moved to 7.4 (gate timing)
- [x] 2.3 `FRaceRules` + `FRaceTrack` in Unreal, run by `URacerController` on the physics thread (one controller per track model: URLab calls one per articulation)
- [x] 2.4 Get-up switch and auto-reset (`FGo2Racer`); flip test passes in both runtimes
- [x] 2.5 `-RaceTest` result line, `scripts/regress.ps1`: seeds 1–5 identical to Python on the same model, within 0.66 % of the track file
- [x] 2.6 HUD: track, standings, race time, countdown, fps / physics Hz, build stamp `v0.1.0 YYMMDD`
- [x] 2.7 The race waits for the first drawn frame (a slow first frame used to swallow the countdown)

## Slice 3 — Matt and mixed fields
- [x] 3.1 Matt: fingerprint, `racelib/human.py` + `FHumanRacer`; brain verified on MuJoCo 4.0.0 (`human_check.py`); races identical to Python in Unreal
- [x] 3.2 `ARacerVisual`: Matt's skinned scan posed from his bodies; his capsules hidden
- [x] 3.3 Track model with every eligible racer; `-Racers=` / `--racers` picks the grid, the rest parked and hidden; race impratio = the grid's lowest
- [x] 3.4 Flat Oval (`L_FlatOval`), laps, seeded lanes and speeds: 2-lap races identical to Python
- [ ] 3.5 Creature registry in Unreal: moved to 4.2 (the menu's roster needs it; races read the JSON cards)

## Slice 4 — Game loop
- [x] 4.1 `ARaceHUD`: corners (track/lap/standings TL, rates TC, pause TR, stamp BR), Canvas text + Slate buttons
- [x] 4.2 Menu (`L_Menu`): tracks, roster with ready / not ready / not eligible and why, laps, START rules; `RaceRegistry` from the JSON (from 3.5)
- [x] 4.3 Racer intro (fixed length, in the rules), countdown, results card, pause sheet; finish window and race limit (Python + C++)
- [x] 4.4 Chase camera, intro close-ups; fills any screen shape, keeps the vertical field of view
- [x] 4.5 `-RaceUiTest` (registry, eligibility, START, layout at 16:9 / portrait / 21:9), `-RaceShots`, `-AutoStart` / `-AutoOk` / `-AutoLoops` (10/10); `SCREENSHOTS/slice4_ui_report.html`
- [ ] 4.6 Memory over many races: +315 MB in 10 short races, unclear if a leak: decide in the Slice 10 soak

## Slice 5 — Race rules complete
- [x] 5.1 Tactics (pass, avoid, block, lateral step 0.25 m/s, banks no-manoeuvre) in reference and Unreal; overtakes counted with 0.25 m hysteresis; a pass holds until 1 m clear (new: Unity's cut back across the slower racer); "slower" at the pace a racer holds
- [x] 5.2 Yellow flag (2+ down on a 3+ grid, 80 % pace, ≤ 5 s, 15 s cooldown): self test in both runtimes; cannot fire in a real race until a third racer is ready
- [x] 5.3 Finish window and DNF classification (done in Slice 4)
- [x] 5.4 Handicap (`-Handicap`, menu toggle, `?Handicap=1`) from cruise × card `pace`; unstick unchanged; fixed: after a reset the progress walk restarts at the spawn's segment (an off-track reset loop on curves, also in Unity)
- [x] 5.5 Contact audit (`FContactAudit`, always on in Unreal, `--audit` in Python, identical lines), `-ContactGate` exit 4; bump count in the result line; `footGeoms` on the cards

## Added: the Stroller (owner's request, 2026-11-10)
- [x] S.1 Body from the scan's rig (`training/stroller/make_model.py`), card, fingerprint
- [x] S.2 Rolling brain trained (`train.py --env stroller`, run s1): ladder 100/100 on MuJoCo 4.0.0
- [x] S.3 `racelib/stroller.py` + `FStrollerRacer`; `ARacerVisualStroller` (scan rides the chassis, wheels turn)
- [x] S.4 Width-aware tactics and the alongside rule (both runtimes); three-racer races identical in Unreal
- [x] S.5 Report `docs/20261110/stroller.md`

## Slice 6 — All four tracks
- [ ] 6.1 Banked surface geoms and visuals
- [ ] 6.2 Steeplechase obstacles and visuals
- [ ] 6.3 Per-track brain selection; parity for bank and steeple brains
- [ ] 6.4 Regression on maps 2 and 3

## Slice 7 — Broadcast: cameras and signals
- [ ] 7.1 `URaceSensors`, `UContactImpulse`, `UStrainMonitor`
- [ ] 7.2 `URaceDirector` and manual camera
- [ ] 7.3 Wobble warning, recovery countdown
- [ ] 7.4 `UGateTiming` (also the split times from 2.2)
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
- [x] 14.4 Remove `reference/unity/` (2026-11-20; still in git history)
