"""Training runs grid: training/runs/runs.html, one row per real training run under training/runs/, newest first.

    python benchmark/runs.py                                   rebuild training/runs/runs.html from the run folders
    python benchmark/runs.py --record <run-id> --ended "<how>" [--launcher <script>] [--args "<train.py args>"]
                                                               note this machine and how the run ended, then rebuild

The grid is rebuilt from what training/train.py leaves in each run folder (training/runs/<run>/: ppo_params.json and
checkpoints/config.json written at the start, tags.json from preflight.py with restored_from, checkpoints/<step>/,
params.pkl at the end) and from training/launch.sh's filtered log beside it (training/runs/<run>.log: one
"<steps>  reward=...  <seconds>s" line per eval, then "exit <code>"), so a run started by hand, or one whose launcher
was killed, still gets a row. What the folder cannot tell (which machine, which commit, how the run ended, the exact
train.py arguments) comes from training/runs/<run>/run_meta.json, which --record writes on the Windows host after the
container exits (training/launch.sh, training/run.ps1). Without it those cells read "-".

Speed is the run's own: env steps per second (Brax counts steps summed over all parallel envs), measured between the
first and last eval line of this session's log (else the first and last checkpoint written this session), so a resumed
run is not credited with the steps of its earlier sessions. Benchmark is the newest benchmark/history.json result on
the same machine from before the run started (ms per Step and env steps/s), for comparison.
Stdlib only; core.py next to this file supplies the machine description.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import re
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESULTS = ROOT / "training" / "runs"
OUT = RESULTS / "runs.html"
BENCH = HERE / "history.json"
META = "run_meta.json"
TITLE = "PoRaceUnreal"
# the Benchmark's own throwaway logdir (runs/_benchmark) and its init copy (runs/_benchmark_init)
SKIP = ("_benchmark",)
EVAL_LINE = re.compile(r"^\s*(\d[\d,]*)\s+reward=\s*\S+\s+(\d+)s", re.M)  # train.py's progress() print


# ---------------------------------------------------------------- collect


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _arg(argv: list[str], name: str) -> str | None:
    for i, a in enumerate(argv):
        if a == f"--{name}" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(f"--{name}="):
            return a.split("=", 1)[1]
    return None


def _split(args: str) -> list[str]:
    try:
        return shlex.split(args)
    except ValueError:
        return args.split()


def _rate(points: list[tuple[float, float]]) -> float | None:
    """(steps, seconds) points of one session -> steps/s between the first and the last."""
    if len(points) < 2:
        return None
    (s0, t0), (s1, t1) = points[0], points[-1]
    return (s1 - s0) / (t1 - t0) if t1 > t0 and s1 > s0 else None


def _tb_points(d: Path, start: float) -> list[tuple[float, float]]:
    """(step, wall time) of eval/episode_reward from TensorBoard, only when the tensorboard package is importable."""
    try:
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    except ImportError:
        return []
    try:
        acc = EventAccumulator(str(d / "tb"), size_guidance={"scalars": 0})
        acc.Reload()
        events = acc.Scalars("eval/episode_reward")
    except Exception:  # noqa: BLE001 - a broken or missing event file just means no TensorBoard points
        return []
    return sorted((float(e.step), e.wall_time) for e in events if e.wall_time >= start - 1)


def _steps(d: Path, log: str, start: float, end: float) -> tuple[int | None, float | None]:
    """(env steps reached, env steps/s this session)."""
    points = [(float(s.replace(",", "")), float(t)) for s, t in EVAL_LINE.findall(log)]
    ckpts = []
    if (d / "checkpoints").is_dir():
        for c in (d / "checkpoints").iterdir():
            m = _mtime(c)
            if c.is_dir() and c.name.isdigit() and m is not None:
                ckpts.append((float(int(c.name)), m))
    ckpts.sort()
    tb = [] if points else _tb_points(d, start)
    reached = max((s for s, _ in points + ckpts + tb), default=None)
    session = sorted((s, t) for s, t in ckpts if start - 1 <= t <= end + 60)
    rate = _rate(points) or _rate(tb) or _rate(session)
    return (int(reached) if reached is not None else None), rate


def describe_exit(code: int, log: str = "") -> str:
    """How a run ended, in words, from the container's exit code (and the run's log for a crash)."""
    if code == 0:
        return "finished"
    if code == 130:
        return "stopped (Ctrl+C)"
    if code in (137, 143):
        return f"stopped (killed, exit {code})"
    if code == 125:
        return "crashed (docker run failed, exit 125)"
    why = [ln.strip() for ln in log.splitlines() if re.search(r"Error\b|PREFLIGHT FAIL|Traceback", ln)]
    last = why[-1][:120] if why and why[-1] != "Traceback (most recent call last):" else None
    return f"crashed (exit {code})" + (f": {last}" if last else "")


def _bench_for(host: str | None, before: float) -> dict | None:
    runs = [r for r in _json(BENCH).get("runs", []) if r.get("ok") and r.get("result")]
    if host:
        runs = [r for r in runs if r.get("machine", {}).get("hostname") == host]
    if not runs:
        return None
    stamp = lambda r: datetime.datetime.fromisoformat(r["when"]).timestamp()  # noqa: E731
    earlier = [r for r in runs if stamp(r) <= before]
    return (earlier or runs)[-1]


def _config(argv: list[str], args: str, tags: dict, ppo: dict) -> str | None:
    recipe = re.search(r"(\w+/launch\.sh)", args)
    env = _arg(argv, "env") or (recipe.group(1).split("/")[0] if recipe else None) or tags.get("creature")
    if not env and not ppo:
        return None
    parts = [" ".join([env or "?", *(f"--{f}" for f in ("pert", "cubes", "dr", "steeple") if f"--{f}" in argv)])]
    if recipe:
        parts.append(f"{recipe.group(1)} recipe")
    if ppo.get("learning_rate") is not None:
        parts.append(f"lr {float(ppo['learning_rate']):g}")
    if ppo.get("entropy_cost") is not None:
        parts.append(f"ent {float(ppo['entropy_cost']):g}")
    sets = sum(1 for a in argv if a == "--set" or a.startswith("--set="))
    if sets:
        parts.append(f"{sets} --set")
    return " · ".join(parts)


def collect() -> list[dict]:
    rows = []
    if not RESULTS.is_dir():
        return rows
    for d in RESULTS.iterdir():
        if not d.is_dir() or d.name.startswith(SKIP):
            continue
        meta = _json(d / META)
        starts = [m for m in (_mtime(d / "ppo_params.json"), _mtime(d / "checkpoints" / "config.json")) if m]
        if not starts and not meta:
            continue  # not a train.py logdir
        log = _text(RESULTS / f"{d.name}.log")  # training/launch.sh's log; overwritten each session
        recorded = datetime.datetime.fromisoformat(meta["recorded"]).timestamp() if meta.get("recorded") else None
        start = min(starts) if starts else (recorded or _mtime(d / META) or 0.0)
        ends = [_mtime(RESULTS / f"{d.name}.log"), _mtime(d / "params.pkl"), _mtime(d / "tags.json")]
        if (d / "checkpoints").is_dir():
            ends += [_mtime(c) for c in (d / "checkpoints").iterdir()]
        end = recorded or max([e for e in ends if e] + [start])
        steps, rate = _steps(d, log, start, end)
        tags, ppo = _json(d / "tags.json"), _json(d / "ppo_params.json")
        args = meta.get("args") or ""
        argv = _split(args)
        exits = re.findall(r"^exit (\d+)\s*$", log, re.M)
        ended = (
            meta.get("ended")
            or (describe_exit(int(exits[-1]), log) if exits else None)
            or ("finished" if (d / "params.pkl").exists() else "still running or killed")
        )
        restore = _arg(argv, "restore")
        logged_restore = re.findall(r"^restoring from (\S+)", log, re.M)
        warm = [w for w in (restore, _arg(argv, "restore_params") or tags.get("restored_from")) if w]
        if not restore and logged_restore:
            warm.insert(0, logged_restore[-1].split("/runs/", 1)[-1])
        bench = _bench_for(meta.get("host"), start)
        rows.append(
            dict(
                run=d.name,
                start=start,
                wall=max(0.0, end - start),
                ended=ended,
                resumed=bool(restore or logged_restore),
                target=ppo.get("num_timesteps"),
                steps=steps,
                rate=rate,
                bench=bench,
                config=_config(argv, args, tags, ppo),
                args=args,
                envs=_arg(argv, "num_envs") or ppo.get("num_envs"),
                warm=warm,
                commit=meta.get("commit"),
                host=meta.get("host"),
                gpu=meta.get("gpu"),
                device=meta.get("device"),
                launcher=meta.get("launcher"),
            )
        )
    rows.sort(key=lambda r: r["start"], reverse=True)
    return rows


# ---------------------------------------------------------------- render


def _dur(s: float) -> str:
    h, m = divmod(int(s) // 60, 60)
    return f"{h} h {m:02d} m" if h else f"{m} m"


def _num(n: float | None, digits: int = 0) -> str:
    return "-" if n is None else f"{n:,.{digits}f}"


def render(rows: list[dict]) -> str:
    e = html.escape
    body = []
    for r in rows:
        b = r["bench"]
        if b:
            notes = [f"{b['result']['env_steps_per_s']:,} env steps/s", e(b["when"][:10])]
            if datetime.datetime.fromisoformat(b["when"]).timestamp() > r["start"]:
                notes.append("taken after the run")
            if not r["host"]:
                notes.append("machine unknown")
            bench = f"{b['result']['step_time_ms']} ms<small>{' · '.join(notes)}</small>"
        else:
            bench = "-<small>no benchmark on this machine</small>"
        ended = e(r["ended"])
        cls = "bad" if re.search(r"crash|died|killed|HALT|error|exception", r["ended"], re.I) else ""
        target = f"of {_num(float(r['target']))}" if r["target"] else ""
        body.append(
            "<tr>"
            f"<td><b>{e(r['run'])}</b>{'<small>resumed</small>' if r['resumed'] else ''}</td>"
            f"<td>{datetime.datetime.fromtimestamp(r['start']).strftime('%Y-%m-%d %H:%M')}</td>"
            f'<td class="n">{_dur(r["wall"])}</td>'
            f'<td class="{cls}">{ended}</td>'
            f'<td class="n">{_num(r["steps"])}<small>{e(target)}</small></td>'
            f'<td class="n"><b>{_num(r["rate"])}</b><small>env steps/s</small></td>'
            f'<td class="n">{bench}</td>'
            f'<td title="{e(r["args"])}">{e(r["config"] or "-")}'
            f"<small>{e(r['launcher'] or '')}</small></td>"
            f'<td class="n">{e(str(r["envs"] or "-"))}</td>'
            f"<td>{e(', '.join(r['warm']) or 'cold')}</td>"
            f'<td class="mono">{e(r["commit"] or "-")}</td>'
            f"<td>{e(r['host'] or '-')}<small>{e(r['gpu'] or '')}{' · ' + e(r['device']) if r['device'] else ''}"
            f"</small></td>"
            "</tr>"
        )
    latest = rows[0] if rows else None
    prev = next((r for r in rows[1:] if r["rate"]), None) if rows else None
    delta = ""
    if latest and latest["rate"] and prev:
        pct = 100 * (latest["rate"] / prev["rate"] - 1)
        delta = f'<span class="{"up" if pct >= 0 else "down"}">{pct:+.0f}% vs {e(prev["run"])}</span>'
    summary = (
        f'<div class="sum"><div><span>Latest run</span><b>{e(latest["run"])}</b></div>'
        f"<div><span>Speed</span><b>{_num(latest['rate'])} env steps/s</b>{delta}</div>"
        f"<div><span>Wall-clock</span><b>{_dur(latest['wall'])}</b></div>"
        f"<div><span>Runs listed</span><b>{len(rows)}</b></div></div>"
        if latest
        else "<p>No training runs under training/runs/ yet.</p>"
    )
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(TITLE)} training runs</title>
<style>
:root{{--bg:#f5f7f6;--card:#fff;--ink:#18211f;--muted:#5d6b67;--line:#d8e0dd;--accent:#0f6b5c;--bad:#b42318;--up:#1f7a43}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1514;--card:#161e1c;--ink:#e2eae7;--muted:#91a19c;--line:#27332f;
--accent:#5cc9b0;--bad:#ff8a7a;--up:#5fcf8a;color-scheme:dark}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Segoe UI",system-ui,sans-serif;padding:24px 16px}}
h1{{font-size:20px;margin:0 0 4px}} p{{margin:0;color:var(--muted)}} .wrap{{max-width:1500px;margin:auto;display:grid;gap:16px}}
.sum{{display:flex;flex-wrap:wrap;gap:12px 40px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 18px}}
.sum span{{display:block;color:var(--muted);font-size:12px}} .sum b{{font-size:20px}} .sum .up,.sum .down{{display:block;font-size:12px}}
.up{{color:var(--up)}} .down{{color:var(--bad)}}
.t{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:nowrap}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);position:sticky;top:0;background:var(--card)}}
tr:last-child td{{border-bottom:0}} td.n{{text-align:right}} td small{{display:block;color:var(--muted);font-size:11px}}
td.bad{{color:var(--bad)}} .mono{{font-family:Consolas,monospace}}
</style></head><body><div class="wrap">
<div><h1>{e(TITLE)} training runs</h1><p>Every real training run under training/runs/, newest first. Rebuilt {now} by
benchmark/runs.py. Speed = env steps/s (summed over all parallel envs) of this session; Benchmark = the newest
benchmark.ps1 result on the same machine before the run (ms per Step, env steps/s).</p></div>
{summary}
<div class="t"><table><thead><tr><th>Run</th><th>Started</th><th>Wall-clock</th><th>Ended</th><th>Steps</th>
<th>Speed</th><th>Benchmark</th><th>Config</th><th>Envs</th><th>Warm start</th><th>Commit</th><th>Machine</th></tr></thead>
<tbody>{"".join(body)}</tbody></table></div></div></body></html>
"""


