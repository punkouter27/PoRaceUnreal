# Agent guide

PoRaceUnreal is an Unreal / MuJoCo RL racing simulation. MuJoCo is the sole
physics authority; Unreal renders and presents the simulation. Read `SPEC.md`,
`docs/PRD.md`, `tasks/plan.md`, and the latest completed slice report in
`docs/` before making project changes.

## Project contracts

- Keep the Python reference race, Unreal runtime, and browser runtime aligned.
  `training/contract.py` is the source for generated contract files; regenerate
  and run its `--check` mode instead of editing generated values by hand.
- Preserve the frozen physics, observation, action, joint-order, and checkpoint
  contracts. Changes to them require the corresponding parity and race gates in
  `tasks/plan.md`; do not retrain, promote, or replace brains without those gates.
- Chaos must not simulate racers, track elements, or props. Use the existing
  MuJoCo / URLab pipeline and its model and contact audits.
- Follow the approved slice order and stop at any failed gate. Preserve the
  recorded decision not to use a Unity baseline and retain incomplete-slice
  status as documented; do not imply unverified features are complete.
- Keep compatibility-sensitive paths as they are unless a planned slice
  explicitly covers their migration. The current `Scripts/` casing and
  `Source/PoRaceUnreal/` layout are known differences from the canonical
  Profile B layout, not a reason for an unplanned mass rename.

## Workflow

- Work on `master`; preserve existing local work. Do not commit, push, or deploy
  unless explicitly requested.
- Keep training and generated artifacts out of unrelated changes. Do not prune
  checkpoints or run folders unless the project's cleanup procedure permits it.
- Use the smallest relevant checks from `tasks/plan.md` for changed areas.
  Report skipped engine, device, visual, or long-running gates explicitly.
- For UI changes, retain the five HUD anchors and bottom-docked, non-overlapping
  panels; save the required before/after evidence under `SCREENSHOTS/`.
