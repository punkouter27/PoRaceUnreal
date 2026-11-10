# PoRace proposals, round 3, 2026-11-09

This file has 50 options in five tracks. It follows rounds 1 and 2 (`proposals_20261027.md`, `proposals_20261027_r2.md`) and doesn't repeat them; where it picks up an earlier option that was never built, it says so. The prompt's two CLEAN lists were identical, so they are merged into one track (E).

Each entry says why it matters (**Why**), what drives it (**Hook**: telemetry, kinematics or sensing), how it plugs in (**Engine**), and which policies it touches (**Policies**, per the AGENTS.md "before any change" rule). ★ marks the ones built in this round (Phase J in `tasks.md`).

Context measured today: a fresh checkout on the RTX 2060 PC (no `Library/`, `Build/` or `training/runs/`), Unity 6000.6.0f1 URP, Docker image `porace-trainer` present, Blender 5.2 installed. Matt m20 is the shipped policy (graduated 98/100; adult jog 2.5 m/s and 10 % grade 0/10).

## A. Features (AI navigation and visual clarity)

1. ★ **Wobble warning (fall prediction).** Why: the director cuts to a fall *before* it happens, so viewers see the stumble, not the aftermath. Hook: a per-racer stability score at 50 Hz from tilt (projected-gravity z from `UpAdr`), base angular speed (gyro) and base-height drop, smoothed over 0.2 s; above a threshold for 0.1 s raises `Wobbling`. Engine: `RaceSensors` computes it, `RaceDirector` scores it like an incident (pre-roll), the chip flashes amber. Policies: none (reads state only).
2. ★ **Agent telemetry stream (BL).** Why: the BL corner tells you what the featured racer's body is doing: speed, cadence, stride, effort, state. Hook: foot touchdowns from `RaceSensors.FootStrike` give cadence (Hz) and stride (m = speed / cadence × feet per cycle); base speed from `qvel` decimated to 5 Hz; effort = mean |force| / max. Engine: one uGUI block fed by `RaceDirector.Subject`. Policies: none.
3. ★ **Yellow flag after a pile-up.** Why: when two or more racers are down, the leaders ease off for 5 s; it keeps the race close and reads like real motorsport. Hook: count of racers in `FALLEN_RECOVERING`; leaders' cruise capped at 80 % (inside every policy's trained command range), lifted when the field is up or after 5 s. Engine: `MultiRaceOrchestrator` command cap + ticker post + yellow bar on the HUD. Off in `-raceTest` unless `-yellowFlag`, so regression races stay bit-identical. Policies: none (command inside the trained envelope).
4. **Intent ribbons.** Why: you see where each racer is about to go. Hook: integrate `FilteredCommand` (vx, vy, yaw rate) forward 1.5 s from the base pose at 10 Hz. Engine: a pooled `LineRenderer` per racer, fading alpha; extends `IntentArrows`. Policies: none.
5. **Time-to-collision tactics.** Why: fewer racer-on-racer pile-ups, smarter passes. Hook: TTC between every racer pair from base positions and velocities (`qpos`, `qvel`); the attacker yields (vy toward the open lane, vx −10 %) when TTC < 0.8 s. Engine: `MultiRaceOrchestrator` tactics; `-noTactics` unchanged. Policies: none (commands only).
6. **Force-vector replays.** Why: an incident replay shows *why* he fell: the contact force arrows, centre of mass and support polygon. Hook: `mjData.contact` + `mj_contactForce` during `RaceReplay` playback; COM from `subtree_com`. Engine: `RaceReplay` + GL lines on the INCIDENT look. Policies: none.
7. **Racing-line heatmap.** Why: a post-race graphic comparing how a dog and a human take the oval. Hook: base positions at 10 Hz into a 256² grid per creature. Engine: a RenderTexture on the result card. Policies: none.
8. **Slalom map (Map 05).** Why: a navigation test without new training: visual cones, time penalty for a missed gate. Hook: yaw command within each racer's `MaxYawRate`; waypoints alternate sides. Engine: `TrackBuilder` + a new `MapDefinition`; cones visual-only. Policies: none (inside the trained yaw range; verify with `-raceTest`).
9. **Brain view (TAB).** Why: shows the agent "thinking": live policy outputs and foot contacts for the featured racer. Hook: `PolicyRunner` output vector (12 for Go2, 29 for Matt) and the foot contact flags. Engine: a bar strip in the TAB debug panel. Policies: none.
10. **Rival duel mode.** Why: Matt vs. one dog, handicapped, best of three. Hook: `-handicap` start offsets (I.1) + `SeasonMode` points. Engine: a menu preset. Policies: none.

