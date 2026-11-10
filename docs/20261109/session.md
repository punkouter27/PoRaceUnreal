# Session 2026-11-09: proposals round 3 and Grandma

Machine: RTX 2060 6 GB (Docker `porace-trainer`, 1024 envs, `XLA_PYTHON_CLIENT_MEM_FRACTION=0.30`), fresh checkout, Unity 6000.6.0f1, Blender 5.2.
Unity runs with `-batchmode -nographics` while the GPU trains; that ran beside run m25 with no trouble. Only graphics runs (`-shots`) wait for the GPU.

## Policies each change touches (AGENTS.md "before any change")

| Change | Policies touched | Why |
|---|---|---|
| Gait clock v2 (stride rises with speed): `matt/env.py`, `g1/sim.py`, `MattController` | **Matt locomotion** (new run m25; m20 unchanged, slope 0 in `MattSpec`) | New clock meaning; observation layout unchanged |
| Grandma: body, env, card, Unity controller | **Grandma locomotion** (new, from scratch) | New character, her own policy |
| `MattController` → `HumanSpec` (prefix, spec per human) | Matt locomotion: re-checked, **bit-identical race** (Planar Sprint seed 7, Matt 76.86 s) | Code path only |
| Yellow flag | None (commands stay inside every trained range; off in `-raceTest` unless `-yellowFlag`) | Rules |
| Wobble warning, telemetry, HUD corners, quality governor, modal audio, contact audit | None (read only, or visuals) | Visuals |
| Preflight tags | None (tooling) | |
| Agent vocal sound banks (`HAPPY`, `ANGRY`, `HURT`, `INSULT` × 5 sounds × 5 expressiveness levels 1–5, WAV + procedural fallback) & 16-character placeholders | None (audio and character metadata only) | Visuals / audio |
| 16-player main menu roster placeholders + symmetric tournament bracket (8 left, 8 right, winner in middle), self-playing tournament mode, and agent ELO ratings | None (menu UI, match flow, ELO persistence) | Game flow / UI |

## Regression after the code changes (`tools/regress.sh`, headless, timeScale 4)

| Scenario | Baseline (r2 build) | Round 3 build |
|---|---|---|
| Dogs, Planar Sprint, seed 7 | Green 81.80 / Gold 82.20 / Blue 82.33 / Red 83.53 s, 167 bumps | **same** |
| Dogs + Matt, Planar Sprint, seed 7 | Gold 71.13 … Matt 76.86 s, 226 bumps | **same** |
| Dogs + Matt, Flat Oval, seed 3 | Gold 130.68 … Matt 148.36 s | broke: Grandma's controller ran OnInit while off the grid (fixed: an inactive human skips init); re-run below |
| Grandma on the grid (no policy yet) | – | `[GrandmaCheck] OK` mass 73.6; DNF as expected (hold pose) |

Contact audit, first measurement (all within the existing contract, same on the baseline physics):

- **Foot to floor:** peaks 2.5–2.7 cm and stays over 1 cm for 0.14–0.18 s.
- **Robot to robot:** peaks 2.2–3.2 cm, for under 0.01 s.

This is soft-contact sink with the race solver at 1 iteration. `-contactGate` makes it fail a test; it's off by default.

## Training runs

See `rl_optimization_log.md` (2026-11-09) for m25 and Grandma's runs. TensorBoard runs at http://127.0.0.1:6007 from inside the trainer container.

### Grandma `g6` completion (102,727,680 steps in 2,314 s / 38.6 min)

- **Checkpoint & tags:** `training/runs/g6/params.pkl` (`physics 5e79c99044f02ace`, `interface 265293b4b0b21c42`, `obs 103`, `act 29`, `ctrl 0.02 s`, `sim 0.004 s`, clock `gait_hz_v0=0.9`, `gait_hz_slope=0.2`), resumed from `runs/g5/checkpoints/000034242560`.
- **Intermediate checkpoints:** `params_000016220160.pkl` (16.2M), `params_000032440320.pkl` (32.4M), `params_000054067200.pkl` (54.1M), and final `params.pkl` (102.7M).
- **Eval reward progression (`training/runs/g6_tb.json`):**
  - `eval/episode_reward`: `13.47` (0) → `39.12` (16.2M) → `76.46` (32.4M) → `106.39` (43.3M) → **`121.43` (70.3M peak)** → `117.28` (81.1M) → `120.32` (97.3M) → `117.38` (102.7M).
  - `eval/avg_episode_length`: `64.9` (0) → `254.5` (32.4M) → `345.7` (43.3M) → **`378.7` (70.3M peak)** → `375.9` (91.9M).
  - `eval/episode_reward/tracking_lin_vel`: `72.2` (0) → `311.1` (32.4M) → `490.9` (70.3M) → `520.6` (81.1M) → **`526.3` (97.3M peak)**.
  - `eval/episode_reward/tracking_ang_vel`: `30.2` (0) → `197.0` (32.4M) → `350.8` (70.3M) → **`363.8` (97.3M peak)**.
- **HTML report:** `docs/20261109/g6_report.html`.

## Roster trim: one dog (owner's call)

- **Change:** Red, Green and Gold are gone from every race scene. `RosterBuilder.KeepOneDog` removed them, and `RaceConfig.Dogs` is now Blue only.
- **Policies touched:** none. Blue runs the same Go2 policies, and the humans are unchanged.
- **Regression baseline:** the 4-dog baseline numbers above no longer apply; the one-dog grid replaces them (`tools/regress.sh`).
- **Lone racer:** a banked or steeplechase race is now Blue alone, since the humans' policies are flat-only.

