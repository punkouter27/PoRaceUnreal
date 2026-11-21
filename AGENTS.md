# Agent guide — PoRaceUnreal

PoRaceUnreal is an Unreal / MuJoCo RL racing simulation. MuJoCo is the sole
physics authority; Unreal renders and presents the simulation. Read `docs/spec.md`,
`docs/PRD.md`, `docs/tasks/plan.md`, and the latest completed slice report in
`docs/` before making project changes.

## Repo map

| Path | What |
|---|---|
| `Source/PoRaceUnreal/` | Game module (C++): race director, racers, HUD (`RaceHUD*.cpp`), theme tokens (`UiTheme.h`) |
| `Plugins/UnrealRoboticsLab/` | URLab (MuJoCo in Unreal), vendored at a pinned commit with this repo's patch applied |
| `training/` | Brax / mujoco_playground PPO trainer, contracts (`contract.py`), reward weights (`reward_config.json`) |
| `tests/` | pytest suite (`pytest` from the repo root) |
| `scripts/` | Unreal editor Python (`build_track.py`, ...), `regress.ps1`, `verify_all.ps1`, `setup_urlab.ps1` (editor-Python packages for the vendored URLab) |
| `tools/` | Blender / Android / maintenance helpers |
| `web/` | Static showcase site + `/diag`, built by `web/build.py`, deployed to `swa-poraceunreal` |
| `docs/` | Spec, PRD, plan / todo (`docs/tasks/`), slice reports, proposals |

## Project contracts

- Keep the Python reference race, Unreal runtime, and browser runtime aligned.
  `training/contract.py` is the source for generated contract files; regenerate
  and run its `--check` mode instead of editing generated values by hand (`RaceContract.gen.h`).
- Preserve the frozen physics, observation, action, joint-order, and checkpoint
  contracts. Changes to them require the corresponding parity and race gates in
  `docs/tasks/plan.md`; do not retrain, promote, or replace brains without those gates.
- Chaos must not simulate racers, track elements, or props (verified by `ARaceDirector::CheckChaos`).
  Use the existing MuJoCo / URLab pipeline and its model and contact audits.
- Reward penalty weights (torque², joint angular velocity², action rate, foot slip) and curriculum thresholds live in
  `training/reward_config.json`; the trainer reads them and the Unreal DataAsset mirrors them (a pytest checks parity).
  Shipped brains predate the file; changing a weight does not retrain them.
- Follow the approved slice order and stop at any failed gate. Do not imply unverified features are complete.
- Seeds: `-Seed=<n>` CLI parameter / `?Seed=<n>` URL option seeds `FRaceRules::Seed`.

## Workflow

- Work on `master`; preserve existing local work. Do not commit, push, or deploy
  unless explicitly requested.
- Keep training and generated artifacts out of unrelated changes. Do not prune
  checkpoints or run folders unless the project's cleanup procedure permits it.
- Checks before a push: `ruff check .`, `ruff format --check .`, `pytest` (repo root), the Unreal editor target
  build, and `python web/build.py`. Report skipped engine, device, visual, or long-running gates explicitly.
- For UI changes, keep the HUD anchors and bottom-docked, non-overlapping panels; save before/after
  evidence under `SCREENSHOTS/`.

## CI/CD and Azure

- `.github/workflows/deploy.yml` (the only workflow): on push to `master` it runs the Python checks (ruff, pytest),
  builds the showcase site (`web/build.py`), deploys it to the Azure Static Web App `swa-poraceunreal`
  (resource group `PoShared`, secret `AZURE_STATIC_WEB_APPS_API_TOKEN`) and checks `/` and `/diag` live.
