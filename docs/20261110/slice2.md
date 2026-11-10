# Slice 2 — One race, one racer, 2026-11-10

Result: **PASS**. Blue runs Planar Sprint in Unreal from countdown to finish, unattended, and the race matches the
Python reference race.

## Results

`Scripts/regress.ps1 -Track planar_sprint -Seeds "1,2,3,4,5"`:

| Seed | Unreal | Python, same model | Python, track file | Checks |
|---|---|---|---|---|
| 1 | 76.50 s | identical | 76.36 s (0.18 %) | 3 OK |
| 2 | 76.31 s | identical | 76.27 s (0.05 %) | 3 OK |
| 3 | 74.94 s | identical | 74.45 s (0.66 %) | 3 OK |
| 4 | 76.20 s | identical | 75.87 s (0.44 %) | 3 OK |
| 5 | 75.76 s | identical | 75.72 s (0.05 %) | 3 OK |

Every seed: 0 resets, 0 off-track, 0 un-sticks, 0 falls. Flip test (`-RaceFlipAt=20`, seed 1): Blue is knocked onto
his back at 20.1 s, the get-up brain stands him up by 22.4 s, the running brain is back at 22.9 s, finish 80.30 s;
identical to Python on the same model.

Against the Unity log: the Unity single-dog sprint was 74.42 s at a flat 1.5 m/s command. Each race now draws its own
cruise speed (1.41–1.5 m/s, as Unity's 4-racer races did), so times scale with it: seed 3 drew 1.49 m/s and ran
74.94 s (0.7 % off 74.42 at that speed); the plan's "within 2 % of 74.4 s" holds for the seeds that drew 1.47 m/s or more.

## What "same model" and "track file" mean

- **Same model**: Python steps the exact model Unreal ran (`Saved/PoRace/model_bound_<track>.mjb`). The result lines
  are byte-identical: the race rules, the brains, the get-up switch and the resets are the same code in both runtimes.
- **Track file**: Python steps `training/assets/tracks/<track>.xml`. URLab simplifies the drawn meshes on import
  (192 k vertices to 10 k for the Go2). They never collide, but they are part of each body's bounding-volume tree, so
  MuJoCo finds and sums the floor contacts in a different order. That is a rounding-level difference that a 76 s
  closed loop grows to at most 0.66 %. Bisected: geom sizes, positions, bounds, friction, `dof_length` and every solver
  option were each ruled out. The gate is 1 %.

## New contracts (Python and Unreal both)

- The seeded draw is SplitMix64 (`racelib/rng.py`, `RaceRng.h`): Unity's `System.Random` cannot be reproduced outside .NET.
- Every timer is a whole number of 4 ms physics steps: countdown 750, fall reset 1250, stall reset 2500, un-stick 125,
  back-off 300. The get-up hands back to the running brain after 25 straight decisions with the up vector above 0.9.
- Lengths use `sqrt(dx*dx + dy*dy)`, not `hypot` (CPython's `math.hypot` is its own algorithm).
- Off-track resets (more than 1 m past the half width) are counted separately from fall and stall resets.

## Things found on the way

1. **The race must wait for the first drawn frame.** The editor binary run with `-game` scans its asset registry
   (9,000 files, 67 s) before drawing anything, while URLab starts physics at level load: the countdown and most of
   the race ran unseen. `URacerController` now leaves the model alone until `ARaceDirector`'s first tick, then resets
   it completely and starts the countdown. A slow first frame on any machine is covered the same way.
2. **A stale Blueprint copy.** `TObjectIterator<URacerController>` returned a `TRASH_` instance left by Blueprint
   re-instancing. The controller is now found through the live track actor (`URacerController::Find`).
3. **The marker check needs a still racer.** Right after the grid reset the drawn pose is a frame behind the teleport
   (25 cm). The check runs 1 s into the countdown: drawn and MuJoCo positions 0.000 cm apart, every seed.
4. **HUD text.** `FCanvasTextItem::Scale` is ignored by the engine's runtime fonts; the HUD sets point sizes instead.
5. **Motion blur** off on the chase camera (it smeared the flip).

## Files

- `training/racelib/` (track, rng, go2racer, race), `training/race.py`, `training/build_track_model.py`
- `Source/PoRaceUnreal/`: `RaceTrack`, `RaceRng.h`, `RacerGo2`, `RaceRules`, `RaceModel`, `RaceHUD`, `RaceDirector`,
  `RacerController` (race + testbed)
- `Scripts/build_track.py` (the level), `Scripts/regress.ps1`
- Screenshots: `Saved/PoRace/shots/` (`-RaceShots=<dir>`), not committed.

## Open

- The drawn track is plain (two grey shades, engine cube tiles): Slice 8 is the look.
- Race brains are read from `training/models/brains/*.onnx` on disk; cooked builds need them as assets (Slice 12).
