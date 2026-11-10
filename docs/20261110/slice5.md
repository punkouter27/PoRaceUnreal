# Slice 5 — Race rules complete, 2026-11-10

Result: **PASS**. Tactics, yellow flag, handicap, bump count and contact audit run in both the Python reference race and
Unreal, line for line; every Unreal race below is identical to Python on the same model (result line, pass events and
contact audit).

## Checks (`Scripts/regress.ps1`)

| Run | Seeds | Result |
|---|---|---|
| Planar Sprint, tactics on, `-ContactGate` | 1–5 | 5/5 identical, gate passes |
| Flat Oval 2 laps, `-Handicap -ContactGate` | 1–5 | 5/5 identical; finishes 0.8–4.6 s apart, Blue passes Matt on seeds 1 and 3, 0 bumps |
| Flat Oval 2 laps, leader knocked over at 20 s, `-ContactGate` | 1–5 | 5/5 identical |
| `-NoTactics`: Flat Oval 1–3, Planar Sprint 1–5 | 8 | the Slice 3 result lines exactly (plus the new `bumps=` field) |
| Planar Sprint, both racers knocked over, `-YellowFlag` | 1–2 | identical; no yellow flag (the rule needs 3+ on the grid) |
| Self test (`-RaceSelfTest` / `training/selftest.py`) | — | 12 lines identical: pass, pass left, avoid, hold a pass, let go, block, timid, boxed in, stumbling, yellow 3 and 2 racers |

Contact audit (Planar Sprint seed 1): feet sink at most 1.9 cm, past 1 cm for at most 0.08 s (gate 0.1 s); no other
contact class past 2.5 cm. Unity measured 0.14–0.18 s on its own races.

## Rules added (Unity MultiRaceOrchestrator)

- **Tactics**: pass a slower racer up to 2.5 m ahead (a fallen one up to 5 m, 0.85 m aside) on the side with more room;
  an aggressive racer (> 0.5) blocks an attacker within 1.5 m behind; tactical offset slewed at 0.6 m/s; sideways
  command ≤ 0.25 m/s; no manoeuvres on banks. Passes counted with 0.25 m hysteresis.
- **Yellow flag**: 2+ racers down on a 3+ grid: 80 % pace for ≤ 5 s, 15 s cooldown. On in interactive races, in tests
  only with `-YellowFlag`. HUD banner.
- **Handicap**: head starts so expected finish times are equal (`-Handicap`, menu toggle, `?Handicap=1`).
- **Bumps**: robot-robot contacts in the result line (`bumps=N bumpTime=X s`).
- **Contact audit**: per class (foot-floor, body-floor, robot-robot, self, other) the deepest penetration and the
  longest run past its limit; `-ContactGate` fails the test with exit 4.

## Changed from Unity (bugs the Unreal tests found)

1. **Off-track reset loop.** After a reset the progress walk stayed on the segment the racer had reached; put back on a
   curve, it measured as off the track every step (Flat Oval handicap seed 3: 124 075 resets, DNF). Now the walk restarts
   at the spawn's segment.
2. **"Slower" uses the pace a racer holds.** Cards carry `pace` (go2 1.0, matt 0.92, measured); Unity compared
   commanded speeds, so Blue never passed Matt at equal commands and rammed him (40 bumps).
3. **The handicap uses the same pace**: Unity's head starts went to whoever drew the lower command, often Blue.
4. **A pass holds until 1 m clear**: Unity's passer drifted back once 0.55 m aside and cut across the slower
   racer's nose (seed 1: Matt knocked down, 5.8 s of contact).
5. Cards carry `footGeoms` for the audit (names resolved through URLab's actor prefix).

## Open

- The yellow flag cannot fire in a real race until a third racer is ready (Grandma or G1).
- Intent markers above racers are Slice 7; the standings show the intent (PASS L / PASS R / AVOID / BLOCK).