- The Unreal project is built and tested locally (GitHub's runners have no Unreal Engine). It compiles from a fresh
  clone because URLab is vendored in `Plugins/`.

## Po Game Standard (Unity / Unreal RL games)

This repo is one of several independent Po games. It follows the conventions below, but it owns every file:
nothing is generated from, synced with, or required to stay identical to another repository (no "same file in
every game" headers, no sync scripts that copy into other repos). Third-party code it needs (ML-Agents, MuJoCo
plugins, URLab) is vendored INSIDE this repo at a pinned version. Azure resources may be shared through `PoShared`.

### Repo skeleton
```
README.md   AGENTS.md (this standard + repo notes)   CLAUDE.md ("Read AGENTS.md.")
docs/       lowercase, all prose (no DOCS/, no root DESIGN.md/SPEC.md/tasks.md — move them into docs/)
scripts/    build/publish/helper scripts (Unity: Tools/ is renamed scripts/ unless Unity itself needs it)
.github/workflows/<one file>.yml   the ONLY workflow
pyproject.toml with a [tool.ruff] section for any Python in the repo
```
No absolute local paths (C:\Users\...) committed anywhere. No build outputs or node_modules tracked.

### Web page around the game (WebGL template / web viewer)
- The page chrome is drawn ONCE, by the HTML page, OUTSIDE the game canvas, so it can never overlap the HUD:
  a 44px top bar (game name top-left, settings gear / fullscreen top-right) and the version `vYYMMDD` bottom-right
  in the bar's counterpart or a 20px footer strip. The canvas fills the remaining viewport.
- The in-game HUD does NOT repeat the game name or version (it may show them inside menus, not as corner chrome).
- Same tokens as the web apps: dark background `#0b0f17`, surface `#121826`, text `#e6e9f2`, muted `#9aa3b5`,
  accent `#6366f1`, Inter/system-ui font. Text ≥ 4.5:1 contrast.

### Orientation (C11)
The canvas fills any viewport (no fixed portrait aspect, no pillarboxing). UI is anchored and DPI-scaled
(Unity: CanvasScaler "Scale With Screen Size" or UI Toolkit PanelSettings scale-with-screen; Unreal: UMG anchors +
DPI curve). Must be checked at 1600x900 (landscape) and 450x800 (portrait) — screenshots in the PR/commit notes.

### Version
One stamp, UTC `yyMMdd`, computed once by the publish/build script and injected into: index.html, diag.html,
and the player (`PlayerSettings.bundleVersion` / Unreal ProjectVersion) so `Application.version` matches the page.

### /diag (games)
`/diag` (static `diag.html` generated by the publish script) titled **System status**, same layout as the web apps:
overall banner, then **API / Data / Services** sections. It must LIVE-probe (fetch from the browser, with latency)
every external dependency the game really calls (leaderboard tables/functions, weather APIs, AI APIs, replay bundles,
model files), plus the WebGL2 capability and that the build bundle files exist. Nothing hard-coded as "Ready".
The checks are listed in the repo's own config (e.g. `scripts/webgl.json` → `diagChecks`).

### In-game diagnostics overlay (C12)
`Tab` (and a 44px corner button on touch devices) toggles an overlay showing: FPS, current episode reward,
inference latency (ms, rolling average), curriculum stage. Readable text (≥ 4.5:1 on an opaque panel).

### Demo mode (C13)
After 30 s with no input (keyboard, mouse, touch, gamepad) from load or from last input: hide non-essential HUD,
all agents are driven by the trained policy (inference only), showcase cameras cycle (~6–8 s each); any input
returns control and the HUD. Idle threshold, camera list and dwell time are editor-tunable assets.

### Rewards + editor-first config (C9, C10)
Reward includes penalties for joint torque², joint angular velocity², action rate ‖a_t − a_{t−1}‖², and foot sliding
(foot planar speed while in contact), each with its own weight. Reward weights, curriculum thresholds, cameras and UI
references live in ScriptableObjects / `[SerializeField]` (Unity) or DataAssets / `UPROPERTY(EditAnywhere,
BlueprintReadWrite)` (Unreal); Python trainers read the same values from the repo's training config. Changing a
penalty does not retrain shipped policies — note this in docs when shipped models predate the change.

### Workflow
- Unity: the WebGL player is built locally with the EXACT pinned editor (Unity cannot be licensed in CI) by
  `scripts/publish_webgl.ps1`, which runs EditMode tests first, then builds, zips and publishes a `webgl-*` release.
  The one workflow: on release → deploy to the game's Static Web App → check the live page AND /diag; on push →
  Python checks (`ruff check`, `ruff format --check`, `pytest`) only.
- Unreal: the one workflow builds and deploys the repo's web front (viewer / showcase + /diag) to its Static Web App,
  after Python checks. The Unreal project must compile from a fresh clone (all plugins vendored in `Plugins/`).

### Tests
Python: real pytest tests (collected by pytest, not ad-hoc scripts), ruff clean. Unity: EditMode tests pass before
every publish. Tests never write into tracked files.