def build() -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(render(collect()), encoding="utf-8")
    os.replace(tmp, OUT)
    return OUT


def record(run_id: str, ended: str, launcher: str | None, args: str | None, device: str | None) -> None:
    """Write training/runs/<run>/run_meta.json: this machine, the commit, how the run ended and its train.py args.
    Run on the Windows host after the container exits, so the machine is the host's, not the container's."""
    sys.path.insert(0, str(HERE))
    import core

    m = core.machine()
    d = RESULTS / run_id
    d.mkdir(parents=True, exist_ok=True)
    code = re.fullmatch(r"exit (-?\d+)", ended.strip())
    if code:  # the launcher passes the container's exit code; put it in words (with the log's error for a crash)
        ended = describe_exit(int(code.group(1)), _text(RESULTS / f"{run_id}.log"))
    meta = dict(
        host=m["hostname"],
        gpu=m["gpu"],
        cpu=m["cpu"],
        device=device,
        commit=core.git_commit(),
        ended=ended,
        launcher=launcher,
        args=args,
        recorded=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    (d / META).write_text(json.dumps(meta, indent=1), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="Rebuild training/runs/runs.html (the training runs grid).")
    p.add_argument("--record", metavar="RUN_ID", help="note this machine and how the run ended first")
    p.add_argument("--ended", default="exited", help='how the run ended, in words, or "exit <code>"')
    p.add_argument("--launcher", help="the script that ran it")
    p.add_argument("--args", help="the train.py arguments (or the command run in the container)")
    p.add_argument("--device", help="e.g. CPU when the run had no GPU")
    a = p.parse_args()
    if a.record:
        record(a.record, a.ended, a.launcher, a.args, a.device)
    print(f"Training runs grid: {build()}")


if __name__ == "__main__":
    main()
