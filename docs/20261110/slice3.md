# Slice 3 — Matt and mixed fields, 2026-11-10

Result: **PASS**. Blue and Matt race each other on Planar Sprint and Flat Oval in Unreal, and every race matches the
Python reference race exactly.

## Results

`Scripts/regress.ps1` (Unreal headless race test, then Python on the same model and on the track file):

| Race | Seeds | Unreal | Same model | Track file | Checks |
|---|---|---|---|---|---|
| Planar Sprint, Blue + Matt | 1–5 | Blue 69.99–70.75 s, Matt 74.08–76.36 s | identical | identical | 4 OK each |
| Flat Oval, 2 laps, Blue + Matt | 1–3 | Blue 133.77–136.56 s, Matt 146.24–151.16 s | identical | identical | 4 OK each |
| Planar Sprint, Blue alone (Matt parked) | 1–2 | 76.66 s, 76.18 s | identical | identical | 3 OK each |
| Planar Sprint, Matt alone, knocked over at 20 s | 1 | 81.68 s, 1 fall, 1 reset | identical | identical | 3 OK |

No resets, falls or off-track moments in any race except the deliberate flip. (Flat Oval in Unity, 4 dogs at
impratio 100: 150.6–155.2 s; Blue alone here at impratio 1 runs 134–137 s.)

Python on the track file now matches exactly too, unlike Slice 2 (up to 0.66 %): both runtimes now write the
fingerprints' exact numbers onto whatever model they loaded (below), and the remaining mesh difference did not reorder
any contacts in these races. The 1 % gate stays.

## Matt's brain on MuJoCo 4.0.0 (`training/human_check.py`)

| Check | Result |
|---|---|
| Training recording's controls replayed | under 1 mm for the whole 5 s |
| ONNX vs the recorded actions | 1.5e-6 |
| `racelib/human.py` with the brain in the loop vs the recording | 0.0 cm after 5 s, 1.077 m/s both |
| Stand 10 s / race speeds 0.8–1.6 m/s / 0.8 rad/s turn | 10/10, 10/10, 10/10 |

The chain to Unreal: the racer class reproduces training exactly, and Unreal's races are identical to it. Same as 3.15.0;
no retraining.

## The physics setting a mixed race runs at

Matt trained at impratio 1; at 100 he cannot walk (0/10 at race speeds). Blue trained at 100. At impratio 1 Blue's
running rungs all pass, and his get-up over 50 random falls is unchanged: 46/50 up within 3 s at both settings,
median 1.12 s vs 1.16 s (an earlier 7/10 on 10 falls was sampling noise). Rule, as in Unity: **a race runs at the
lowest impratio of the racers on its grid** (each card's `impratio`). Blue alone keeps 100.

## Matt in the race (`racelib/human.py`, `RacerHuman.cpp`)

The training sim's brain loop (103 inputs, two-foot gait clock at 1.375 Hz, actions not clipped) plus the Unity race's
rules: down = pelvis below 0.6 m or torso up below 0.3; after 15 decisions down he goes limp (motor targets follow the
joints) until the 5 s fall reset; during the countdown he steers to hold the track heading (he drifts on a zero
command); no un-stick (slow ramp); yaw rate up to 0.8 rad/s. Knock-over (the flip test) lays him on his back as the Unity
controller did; the Go2's upside-down pose put his legs into the floor and the solver threw him off the track.

## Roster selection and parking

Every eligible racer is attached to the track model (`build_track_model.py`). `-Racers=blue,matt` (Unreal) /
`--racers` (Python) picks the grid; the rest are parked: held still 5 m above the floor, 40 m off the track, every
step, so they never touch anything and run no brain. Their drawn bodies are hidden.

## Matt's skinned scan (`ARacerVisual`)

Port of the Unity MattSkin: 22 Mecanim bones mapped to his MuJoCo bodies; each bone's world rotation = body rotation x
a rest offset, the hips follow the pelvis, the other bones keep their rest offset from their parent (four spine bones
ride one torso body). The mesh-to-world turn is found from the leg anchors at start-up: -90 degrees (as Unity), leg
81.8 cm on the mesh and between the bodies, hips 0.0 cm from the pelvis body. URLab's capsules of his body are hidden.

Fixed on the way: the FBX root carries a x100 scale with bone offsets in metres, so driven bones must keep the
accumulated rest scale (he came out 1 cm tall); the actor now follows the pelvis so the mesh's bounds go with him
(he disappeared once 5 m from the origin).

## Found and fixed

- **`MjSpec.to_xml()` rounds to 6 significant digits** (capsule half-lengths 0.20706704 -> 0.207067). The Python
  reference now applies the fingerprints' exact numbers after loading (`racelib/model.py`, the same code as
  `RaceModel.cpp`), so both runtimes step training's values.
- **Parallel race tests broke URLab's mesh cache.** Three Unreal processes compiling at once collided writing the same
  mesh file; the compile failed and the races waited for ever. `regress.ps1` now starts each race only after the
  previous one compiled its model, and a race test that has not started 240 s after its first frame exits 2.
- **The level script missed an existing Blueprint** (the asset registry was not scanned yet in the commandlet). It now
  scans first and checks the file on disk.

## Open

- Matt renders in flat grey: his albedo is largely grey and Unity layered a tint and bib on top (`MattLook`). Slice 8.
- The chase camera frames the pack mean; Matt can block Blue from behind. Slice 7 (the director's cuts).
- Grandma is still "not ready" (her g14 brain, 94/100 at graduation, is not verified yet).
