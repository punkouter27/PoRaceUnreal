# Slice 1 — Physics parity for Blue, 2026-11-10

Result: **PASS**. Unreal + URLab + MuJoCo 4.0.0 moves the Go2 exactly as the training simulation does.

| Check | Result |
|---|---|
| Brains on MuJoCo 4.0.0 (`training/version_check.py`, CPU) | All six Go2 brains pass their rungs; numbers within 0.03 m/s of MuJoCo 3.15.0. No retraining. |
| Hold, 2 s, no brain | 0 difference from the training model at every step |
| Replay, 5 s of recorded controls | 0 difference at every step |
| Brain in the loop, 5 s at 0.5 m/s | Unreal and Python both end at x = 2.029 m, 0.000 cm apart |
| Unreal's brain vs onnxruntime | 0 difference over 250 decisions |
| Model readback | 140 physics arrays, 0 differ |

Run it: `cd training; uv run --no-project --python 3.12 --with mujoco==4.0.0 --with onnxruntime --with numpy python parity_check.py run`
(or `scripts/verify_all.ps1 -Only parity`). Results: `docs/parity/ue_parity.json`.

## What URLab got wrong, and the fix

URLab rebuilds an imported MJCF from its own components. Measured on the Go2:

1. **The free joint picks up the default class's joint damping (0.5) and armature (0.01).** MuJoCo never applies class
   defaults to a free joint, so the trained Go2 has none. In Unreal the whole body was dragged: with the brain in
   the loop it ended 8 cm short of the training model after 5 s. This would have affected every racer.
2. **Sites lose their positions.** The four foot sites came out at the body origin. The brain does not read them, but
   foot sensors and footstep effects will.
3. **Single precision.** Masses, ranges, friction and margins pass through `float`.
4. **The file's `<option>` block is dropped** (known from PoSlapUnreal): timestep 0.002 instead of 0.004, impratio 1
   instead of 100, 100 solver iterations instead of 1.

Fix: `training/contract.py` writes the training model's own numbers into the fingerprint (`model` section: bodies,
joints and their dofs, actuators, sites, geoms by body and order). `URacerController::Bind` writes them over URLab's
model by name, then calls `mj_setConst` so MuJoCo's derived constants follow. Visual-only geoms keep URLab's pose
(it re-centres their meshes) and get only their margin. The bound model is saved to `Saved/PoRace/model_bound.mjb`
and the readback compares it with the training model.

Exempt from the readback, with reasons in `training/parity_check.py`: `dof_length` (only the sleep test reads it, and
sleep is off; the check fails if sleep is turned on) and visual-only arrays.

## URLab on MuJoCo 4.0.0

URLab was pinned to 3.10.0. Moving it to 4.0.0 needed one source change: in MuJoCo 4 the spec's `limited` flags are
the `mjtLimited` enum and `active` / `actgravcomp` are `mjtBool`. Nine assignments in `MjActuator.cpp`, `MjJoint.cpp`,
`MjTendon.cpp` and `MjEquality.cpp`. URLab's code generator (`Scripts/codegen/generate_ue_components.py`) still emits
the old form; regenerating the components would undo the fix.

All URLab changes: `Plugins/urlab_porace.patch` (10 patches on upstream `efbc5e2`). Patches 4–6 are PoSlap's Android
build for MuJoCo 3.10.0 and will need checking against 4.0.0 in Slice 12.

## Carried into Slice 2

- Coordinate marker check (MuJoCo metres → Unreal centimetres, Y mirrored): nothing is drawn from MuJoCo poses yet.
- A run-time assert that no Chaos body simulates (the testbed script turns Chaos off; nothing checks it while running).
