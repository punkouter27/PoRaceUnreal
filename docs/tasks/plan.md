# PoRaceUnreal — Vertical-slice plan

Status: approved 2026-11-10. Slices 0–5 done (reports: `docs/20261110/slice1.md` … `slice5.md`). Requirements: `docs/PRD.md`. Design: `docs/spec.md`. Checklist: `docs/tasks/todo.md`.

Each slice ends with something that runs and a check that passes. A slice does not start until the one before it passes. "Blast radius" names what a slice can break.

---

## Slice 0 — Salvage and repo

**Goal:** everything needed from the Unity project is inside PoRaceUnreal, so `PoRace/` can be deleted.

- **Acceptance:** every row of SPEC §6 is copied; track and creature definitions are converted to JSON; the new repo has its first commit.
- **Test assertions:** file counts and hashes match the sources for copied files; every `.onnx` loads in onnxruntime and reports the expected input and output sizes (48→12, 42→12, 103→29); every MJCF compiles in MuJoCo 3.15.0 and 4.0.0; `check_model.py` passes for Go2, Matt and Grandma from the new location.
- **Verification:** `python tools/salvage_check.py` prints a table of source → destination with OK per row.
- **Blast radius:** none in PoRace (read only). Stop point: **the owner deletes `PoRace/` only after this slice is reported green.**
- **Note:** no Unity baseline run (owner's call). Regression uses the Python reference race and the Unity times already logged in `docs/unity_tasks.md`.

## Slice 1 — Physics parity for Blue (the go / no-go slice)

**Goal:** Blue stands and walks in Unreal exactly as in MuJoCo.

- **Acceptance:** trainer and URLab move to MuJoCo 4.0.0; Blue's brains pass their ladder rungs in Python on it (retrain any that fail); Unreal project builds; the Go2 model imports; the zero-brain hold, replay and closed-loop gates pass with `go2_loco.onnx`.
- **Test assertions:** marker check lands at (0,0,0), (100,0,0), (0,−100,0) cm; model readback has no field differences beyond float residue; zero-brain max difference < 1e-6; replay every body ≤ 1 mm and action difference < 1e-4; closed loop base ≤ 1 cm after 5 s; no Chaos bodies.
- **Verification:** `scripts/verify_all.ps1 -Only parity`.
- **Blast radius:** the URLab patch and MuJoCo pin. If URLab will not build against 4.0.0, stop and report before any further slice. A retrain of Blue costs GPU hours and is reported with an estimate before it starts.

## Slice 2 — One race, one racer

**Goal:** Blue runs Planar Sprint from countdown to finish, unattended.

- **Acceptance:** track JSON → MuJoCo rails → Unreal level by script; `training/race.py` (reference) and Unreal both run the race; get-up switch works; auto-reset works; build stamp shows.
- **Test assertions:** `-RaceTest -Map=0 -Seed=1..5`: 5/5 finish, 0 resets, time within 2 % of the logged Unity time (74.4 s); Python reference and Unreal agree on finish time within 1 %; a forced flip at 20 s still finishes.
- **Verification:** `scripts/regress.ps1 -Maps 0`.
- **Blast radius:** contract generation (`training/contract.py`); everything later reads it.

## Slice 3 — Matt and mixed fields

**Goal:** Blue and Matt race each other on the flat tracks.

- **Acceptance:** Matt's model imports with his skinned mesh following the physics; Matt passes the parity gates with `matt_m20.onnx`; Flat Oval is built; both racers share one MuJoCo model; roster selection parks the unpicked racer; laps, splits, lane draw and speed spread work.
- **Test assertions:** Matt replay ≤ 1 mm, closed loop ≤ 1 cm; Flat Oval seeds 1–5, 2 laps: all picked racers finish; same seed twice gives identical result lines; Blue-only races give the same times as Slice 2 (parking Matt changes nothing).
- **Verification:** `scripts/regress.ps1 -Maps 0,1`; `-Shots` capture of Matt at rest and mid-stride for a skin check.
- **Blast radius:** the combined option block (SPEC risk 3). Re-run Slice 1 gates for Blue.

## Slice 4 — Game loop

**Goal:** a person can go menu → race → results → menu.

- **Acceptance:** menu (track, roster with ready / not-ready, laps, start), eligibility rules, racer intro, countdown, standings, results card, pause sheet, follow camera, Grandma and G1 listed as not ready.
- **Test assertions:** `-RaceUiTest` resolves every binding; humans cannot be picked on a non-flat track; start is disabled with no racer picked; `-AutoOk` loops menu → race → results 10 times without a leak or a stall; `-Shots` at 16:9, 19.5:9 and 21:9 shows no overlapping corner groups.
- **Verification:** HTML report in `SCREENSHOTS/` with captures of each screen beside the Unity one.
- **Blast radius:** UI only. Race results unchanged (re-run Slice 3 regress).

## Slice 5 — Race rules complete

**Goal:** races behave like the Unity version.

- **Acceptance:** tactics (pass, block, lateral cap), yellow flag, finish window and DNF classification, handicap, unstick logic, contact audit.
- **Test assertions:** `-NoTactics` reproduces Slice 3 result lines exactly; with tactics, Flat Oval seeds 1–5 all finish with ≥ 1 pass logged; forced double fall triggers a yellow flag of ≤ 5 s at 80 % pace; `-ContactGate` passes on every track built so far.
- **Verification:** `scripts/regress.ps1` against the Python reference race.
- **Blast radius:** `URaceOrchestrator` and `training/race.py` must change together.

## Slice 6 — All four tracks

**Goal:** Banked Oval and Steeplechase run with Blue's bank and steeple brains.

- **Acceptance:** banked surface and 34 obstacles import as MuJoCo geoms with matching visuals; per-track brain selection; no-manoeuvre zone on banks.
- **Test assertions:** parity gates pass for `go2_loco_steeple` and `go2_loco_bank`; Banked Oval and Steeplechase seeds 1–5: 5/5 finish, resets no worse than the logged Unity runs; humans are refused on both.
- **Verification:** `scripts/regress.ps1 -Maps 2,3`.
- **Blast radius:** mesh-geom import (SPEC risk 5). Flat tracks unaffected.

## Slice 7 — Broadcast: cameras and signals

**Goal:** the race is watchable without touching anything.

- **Acceptance:** director cuts (pack, leader, battle, trackside, overhead, incident, finish), manual camera, wobble warning with pre-roll, strain glow and standings marks, telemetry corner, recovery countdown, gate timing against the record, intent markers, picture-in-picture, captions.
- **Test assertions:** a scripted fall produces an INCIDENT cut within 0.5 s and a wobble flag before it; gate times interpolate inside a step (two runs of one seed give identical splits); none of these change a result line.
- **Verification:** `-Shots` set per camera; HTML report.
- **Blast radius:** read-only on physics. Result lines must be byte-identical with the layer on and off.

## Slice 8 — Desktop presentation

**Goal:** the advanced graphics that motivated the move.

- **Acceptance:** Lumen lighting, Nanite track and trackside meshes, virtual shadow maps, Niagara dust / sparks / confetti / rain, scuff decals, per-track colour grade, MetaSound footsteps / motors / modal impacts / crowd, quality governor holding 30 fps.
- **Test assertions:** `-FrameProbe 20` p95 ≤ 33 ms on the dev PC at the highest tier the governor settles on; impact effects fire only on real contacts above the impulse threshold; result lines unchanged.
- **Verification:** before / after HTML report in `SCREENSHOTS/`; frame-time table.
- **Blast radius:** rendering and audio only. GPU contention with training: do not run alongside a training job.

## Slice 9 — Replay, ghost and records

**Goal:** races leave a trace.

- **Acceptance:** 8 s replay with pause and resume, slow-motion incidents, best-run ghost, stats card, race logs, persistent track records and recovery records.
- **Test assertions:** entering and leaving replay mid-race gives the same result line as not replaying; a faster run replaces the record and the ghost; `-RaceTest` writes nothing under `Saved/PoRace/`.
- **Verification:** `scripts/regress.ps1 -ReplayAt 20`.
- **Blast radius:** replay snapshots and restores physics state; a bug here changes outcomes.

## Slice 10 — Modes

**Goal:** tournament, season, ratings and attract mode.

- **Acceptance:** 16-slot bracket with byes and auto-play, season with points and persistence, ratings from 1500, attract mode after 30 s idle, self-running loop.
- **Test assertions:** `-TournamentAuto -AutoOk=1` crowns a champion and exits; a tournament with one ready racer ends without a race; season points match 10 / 7 / 5 / 3 / 1 and the half-distance rule; a 2-hour `-Autoplay` soak shows flat memory.
- **Verification:** soak log and bracket capture.
- **Blast radius:** saved-state files.

## Slice 11 — Weather

**Goal:** real conditions change grip and wind.

- **Acceptance:** circuit list in the menu, live fetch with offline fallback, friction scaling, wind force through the single force writer, rain visuals, conditions chip.
- **Test assertions:** `-Weather="rain=2,wind=7,dir=270"` scales world friction within 0.7–1.0 and wind ≤ 10 N; a failed fetch runs dry and says so; `-NoWeather` reproduces the dry result lines.
- **Verification:** `scripts/regress.ps1 -Weather`.
- **Blast radius:** friction writes touch the shared model; must be restored between races.

## Slice 12 — Android

**Goal:** the same races on a phone.

- **Acceptance:** arm64 build; brains through Basic CPU; mobile renderer and device profile; portrait HUD; haptics.
- **Test assertions:** `-RaceBasicCpu` on desktop gives the same result lines as the ONNX path; on a Pixel 9 Pro a 4-racer-equivalent load holds 60 fps; one seed gives the same finish order and times within 0.1 % as Windows.
- **Verification:** device capture and frame-time table.
- **Blast radius:** brain export path; a mismatch between `.onnx` and `.bin` breaks R-9.

## Slice 13 — Browser

**Goal:** a shareable link.

- **Acceptance:** `Web/` runs menu, race, standings, timing and results with MuJoCo WASM and onnxruntime-web; deploy workflow to the game's Azure Static Web App.
- **Test assertions:** `node Web/check.mjs` finishes a race on each flat track; finish order for seeds 1–5 matches the Python reference.
- **Verification:** deployed URL loads and completes a race on a phone browser.
- **Blast radius:** third copy of the rules; `contract.gen.js` keeps it in step.

## Slice 14 — Growth recipes and close-out

**Goal:** the next racer and the next track are a checklist.

- **Acceptance:** `docs/onboarding_racer.md` and `docs/onboarding_track.md`; `scripts/onboard_racer.py`; full regression grid; CI workflows; `CLAUDE.md` and `AGENTS.md` for the new repo; `reference/unity/` removed.
- **Test assertions:** a dry run of the racer recipe with Grandma's body gets her into the roster as "not ready" with no code change; a fifth test track defined only by JSON builds and races.
- **Verification:** `scripts/verify_all.ps1` green from a fresh clone.
- **Blast radius:** none on shipped racers.

---

## Order and dependencies

```
0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8
                          ↘ 9 → 10 → 11
                    3 → 12 (any time after 5)
                    5 → 13 (any time after 5)
                                   all → 14
```

Slices 1–3 carry the technical risk. If they pass, the rest is porting known behaviour.