## B. Graphics, audio and collision (PC high end, 30 FPS floor)

URP can't do HDRP's SSGI, contact shadows, ray tracing or volumetrics. The URP equivalents are: Adaptive Probe Volumes (baked multi-bounce GI), SSAO, Screen Space Lens Flare, TAA / STP upscaling, Render Graph custom passes, and VFX Graph GPU particles. Switching the PC tier to HDRP would mean two pipelines and redoing every shader (StrainRim, Decal, HeatShimmer), so it's out of scope.

1. ★ **Adaptive quality governor (30 FPS floor).** Why: the PC tier gets every effect it can afford and backs off before dropping under 30 fps. Hook: rolling p95 frame time over 2 s; above 30 ms steps down (render scale 1.0 → 0.85 → 0.7, then shadows, then post); below 20 ms for 5 s steps back up. Engine: `QualityGovernor` on the PC tier; state in the TAB panel; `FrameProbe` reports the final step. Policies: none.
2. ★ **PC "Ultra" level.** Why: maximum look on desktop: 4 shadow cascades at 4096, soft shadows high, MSAA 4×, HDR, SSAO back on with its resources referenced (the G.0 fix removed SSAO instead of shipping its shaders). Hook: none. Engine: `GfxTier` adds Ultra as the governor's top step; Mobile untouched. Policies: none.
3. **Adaptive Probe Volumes per track.** Why: baked multi-bounce GI and reflection probes; the static tracks are a perfect fit. Engine: CLI bake in `TrackBuilder`. Policies: none.
4. **GPU impact bursts (VFX Graph, PC).** Why: dense sparks and dust (10k particles) on hard hits. Hook: `ContactImpulse` J, surface. Engine: VFX Graph (compute, URP); Mobile keeps `ImpactFx`. Policies: none.
5. **Volumetric light shafts.** Why: the subject spotlight and rain read as volume. Engine: a Render Graph full-screen raymarch pass, 1/4 resolution, PC only. Policies: none.
6. **Skin and micro-detail shader.** Why: Matt reads as a person: wrap lighting + transmission (a URP SSS approximation) from a thickness map baked in Blender; triplanar detail normals on robots and track. Engine: Shader Graph. Policies: none.
7. ★ **Modal impact synthesis.** Why: impacts sound like the material that was hit, scaled by the energy of the collision, not one sample per class. Hook: `ContactImpulse` J and surface; each material has a set of damped modes (frequency, decay, gain); energy = J² / (2 m_red) sets amplitude and brightness. Engine: `ModalImpact` voices on `OnAudioFilterRead`, pooled, tier-capped. Policies: none.
8. **HRTF binaural + geometric reverb (carried from r1 B6, not built).** Why: you hear who is behind you. Engine: Steam Audio (free, Windows/Android); reverb from the rail and grandstand geometry; WebGL falls back to the built-in panner. Policies: none.
9. ★ **Penetration and momentum audit in `-raceTest`.** Why: proves "no clipping" with numbers on every race. Hook: per physics step, the deepest contact (`mjData.contact.dist < 0`) by pair class (foot-floor, body-floor, robot-robot, self) and, for robot-robot impacts, the momentum exchanged vs. the reduced-mass prediction. Engine: `ContactAudit` logs a summary line; `-contactGate` makes `-raceTest` fail above the limit for 0.1 s. *Built. First measurement: feet peak 2.5–2.7 cm, over 1 cm for 0.14–0.18 s on the unchanged contract (dogs and Matt), so the gate is opt-in until the contract changes.* MuJoCo, not PhysX, so "CCD" here means `ccd_iterations` and soft-contact margins, already owned by the model. Policies: none.
10. ★ **Blender batch export.** Why: every `.blend` in `Assets/Art/Raw/` becomes a runtime GLB with LODs in `Assets/Art/Exports/GLB/` by one command (the folder is empty today). Engine: `tools/blender/batch_export.py` (`blender --background --python`): per mesh, LOD1 50 % / LOD2 20 % decimate, triangulate, apply transforms, export GLB with `_LOD0/1/2` nodes. Policies: none. *Built and run: 4 GLBs. Unity has no glTF importer in the manifest (glTFast), so they don't import as models yet.*

