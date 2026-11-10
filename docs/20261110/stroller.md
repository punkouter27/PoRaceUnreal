# The Stroller: a wheeled racer, 2026-11-10

Result: **on the roster and racing.** A scanned three-wheeled jogging stroller (source: `C:/Users/punko/Downloads/Stroller`,
copied to `Content/Art/Stroller/`) with a trained rolling brain. Ready on flat tracks; races identical in Unreal and
Python.

## Body (`training/stroller/make_model.py`)

Measured from the rig in Blender: rear wheels r 16.8 cm, 58.7 cm apart; front wheel r 12.8 cm, 67 cm ahead of the rear
axle; frame 1.12 x 0.78 x 1.0 m. MuJoCo: a 12 kg chassis on a free joint (centre of mass low and toward the rear axle),
collision boxes for the seat, canopy, fork and a capsule push handle, all at least 10 cm off the ground; a steering fork
(position servo, +-45 deg) carrying the front wheel; two rear wheels on torque motors (2 N.m each). 14 kg in all. The
scan's README sets it up as a Chaos vehicle; not used (MuJoCo owns all physics here).

Two physics findings:
- **Euler damping off** is required: the race runs with it disabled (`disableflags 32768`); with it on the light front
  wheel spun to 345 rad/s on touchdown under the race's 1-iteration solver and launched the stroller.
- **impratio 1**: at the dogs' 100 the stiff friction binds the three wheels and steering does nothing. The stroller
  trains and races at 1, as Matt does (a race runs at its grid's lowest).

## Brain (`training/stroller/env.py`, run s1)

Obs 20 (body velocity, gyro, gravity, steer angle and rate, wheel speeds, last action, command); action 3 (steer, left
and right wheel torque). Rewards: speed and turn tracking, side slip, staying upright, smooth actions. Trained with
`train.py --env stroller`: 14.7 M steps, 16 min on the RTX 5070 Ti. Weights `training/final/stroller_s1_params.pkl`,
brain `training/models/brains/stroller_roll.onnx`.

Ladder (`stroller/sim.py ladder`, MuJoCo 4.0.0 CPU, the race's own racer code):

| Test | Result |
|---|---|
| Hold still 10 s | 10/10, drift <= 0.10 m |
| Straight 1.0 / 1.5 / 2.0 m/s | 10/10 each, error 0.095 / 0.023 / 0.010 m/s |
| Turn +0.8 / -0.8 rad/s at 1 m/s | 10/10 each, error 0.012 / 0.084 rad/s |
| Reverse 0.5 m/s | 10/10 |
| Graduation: 100 x 20 s of race-range commands | 100/100, mean error 0.074, never tipped |

A hand-written proportional controller scores 0.139 on the same graduation; the brain halves it.

## Races

| Run | Seeds | Result |
|---|---|---|
| Planar Sprint, Blue + Matt + Stroller, `-ContactGate` | 1–5 | Unreal identical to Python (result, events, contact audit); stroller wins 3, Blue 2 |
| Flat Oval 2 laps, all three, `-ContactGate` | 1–3 | identical; stroller wins 2, Blue 1 |
| Planar Sprint, Blue + Matt (stroller parked) | 1–2 | identical; seed 1 unchanged from Slice 5, seed 2 Matt 75.45 s (was 75.46: the block rule below) |
| Self test | — | 14 lines identical |
| UI test at 1280x720, 540x1170, 1680x720 | — | 0 failures (menu shows 5 racers, 3 ready) |
| Windowed race | seed 1 | mesh on its body to 0.004 cm; mesh-to-chassis alignment measured from the hubs: 0 deg, 0 cm; rear track 58.7 cm on mesh and model |

## Rule changes (both runtimes; Unity had neither problem with 0.35 m dogs)

The first three-racer races were a pile-up: Flat Oval seed 1 had 909 bumps and 113 s of contact in a 157 s race.

1. **Width-aware gaps.** Cards carry `width` (Go2 0.35, Matt 0.55, stroller 0.65, Grandma 0.5). Passing, avoiding and
   the "in the way" window keep half the two widths + 0.2 m, never less than Unity's numbers, so dog/human races keep
   Unity's 0.65 m pass gap. A blocker never closes to within that gap of its attacker (it leaned on the stroller).
2. **Alongside.** Two racers level with each other (within 0.8 m along the track) keep the gap on their own side
   instead of following a lane squeeze into each other. Unity's rules only looked ahead; Planar Sprint squeezes every
   lane to the centre from 40 to 60 %.

After: 0.2–0.7 s of contact per race, no falls.

## Also

- Menu: three racer chips a row (five made the panel overflow 16:9); on a portrait phone the frame-rate readout moves
  to the bottom centre ("3. Stroller" reached it).
- Trainer image: `mujoco-mjx` pinned to 3.15.0 (playground pulled 4.0.0, whose `mujoco-core` broke `mujoco` 3.15.0).
- The stroller's `pace` is 0.97 (Planar Sprint alone: 100 m in 70.92 s at 1.45 m/s).

## Open

- Flat tracks only: banks and hurdles are untested for it (Slice 6 decides).
- No get-up: a tipped stroller lies there until the 5 s reset (none tipped in any race so far).
- The intro card calls it "stroller"; a nicer label and its own sounds come with Slice 7–8.