## Game loop: menu → intro → race → results → OK → menu

Scene browse found the loop open: the plain launch autoplayed past the menu, no racer intro, the stats card had no way back. Fixed (report `SCREENSHOTS/loop_report.html`):

- **Policies touched:** none. Visuals, UI and game flow only. The intro holds the grid on the start line exactly as the countdown does (same commands), and is off in `-raceTest`. The new "race called 60 s after the winner" rule (`finishWindow`) is off in `-raceTest` too.
- **Regression:** `-raceTest -timeScale 4`, old build vs new, bit-identical: Planar Sprint s7 + Matt (Blue 71.29 / Matt 73.76), Flat Oval s3 + Matt (138.43 / 146.86), Steeplechase s3 (Blue 87.06).
- **Flow:** a plain launch opens the menu; the self-running app needs `-autoplay`. Racer intro (`RacerIntro`, added at scene load, `-noIntro` skips it); the results card declares the winner, its OK goes to the menu. `-autoOk <s>` presses OK in captures; with `-menuMap` the player then loops menu → race indefinitely.
- **Fixes:** off-grid humans' skins hidden; a season table or track record that names a racer no longer on the roster starts over; Grandma menu chip (locked with her card's `blockedBy` until `raceable`); "up to N racers"; trackside / finish / leader cameras inside the rails (leader goes head-on when a rival is < 2.5 m behind); split box clear of the PiP; HAZARD and split box hidden at the finish; colour-blind label 12 pt; solo races labelled time trial.
- **Matt's look:** `Matt.mat` gloss scale 1 → 0.45 (about 5 % of `matt_metal_smooth`'s alpha is 1.0, which rendered as mirror patches); his team rim at 0.45 × strength. `CreatureBuilder` writes the same value.

## Agent sound banks, 16-player placeholders, ELO & symmetric tournament bracket

- **Policies touched:** none (audio, character definitions, menu UI, tournament flow and ELO persistence only).
- **Agent sounds (`AgentSounds.cs`, `CreatureDefinition.cs`, `CreatureBuilder.cs`, `RaceAudio.cs`):**
  - 16 character slots (`Blue`/`Go2`, `Matt`, `Grandma`, `Agent04`..`Agent16`), each carrying 100 sound slots: 4 categories (`HAPPY`, `ANGRY`, `HURT`, `INSULT`) × 5 sounds (`1..5`) × 5 expressiveness levels (`1 = weakest` .. `5 = strongest`).
  - Lookup order: serialized `CreatureDefinition.soundBank` slot → `Resources/AgentSounds/<Agent>/<CATEGORY>/<Agent>_<CATEGORY>_s<1..5>_e<1..5>` WAV asset → procedurally synthesized vocal clip (Rosenberg glottal harmonics + subharmonic growl + aspiration noise through 3 time-varying vowel formant resonators $F_1, F_2, F_3$, robotic ring/FM modulation for robot bodies, and nonlinear vocal-effort saturation scaled by expressiveness `1..5`).
- **16-player symmetric bracket, random seeding & random tracks (`Tournament.cs`, `BracketScreen.cs`, `MenuController.cs`, `AgentElo.cs`):**
  - 8 starting player slots on the left (`Slots 0..7`) and 8 starting player slots on the right (`Slots 8..15`), converging inward to the `LEFT FINAL`, `RIGHT FINAL`, and the central **`WINNER`** box in the middle (`x = 360`).
  - Filled with current players + `BYE` placeholders; entrants are randomly seeded across the Left 8 and Right 8 slots each tournament, and each match selects a random eligible track.
  - Self-playing Tournament Mode (`Tournament.AutoPlay = true`) plays match-by-match until a single winner is crowned in the middle, recording ELO ratings (`<persistentDataPath>/elo.json`, default 1500, $K = 32$) for every agent.

## Tournament, attract mode, Dog (owner's calls)

- **Policies touched:** none. A tournament match is an ordinary two-racer race; demo races are the existing self-running app; the rename is a label. Regression after the rename: Planar Sprint s7 + Matt, Dog 71.29 / Matt 73.76 (unchanged), UiSelfTest ok.
- **Rename:** the Go2 racer "Blue" is now "Dog" (`RaceConfig.Dogs`, racer name in Track01x4 / 02 / 03 / 04). Its livery stays blue. Saved season tables and records naming Blue start over (`RaceConfig.OnRoster`).
- **Tournament** (`Tournament.cs`, `BracketScreen.cs`, menu TOURNAMENT button): every available racer (Dog, Matt, Grandma once raceable) seeded into a 16-slot knockout bracket (1 v 16, 8 v 9, ...); empty slots are BYEs and advance their opponent. Only two-racer matches are raced, on the flat maps in turn by round (humans are flat-only). Winner = first home, else furthest when the race is called. With today's two racers: byes to a Dog vs Matt final (Flat Oval; Dog 136.86 s). Session-only state. Probe: `-tournamentAuto -autoOk 4` plays it unattended.
- **Attract mode** (`AttractMode.cs`): menu idle 30 s (`-attractAfter <s>`, `-noAttract`) starts demo races (autoplay) with a blinking "DEMO · PRESS ANY KEY / TAP TO PLAY"; any key, click, touch or gamepad press returns to the menu. Off in -raceTest, batch mode and probe runs.
- **Intro:** hard cut to each racer plus a slow push-in (a glide between side-by-side racers on the oval passed through Matt).