## C. UI (portrait 16:9 to 21:9, zero scroll)

What the race HUD shows today (SCREENSHOTS/i_after, matt_after): TL "PoRace Go2" on every map; TC a debug line (ctrl step, inference ms, raw command) that's always on; TR "Locomotion / RACING", Flip, Menu and Pause, not aligned; BL Restart; a weather line; the betting modal covers 40 % of the screen at the start.

1. ★ **TL scene title.** The map name and lap ("Flat Oval · Lap 1/2") instead of "PoRace Go2".
2. ★ **TC FPS / step.** "60 fps · 250 Hz" only. The full debug line (ctrl step, inference ms, command, velocity) moves behind TAB.
3. ★ **TR settings gear.** One gear button opens the settings / pause sheet (Flip camera, Pause, Restart, Menu, gfx tier). "Locomotion / RACING" goes (the chips already show state).
4. ★ **BL agent telemetry.** The A2 stream replaces the Restart button (Restart moves into the sheet).
5. ★ **BR watermark only.** `v0.1.0 YYMMDD` stays alone in BR.
6. **Bets as a bottom-sheet tab.** The odds modal becomes a peek tab in the thumb zone instead of a centre overlay.
7. **Result card.** Place, time, best split, Rematch / Next map / Menu: the explicit Win/Loss → Reset step of the flow.
8. **Weather chip.** Weather moves to a small icon chip under the title; the full line goes to the sheet.
9. **Aspect sweep in `ShotProbe`.** Captures at 16:9, 19.5:9, 20:9, 21:9 with a cutout mask; asserts no overlap between corner groups.
10. **Remove low-value UI.** Candidates: the "bumps N" counter, raw "cmd (…)", the Flip button (the director already cuts), duplicate distance text in the standings. Each removal listed in the UI report.

## D. AI animal realism (biomechanics and RL)

1. ★ **Speed-dependent stride frequency (Matt).** Why: humans raise stride frequency with speed (≈ 0.9–1.0 Hz walking, 1.35–1.5 Hz jogging). Matt's gait clock is fixed (1.25–1.5 Hz in training, 1.375 in Unity), so 2.5 m/s needs ~1.8 m strides; the adult jog fails 0/10. Hook: the clock's frequency becomes base + slope × max(0, |vx_cmd| − v0), integrated (not step × constant) in both the env and `MattController`. Observation layout unchanged (phase sin / cos). Engine: `realism.gait_hz_slope` in `matt/env.py`, the same formula in `MattSpec` / `MattController`. Policies: **Matt locomotion** (fine-tune from m20; physics unchanged; interface unchanged, clock semantics v2).
2. **Slope curriculum for Matt.** Why: the adult 10 % grade is 0/10. Hook: tilted gravity (as Go2's F.8 `--tilt_max`) ramped 0 → 6° over training. Policies: Matt locomotion.
3. **Action low-pass in env and runtime.** Why: smoothed motor output, no 20 ms chatter. Hook: first-order filter on the action (α 0.8) before the PD target, both sides. Policies: every policy of the body (an interface change, so new tags).
4. **Sub-step foot contact observations.** Why: high-frequency contact sensing; the policy sees a touchdown that happened between control steps. Hook: max contact over the 5 sub-steps, appended at the end of the observation (frozen-interface rule: zero-initialised weights). Policies: Matt and Go2 locomotion.
5. **Capture-point reward.** Why: centre-of-mass preservation: the capture point stays inside the support polygon at low speed. Hook: `subtree_com`, foot positions. Policies: Matt locomotion and get-up.
6. ★ **Oscillation metric in the ladder.** Why: penalising high-frequency joint oscillation needs a number first. Hook: share of joint-velocity power above 8 Hz (FFT over the 50 Hz action trace), reported per ladder tier; gate < 10 % at the child tier. Engine: `matt/sim.py ladder`. Policies: none (measurement), later a reward term.
7. **Dogs at impratio 1.** Why: one physics contract for mixed races; dogs keep R1 9/10 at impratio 1 (seed 3 at 1.5 m/s from standstill). Hook: fine-tune `go2_loco` at impratio 1. Policies: Go2 locomotion.
8. ★ **Preflight config snapshot.** Why: validate the configuration before a policy initialises: MJCF sha256, joint-order table, gains, gravity, timestep and observation size vs. the checkpoint's tags (the new "tag each checkpoint with its interface and physics versions" rule). Hook: `training/preflight.py` writes `tags.json` next to each run; `train.py` calls it at start and refuses a restore whose tags don't match. Policies: none.
9. ★ **Parallel headless regression.** Why: multi-instance simulation; every policy's race scenarios in one command. Hook: N `PoRace.exe -batchmode -nographics -raceTest` players in parallel over a seed × map × roster grid; a summary table (finish, falls, resets, time). Engine: `tools/regress.ps1`. Policies: none (it's the post-change check for all of them).
10. **Motor torque-speed curve (Go2).** Why: real servos lose torque with speed (stall 23.7 Nm, about 30 rad/s no load). Hook: a velocity-dependent force range in the MJCF + training. Policies: all Go2 policies (physics change, retrain).

