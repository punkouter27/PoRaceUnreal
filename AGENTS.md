# Agent guide — PoRaceUnreal

PoRaceUnreal is an Unreal / MuJoCo RL racing simulation. MuJoCo is the sole
physics authority; Unreal renders and presents the simulation. Read `docs/spec.md`,
`docs/PRD.md`, `docs/tasks/plan.md`, and the latest completed slice report in
`docs/` before making project changes.

## Repo map

| Path | What |
|---|---|
| `Source/PoRaceUnreal/` | Game module (C++): race director, racers, HUD (`RaceHUD*.cpp`), theme tokens (`UiTheme.h`) |
| `Plugins/UnrealRoboticsLab/` | URLab (MuJoCo in Unreal): NOT tracked (git-ignored, owner decision ca8af3d); `scripts/setup_urlab.ps1` clones upstream at a pinned commit, applies `Plugins/urlab_porace.patch` and builds its third-party libs |
| `training/` | Brax / mujoco_playground PPO trainer, contracts (`contract.py`), reward weights (`reward_config.json`) |
| `tests/` | pytest suite (`pytest` from the repo root) |
| `scripts/` | Unreal editor Python (`build_track.py`, ...), `regress.ps1`, `verify_all.ps1`, `setup_urlab.ps1` (clone + patch + build URLab, editor-Python packages) |
| `tools/` | Blender / Android / maintenance helpers |
| `web/` | Static showcase site, `/viewer` (brains run in the browser with onnxruntime-web on recorded races, Tab overlay, 30 s demo mode in `idle.js`) and `/diag`, built by `web/build.py`, deployed to `swa-poraceunreal` |
| `docs/` | Spec, PRD, plan / todo (`docs/tasks/`), slice reports, proposals |
| `Content/Project/` | Unreal assets (`/Game/Project/...`): `Agents/Racers`, `Environments/{Levels,Tracks,MuJoCoImports}`, `RL_Policies/Brains`, `DataAssets` (`DA_RaceRewardConfig`, `DA_RaceShowcaseConfig`, picked in `Config/DefaultGame.ini`). No `Core`/`UI` assets: the HUD and overlay are C++ Slate. `Content/Art/` holds raw source files (fbx/png/blend), not assets |

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
  (resource group `PoRaceUnreal`, secret `AZURE_STATIC_WEB_APPS_API_TOKEN`) and checks `/`, `/viewer` and `/diag` live.
- The workflow confirms the deploy by the `X-Commit` header on `/` (written by `web/build.py` into the Static Web App
  config) matching the pushed commit, plus `version.json`, `/` and `/diag`.
