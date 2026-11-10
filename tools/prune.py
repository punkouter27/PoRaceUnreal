"""Artifact purge (proposals r3 E1; AGENTS.md cleanup rules). Dry run by default; --apply deletes.

  python tools/prune.py [--apply] [--keep-builds 2] [--log-days 7]

Candidates, each with its reason and size:
  training/runs/<run>   failed (no params.pkl and no checkpoint), or short (< 5,000 steps in its log / checkpoints),
                        unless it's referenced in rl_optimization_log.md / tasks.md / docs, was written in the last
                        24 h, or is named in training/queue*.txt (a queue will resume it).
  Build/<player>        all but the newest --keep-builds player folders (Build/PoRace, the shipped name, is always kept).
  Logs/*                files older than --log-days.
Never touches training/final, Assets/Policies or anything tracked by git. Prints the MB it reclaims (or would).
"""
import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400


def size(p):
  if p.is_file(): return p.stat().st_size
  return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def newest(p):
  ts = [p.stat().st_mtime] + [f.stat().st_mtime for f in p.rglob("*")] if p.is_dir() else [p.stat().st_mtime]
  return max(ts)


def tracked(p):
  r = subprocess.run(["git", "ls-files", "--error-unmatch", str(p.relative_to(ROOT))], cwd=ROOT, capture_output=True)
  return r.returncode == 0


def run_steps(run):
  steps = [int(d.name) for d in (run / "checkpoints").glob("*") if d.is_dir() and d.name.isdigit()] if (run / "checkpoints").is_dir() else []
  for log in list(run.glob("*.log")) + list(run.parent.glob(f"{run.name}.log")):
    try:
      for m in re.finditer(r"^\s*([\d,]+)\s+reward=", log.read_text(errors="ignore"), re.M):
        steps.append(int(m.group(1).replace(",", "")))
    except OSError:
      pass
  return max(steps) if steps else 0


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--apply", action="store_true"); ap.add_argument("--keep-builds", type=int, default=2)
  ap.add_argument("--log-days", type=float, default=7)
  a = ap.parse_args()
  now = time.time()
  refs = ""
  for f in [ROOT / "rl_optimization_log.md", ROOT / "tasks.md", *(ROOT / "docs").rglob("*.md")]:
    if f.exists(): refs += f.read_text(errors="ignore")
  queued = set()
  for q in (ROOT / "training").glob("queue*.txt"):
    queued |= {l.strip() for l in q.read_text().splitlines() if l.strip()}
  out = []   # (path, reason)

  runs = ROOT / "training" / "runs"
  for run in sorted(runs.iterdir()) if runs.is_dir() else []:
    if not run.is_dir(): continue
    name = run.name
    if now - newest(run) < DAY: continue                                  # written in the last 24 h
    if name in queued: continue
    if re.search(rf"\b{re.escape(name)}\b", refs): continue               # in the log / docs: history
    steps = run_steps(run)
    has_params = (run / "params.pkl").exists()
    if steps < 5000: out.append((run, f"short run ({steps} steps)"))
    elif not has_params and not (run / "checkpoints").is_dir(): out.append((run, "failed (no params, no checkpoints)"))

  builds = ROOT / "Build"
  if builds.is_dir():
    players = sorted([p for p in builds.iterdir() if p.is_dir() and p.name != "PoRace"], key=newest, reverse=True)
    for p in players[max(0, a.keep_builds - 1):]: out.append((p, "older player build"))

  logs = ROOT / "Logs"
  if logs.is_dir():
    for f in logs.rglob("*"):
      if f.is_file() and now - f.stat().st_mtime > a.log_days * DAY: out.append((f, f"log older than {a.log_days:g} days"))

  out = [(p, r) for p, r in out if not tracked(p)]
  total = 0
  for p, reason in out:
    s = size(p); total += s
    print(f"{'DELETE' if a.apply else 'would delete'}  {s / 1e6:9.1f} MB  {p.relative_to(ROOT)}  ({reason})")
    if a.apply:
      shutil.rmtree(p) if p.is_dir() else p.unlink()
  print(f"{'reclaimed' if a.apply else 'would reclaim'} {total / 1e6:.1f} MB in {len(out)} item(s)" + ("" if a.apply else "  (dry run: --apply to delete)"))


if __name__ == "__main__":
  sys.exit(main())
