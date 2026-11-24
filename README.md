# PoRaceUnreal

An Unreal / MuJoCo RL racing simulation: MuJoCo is the only physics, Unreal renders and presents the race, and a static
showcase site (`web/`: `/viewer` runs the brains in the browser with onnxruntime-web, plus `/diag`) is deployed to an
Azure Static Web App. Agents and contributors: read [`AGENTS.md`](AGENTS.md) (standard, repo map, exact verify commands).

- Verify everything: `powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1 -Unreal` (AGENTS.md, "Verify").
- Docs: [`docs/`](docs/) (spec, PRD, plan, slice reports).
- UI changes: before/after pages in [`SCREENSHOTS/`](SCREENSHOTS/), made with one command that shoots the local
  `web/dist` build at 1366x768 and 390x844 (never the live site):
  `powershell -ExecutionPolicy Bypass -File scripts\screenshots.ps1 -Feature <name> [-Before <git ref> | -BeforeDir <PNGs>]`
  -> `SCREENSHOTS/<yyMMdd>-<feature>.html` + `.png` (side by side) + `<yyMMdd>-<feature>/`.