- The Unreal project is built and tested locally (GitHub's runners have no Unreal Engine). After a fresh clone run
  `scripts/setup_urlab.ps1` first (URLab is not tracked; see the repo map). v3 does not require vendoring, so this is
  not a deviation (owner decision ca8af3d).

## Coding standard

- C++ (`Source/PoRaceUnreal/`): Unreal conventions (tabs, `F`/`U`/`A` prefixes, `UPROPERTY` for anything a designer
  tunes). The game module builds with 0 warnings. Tunables go in DataAssets / `UDeveloperSettings`, never literals
  scattered through gameplay code. Chaos never simulates racers or track elements.
- Python: `ruff check` + `ruff format` clean (config in `pyproject.toml`, line length 120, py311). Tests are real
  pytest tests under `tests/` and never write into tracked files.
- Assets live under `/Game/Project/...` and are moved or renamed ONLY through the editor (AssetTools rename + fix up
  redirectors), never with git or the file system. URLab's importer always writes to `/Game/MuJoCoImports`: after a
  re-import (`scripts/build_track.py`) move the new meshes to `/Game/Project/Environments/MuJoCoImports` in the editor.
- Web (`web/`): plain HTML/CSS/JS, the Po tokens in `style.css`, text >= 4.5:1. Version stamp from `web/build.py` only.

### Deliberate deviations

| Deviation | Why | Commit sha / date | How to undo |
|---|---|---|---|
| URLab is git-ignored and rebuilt by `scripts/setup_urlab.ps1` (pinned upstream commit + `Plugins/urlab_porace.patch`). Not a deviation from v3: vendoring is not required | owner decision (2.3 GB clone) | `ca8af3d` (owner) 2026-11-21 | track the plugin again |
| Web `/diag` footer: sticky at the viewport bottom above 600 px (content scrolls under the 20 px strip); after the content on phones | owner layout kept on desktop; a fixed stamp covered content on phones | `fda29fc` 2026-11-22 | `git revert fda29fc` (stamp part) |
| `/diag`: a service switched off on purpose shows a neutral **Off**, not counted | not a fault | `fda29fc` 2026-11-22 | — |
| Gaze is render-only | the racers' MJCF has no neck joint; frozen contracts | `fda29fc` 2026-11-22 | owner decision |
| Shipped brains predate the torque² / joint angular velocity² (and humans' action-rate / foot-slip) penalties | not retrained (owner decision) | — | retrain through the gates |
| `Content/Art/` holds raw source files, not assets; no `Core`/`UI` assets (HUD is C++ Slate) | files, not cooked assets | `ffa6927` 2026-11-22 | — |
| Unreal is built and tested locally only; CI runs the Python checks and the showcase site | no Unreal Engine on GitHub runners | — | — |

**Hosting:** Azure Static Web App `swa-poraceunreal` (RG `PoRaceUnreal`), Free tier. Never run test suites against the live
site; live checks = at most 6 page loads + /diag + X-Commit.

## Concurrent work

- One game engine or headless browser at a time on this machine: never run two UnrealEditor / UnrealEditor-Cmd
  processes (they share `Intermediate/`, `Saved/` and DerivedDataCache) and close the editor before a command-line
  build (`Build.bat` waits on the UBT mutex with `-WaitMutex`).
- Other agents may be editing other Po repos: touch only this repo. Stage only the files you changed (`git add <paths>`),
  never `git add -A`; leave unrelated local work alone; fetch and rebase your own unpushed commits before pushing.

## Verify (exact commands)

One command sequence verifies the repo (after `scripts\setup_urlab.ps1` once per clone; close the editor first):

```powershell
ruff check . && ruff format --check . && python -m pytest && python web/build.py --check && powershell -File scripts\verify_all.ps1 -Unreal
```

Last full run (2026-11-23, 3 in a row): pytest 39 passed; build 0 warnings in `Source/PoRaceUnreal`; automation
PoRace.Showcase.IdleClock Success (D3D12); RaceUiTest 0 failures at 1280x720 and 540x1170; showcase capture at 1600x900
and 450x800; /viewer + /diag axe 0, `[policy]` console line, demo at 30.05 s; regress planar_sprint seed 1 rendered OK;
307 assets, 0 redirectors. The steps one by one:

```powershell
# Python (3.12 venv with the [dependency-groups] dev list from pyproject.toml)
ruff check .
ruff format --check .
python -m pytest                       # 39 tests: contract, models, physics rules, reward terms + per-term log, brains,
                                       # race, web build (viewer brains), web/idle.test.mjs via Node (node on PATH)
python web/build.py --check

# Unreal (Windows, UE 5.8 at C:\Program Files\Epic Games\UE_5.8)
powershell -File scripts\setup_urlab.ps1          # once per clone: URLab clone + patch + third-party build
& "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" PoRaceUnrealEditor Win64 Development `
    -Project="$PWD\PoRaceUnreal.uproject" -WaitMutex -NoHotReloadFromIDE     # 0 warnings in Source/PoRaceUnreal
# Rendered UI test at 16:9 and 9:16 (needs a display; never -nullrhi). Demo mode is off under -RaceUiTest.
& "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" "$PWD\PoRaceUnreal.uproject" -game -windowed `
    -ResX=1280 -ResY=720 -ForceRes -unattended -nosplash -nosound -RaceUiTest -AutoStart=1 -RaceLimit=4 -stdout -FullStdOutLogOutput
#   expect "RaceUiTest] done at the results card: 0 check failures"; repeat with -ResX=540 -ResY=1170
# Overlay, benchmark and idle demo (docs/showcase.md): writes overlay_on/off, demo_a/b PNGs, logs the benchmark
& "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" "$PWD\PoRaceUnreal.uproject" -game -windowed `
    -ResX=1600 -ResY=900 -ShowcaseCapture=<dir> -ShowcaseTouch -ShowcaseBench -DiagOverlay -unattended -nosplash -nosound
# Automation tests (PoRace.Showcase.IdleClock: 30 s idle, frames > 0.25 s ignored), rendered (never -nullrhi)
& "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" "$PWD\PoRaceUnreal.uproject" `
    -ExecCmds="Automation RunTests PoRace;Quit" -TestExit="Automation Test Queue Empty" -unattended -nosplash -nosound -windowed -ResX=1280 -ResY=720
# Everything incl. the parity and regression gates (Unreal rendered in small windows, never -nullrhi): scripts\verify_all.ps1 -Unreal
```

UI changes ("save before/after evidence under SCREENSHOTS/"): one command builds `web/dist` for this tree and for the
`-Before` ref (default `HEAD~1`, a temporary worktree) or takes `-BeforeDir` PNGs named `*_<route>_<W>x<H>.png`, shoots
`/`, `/diag.html`, `/viewer.html` locally at 1366x768 and 390x844 (headless Edge, never the live site) and writes the page:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\screenshots.ps1 -Feature <name> [-Before <ref> | -BeforeDir <dir>] [-Notes "..."]
# -> SCREENSHOTS/<yyMMdd>-<feature>.html + .png (side by side, annotated) + <yyMMdd>-<feature>/ (scaled shots)
```

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