## E. CLEAN (merged from the two identical prompts)

1. ★ **Artifact purge script.** `tools/prune.py`: training runs (failed, < 5,000 steps, unreferenced; never one written in the last 24 h or queued), stale players under `Build/`, `Logs/` older than 7 days. `--dry-run` by default; reports MB reclaimed. Today's checkout has no runs or builds to purge, so the script is the deliverable.
2. ★ **Script folders.** `Assets/Scripts/` mixes runtime, probes and test harnesses in one folder of 30 files. Move to `Core/` (racers, controllers, policy, maps), `Probes/` (ShotProbe, FrameProbe, PerfProbe, StressTest, ReplayHarness, ParityRecorder, ModelCheck, UiSelfTest), keeping `Broadcast/` and `Broadcast/UI/`. Moving `.cs` with its `.meta` keeps every GUID, so scenes don't change.
3. **Naming prefixes (adapted).** `BP_` / `SM_` / `M_` are Unreal prefixes; Unity has no Blueprints. Adopt `SM_` for exported meshes and `M_` for materials in `Assets/Art/`, keep class-named scripts (Unity requires file = class). Not applied wholesale: `Resources.Load` paths and the builders reference names.
4. **Console noise.** *Measured instead of built: a `-raceTest` log is 75 lines (one-off setup, ticker, results), so a `Log.Verbose` switch has nothing to gate. Dropped.* The real noise was the trainer: MuJoCo-Warp prints "solver iterations limit reached" every step (m25.log reached 300 MB), now filtered at launch.
5. **Unreferenced assets.** Scan for materials, textures and meshes with no GUID reference from scenes, prefabs, `Resources` or builders; list before deleting.
6. **Policies folder.** `go2_loco_fast.onnx` isn't used by any map (F.9 parity pending) and `zero_policy.onnx` is the B.9 harness. Keep both, tag them in a `Policies/README`.
7. **SCREENSHOTS size.** 99 tracked PNGs (20 MB) in git. Convert report captures to JPEG q85 or keep only the latest report per feature.
8. **`Assets/Local/MjImports`.** The MJCF importer's scratch output for the G1. Gitignore it if it's regenerated.
9. **Duplicate helpers.** Ring buffers, smoothing filters and `Paint` / colour helpers recur across `Broadcast/`; fold them into `BroadcastUi` / `RacerMath`.
10. **UX declutter.** The same as C3–C5 and C10.

## Not adopted from the prompt, and why

- **SSGI, ray tracing, contact shadows, volumetric refraction, chromatic dispersion:** HDRP features; URP equivalents are in B1–B6.
- **CCD and PhysX mass and momentum tuning:** physics is MuJoCo, never PhysX; the audit (B9) measures the MuJoCo contacts instead.
- **Agent count and training instances:** "multi-instance" maps to parallel headless race players (D9) and the trainer's 1024 parallel worlds; one GPU (RTX 2060, 6 GB) can't run two trainer containers at once.
