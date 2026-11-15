# CLAUDE.md — PoRaceUnreal

See `AGENTS.md`, `SPEC.md`, `docs/PRD.md`, and `tasks/plan.md` for architecture and slice gates.

## Runtime & Profile B Summary
- **Engine / Physics:** UE 5.8 + MuJoCo/URLab (`Chaos` simulation strictly disabled; verified by `ARaceDirector::CheckChaos`).
- **UI & Theme:** Slate/UMG HUD in `Source/PoRaceUnreal/RaceHUD.{h,cpp}`, `RaceHUDUi.cpp`, and shared tokens in `Source/PoRaceUnreal/UiTheme.h`. Bottom-right build stamp displays version + `YYMMDD`.
- **Standardized Controls & Cameras:** `F1` cycles Watch/Play/Testbed mode; `F2` cycles `Broadcast` / `Follow` / `Orbit` / `Free` camera (`ARaceDirector`); `F3` toggles bottom-left RL telemetry (policy badge, reward proxy, `NaN/Inf` counter); `F4` cycles policy override; `Space` / `Esc` toggles pause; `R` restarts the race.
- **Seeds & Determinism:** `-Seed=<n>` CLI parameter / `?Seed=<n>` URL option seeds `FRaceRules::Seed`.
- **Contracts & Training:** Never hand-edit generated files (`RaceContract.gen.h`). Run `python training/contract.py --check`, `training/eval.py`, `training/export_onnx.py`, `training/report.py`, and `training/tb_dump.py` cleanly from `training/`.

## Rules
- Work on `master` only; do not commit, push, or deploy unless explicitly asked.
- Retain `Scripts/` and `Source/PoRaceUnreal/` paths as documented in `AGENTS.md`.
