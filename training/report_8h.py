"""HTML report of the 8-hour training session (2026-11-09): Grandma's runs along her training lineage, the ladder
grades of each checkpoint against Matt's shipped m20, the PPO losses where logged, and the per-agent status.
Self-contained (inline SVG, light / dark, hover tooltips, a data table under every chart).

  python tb_dump.py runs/session8h_tb.json g1 g2 g3 g4 g5 g6 g7 ...       (trainer image: needs tensorboard)
  python report_8h.py --tb runs/session8h_tb.json --points ../docs/20261109/grandma_ladder_points.json \
      --status ../docs/20261109/agent_status.json --out ../docs/report/training_8h_20261109.html"""
import argparse, html, json, math
from pathlib import Path

LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]   # validated set (dataviz validator); never extend: a 9th run goes grey
DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
E = html.escape


def css():
  slots = "\n".join(f"  --s{i}: {c};" for i, c in enumerate(LIGHT))
  dslots = "\n".join(f"  --s{i}: {c};" for i, c in enumerate(DARK))
  dark = f"""  color-scheme: dark; --bg: #121211; --surface: #1a1a19; --text: #f0efec; --text2: #c3c2b7; --muted: #8f8e86;
  --grid: #2e2d2b; --axis: #57564f; --line: #2e2d2b; --good: #4cae55; --bad: #e66767;
{dslots}"""
  return f""":root {{
  color-scheme: light; --bg: #f4f4f2; --surface: #fcfcfb; --text: #0b0b0b; --text2: #52514e; --muted: #7a7974;
  --grid: #e6e5e0; --axis: #a3a29b; --line: #dedcd5; --good: #237a2c; --bad: #c13434;
{slots}
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
{dark} }} }}
:root[data-theme="dark"] {{
{dark} }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text); font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1080px; margin: 0 auto; padding: 28px 16px 64px; }}
h1 {{ font-size: 26px; margin: 0 0 4px; }} h2 {{ font-size: 19px; margin: 36px 0 6px; }} h3 {{ font-size: 15px; margin: 0 0 4px; }}
p.sub, .muted {{ color: var(--text2); }} p.sub {{ margin: 0 0 20px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }}
.card, .chart {{ background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 16px; }}
.card .big {{ font-size: 28px; font-weight: 650; margin: 2px 0; }}
.pill {{ display: inline-block; font-size: 12px; font-weight: 600; padding: 1px 8px; border-radius: 99px; border: 1px solid currentColor; }}
.pill.good {{ color: var(--good); }} .pill.bad {{ color: var(--bad); }} .pill.mid {{ color: var(--text2); }}
.chart {{ margin-top: 12px; }} .chart p.what {{ margin: 0 0 8px; color: var(--text2); font-size: 14px; }}
svg {{ width: 100%; height: auto; display: block; overflow: visible; }}
svg text {{ fill: var(--text2); font-size: 11px; }} svg .lbl {{ fill: var(--text); font-size: 12px; font-weight: 600; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 4px 0 6px; font-size: 13px; color: var(--text2); }}
.legend i {{ display: inline-block; width: 14px; height: 3px; border-radius: 2px; vertical-align: middle; margin-right: 6px; }}
.legend i.sq {{ height: 10px; width: 10px; border-radius: 3px; }}
details {{ margin-top: 8px; }} summary {{ cursor: pointer; color: var(--text2); font-size: 13px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 6px; }}
th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }} th {{ color: var(--text2); font-weight: 600; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.scroll {{ overflow-x: auto; }}
#tip {{ position: fixed; pointer-events: none; background: var(--text); color: var(--surface); font-size: 12px; padding: 5px 8px; border-radius: 6px; opacity: 0; transition: opacity .08s; max-width: 260px; z-index: 9; }}
.hit {{ fill: transparent; cursor: default; }}
ol.story li {{ margin: 4px 0; }}
"""


JS = """const tip = document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el => {
  el.addEventListener('mousemove', e => { tip.innerHTML = el.dataset.tip; tip.style.opacity = 1;
    const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8); tip.style.left = x + 'px'; tip.style.top = (e.clientY + 14) + 'px'; });
  el.addEventListener('mouseleave', () => tip.style.opacity = 0);
});"""


def nice_ticks(lo, hi, n=5):
  if hi <= lo: hi = lo + 1
  step = 10 ** math.floor(math.log10((hi - lo) / n)); err = (hi - lo) / n / step
  step *= 10 if err >= 7.5 else 5 if err >= 3.5 else 2 if err >= 1.5 else 1
  t = math.floor(lo / step) * step; out = []
  while t <= hi + 1e-9: out.append(round(t, 10)); t += step
  return out


def fmt(v):
  if not v: return "0"
  if abs(v) >= 100: return f"{v:,.0f}"
  if abs(v) >= 10: return f"{v:.1f}"
  if abs(v) >= 1: return f"{v:.2f}".rstrip("0").rstrip(".")
  return f"{v:.3g}"   # small values (losses): three significant digits, so neighbouring ticks never print alike


def line_chart(series, ylabel, xlabel="training steps along Grandma's lineage (millions)", ymin=None, ymax=None, ref=None):
  """series: [(name, slot, [(x, y)...])]. One y axis. Direct label at each line's end."""
  W, H, L, R, T, B = 900, 330, 56, 92, 14, 40
  xs = [x for _, _, p in series for x, _ in p]; ys = [y for _, _, p in series for _, y in p] + ([ref[1]] if ref else [])
  x0, x1 = 0, max(xs) if xs else 1
  y0 = min(ys) if ymin is None else ymin; y1 = max(ys) if ymax is None else ymax
  yt = nice_ticks(y0, y1); y0, y1 = min(y0, yt[0]), max(y1, yt[-1]); xt = nice_ticks(x0, x1, 8)
  X = lambda x: L + (x - x0) / (x1 - x0 or 1) * (W - L - R); Y = lambda y: T + (1 - (y - y0) / (y1 - y0 or 1)) * (H - T - B)
  o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{E(ylabel)}">']
  for t in yt:
    o.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="var(--grid)"/><text x="{L - 8}" y="{Y(t) + 4:.1f}" text-anchor="end">{fmt(t)}</text>')
  for t in xt:
    if t <= x1: o.append(f'<text x="{X(t):.1f}" y="{H - B + 18}" text-anchor="middle">{fmt(t)}</text>')
  o.append(f'<line x1="{L}" x2="{W - R}" y1="{H - B}" y2="{H - B}" stroke="var(--axis)"/>')
  o.append(f'<text x="{(L + W - R) / 2}" y="{H - 4}" text-anchor="middle">{E(xlabel)}</text>')
  if ref:
    o.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(ref[1]):.1f}" y2="{Y(ref[1]):.1f}" stroke="var(--text2)" stroke-dasharray="5 4"/>'
             f'<text x="{W - R + 6}" y="{Y(ref[1]) + 4:.1f}">{E(ref[0])}</text>')
  ends = []
  for name, slot, pts in series:
    if not pts: continue
    d = " ".join(f"{'M' if i == 0 else 'L'}{X(x):.1f},{Y(y):.1f}" for i, (x, y) in enumerate(pts))
    col = "var(--muted)" if slot is None else f"var(--s{slot})"   # None = a dead-end run: grey, dashed, direct-labelled
    dash = ' stroke-dasharray="5 4"' if slot is None else ""
    o.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"{dash}/>')
    for x, y in pts:
      o.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3" fill="{col}" stroke="var(--surface)" stroke-width="1.5"/>'
               f'<circle class="hit" cx="{X(x):.1f}" cy="{Y(y):.1f}" r="10" data-tip="<b>{E(name)}</b> @ {x:.1f}M<br>{E(ylabel)}: {fmt(y)}"/>')
    ends.append([Y(pts[-1][1]), X(pts[-1][0]), name, slot])
  ends.sort(); last = -99
  for e in ends:   # nudge end labels apart
    e[0] = max(e[0], last + 14); last = e[0]
    o.append(f'<text class="lbl" x="{e[1] + 7:.1f}" y="{e[0] + 4:.1f}">{E(e[2])}</text>')
  o.append("</svg>")
  return "".join(o)


def bar_chart(groups, keys, ylabel, log=False, ref=None, ymax=None):
  """groups: [(label, {key: value})]; keys: [(key, name, slot)]. Grouped bars, 2px gaps, rounded tops."""
  W, H, L, R, T, B = 900, 300, 56, 92, 14, 58
  vals = [g[k] for _, g in groups for k, _, _ in keys if g.get(k) is not None] + ([ref[1]] if ref else [])
  if log:
    lo, hi = 0.3, max(vals) * 1.3   # floor under the smallest real value (g10 final: 0.47 BW)
    yt = [v for v in (0.5, 1, 2, 5, 10, 20, 50, 100) if v <= hi * 1.01]
    Y = lambda v: T + (1 - (math.log10(max(v, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))) * (H - T - B)
  else:
    hi = ymax or max(vals); yt = nice_ticks(0, hi, 5); hi = max(hi, yt[-1])
    Y = lambda v: T + (1 - v / hi) * (H - T - B)
  base = H - B; gw = (W - L - R) / len(groups); bw = min(22, (gw - 16) / len(keys) - 2)
  o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{E(ylabel)}">']
  for t in yt:
    o.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="var(--grid)"/><text x="{L - 8}" y="{Y(t) + 4:.1f}" text-anchor="end">{fmt(t)}</text>')
  if ref:
    o.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(ref[1]):.1f}" y2="{Y(ref[1]):.1f}" stroke="var(--text2)" stroke-dasharray="5 4"/>'
             f'<text x="{W - R + 6}" y="{Y(ref[1]) + 4:.1f}">{E(ref[0])}</text>')
  for gi, (label, g) in enumerate(groups):
    cx = L + gw * (gi + 0.5); x = cx - (len(keys) * (bw + 2) - 2) / 2
    for k, name, slot in keys:
      v = g.get(k)
      if v is not None:
        y = Y(v); h = max(1.0, base - y); r = min(4, h / 2, bw / 2)
        o.append(f'<path d="M{x:.1f},{base} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} H{x + bw - r:.1f} Q{x + bw:.1f},{y:.1f} {x + bw:.1f},{y + r:.1f} V{base} Z" fill="var(--s{slot})"/>'
                 f'<rect class="hit" x="{x - 1:.1f}" y="{T}" width="{bw + 2:.1f}" height="{base - T:.1f}" data-tip="<b>{E(label)}</b><br>{E(name)}: {fmt(v)}"/>')
      x += bw + 2
    for li, part in enumerate(label.split("\n")):
      o.append(f'<text x="{cx:.1f}" y="{base + 16 + 13 * li}" text-anchor="middle">{E(part)}</text>')
  o.append(f'<line x1="{L}" x2="{W - R}" y1="{base}" y2="{base}" stroke="var(--axis)"/></svg>')
  return "".join(o)


def legend(items, square=False):
  def sw(s): return "background:var(--muted)" if s is None else f"background:var(--s{s})"
  return '<div class="legend">' + "".join(f'<span><i class="{"sq" if square else ""}" style="{sw(s)}"></i>{E(n)}</span>' for n, s in items) + "</div>"


def table(head, rows, num=()):
  h = "".join(f'<th class="{"num" if i in num else ""}">{E(c)}</th>' for i, c in enumerate(head))
  b = "".join("<tr>" + "".join(f'<td class="{"num" if i in num else ""}">{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
  return f'<div class="scroll"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def chart(title, what, body, data_table):
  return f'<div class="chart"><h3>{E(title)}</h3><p class="what">{what}</p>{body}<details><summary>Data table</summary>{data_table}</details></div>'


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--tb", required=True); ap.add_argument("--points", required=True); ap.add_argument("--status", required=True)
  ap.add_argument("--out", required=True)
  a = ap.parse_args()
  tb = json.loads(Path(a.tb).read_text()); pts = json.loads(Path(a.points).read_text()); st = json.loads(Path(a.status).read_text())
  lin = pts["lineage"]; runs = [r for r in lin if r in tb]
  dead = set(st.get("dead_ends", []))
  main_runs = [r for r in runs if r not in dead][-8:]   # the latest 8 main-lineage runs take the eight validated slots in order, never cycled
  slot = {r: (main_runs.index(r) if r in main_runs else None) for r in runs}
  def curve(run, tag, scale=1.0):
    return [(lin[run] + s / 1e6, v * scale) for s, v in tb[run].get(tag, [])]

  out = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
         f'<title>Overnight Training Report</title><style>{css()}</style></head><body><main>']
  out.append(f'<h1>{E(st["title"])}</h1><p class="sub">{E(st["subtitle"])}</p>')
  # agent status cards
  out.append('<div class="cards">')
  for c in st["agents"]:
    out.append(f'<div class="card"><h3>{E(c["name"])} <span class="pill {c["tone"]}">{E(c["state"])}</span></h3>'
               f'<div class="big">{E(c["headline"])}</div><div class="muted">{c["detail"]}</div></div>')
  out.append("</div>")
  out.append(f'<h2>What happened, in plain words</h2><ol class="story">' + "".join(f"<li>{s}</li>" for s in st["story"]) + "</ol>")

  # curves
  out.append("<h2>Training curves</h2><p class=\"muted\">Each colour is one training run. Runs that continued from an earlier "
             "checkpoint start where that checkpoint sits on the horizontal axis, so the axis is Grandma's total training. "
             "g1 and g2 were dead ends and start from zero.</p>")
  leg = legend([(f'{r} — {st["runs"].get(r, "")}', slot[r]) for r in main_runs] + [("dead ends and probes (grey, dashed): " + ", ".join(r for r in runs if slot[r] is None), None)])
  ser = [(r, slot[r], curve(r, "eval/avg_episode_length")) for r in runs]
  rows = [[r, f"{x:.1f}", f"{y:.0f}"] for r, _, p in ser for x, y in p]
  out.append(chart("How long Grandma stays up", "Average episode length in the evaluation, in control steps (1000 = she stayed up for the "
                   "whole 20-second episode). Higher is better, but beware: g2 scored high by <b>sitting</b> on the floor.",
                   leg + line_chart(ser, "episode length (steps)", ymin=0, ymax=1000), table(["run", "step (M)", "length"], rows, (1, 2))))
  ser = [(r, slot[r], curve(r, "eval/episode_reward")) for r in runs]
  rows = [[r, f"{x:.1f}", f"{y:.2f}"] for r, _, p in ser for x, y in p]
  out.append(chart("Evaluation reward (convergence)", "Total reward per evaluation episode. The reward recipe changed between runs (g4 and g5+ pay a larger "
                   "bonus for staying up), so compare the <b>shape within a run</b>, not heights across runs. g6 climbs from 13 to ~120.",
                   leg + line_chart(ser, "episode reward"), table(["run", "step (M)", "reward"], rows, (1, 2))))
  ser = [(r, slot[r], curve(r, "eval/episode_reward/tracking_lin_vel")) for r in runs]
  rows = [[r, f"{x:.1f}", f"{y:.0f}"] for r, _, p in ser for x, y in p]
  out.append(chart("Following the speed command", "Reward for matching the commanded walking speed, summed over an episode. It grows both with "
                   "better tracking and with longer episodes; the graduation test below is the strict check.",
                   leg + line_chart(ser, "speed-tracking reward", ymin=0), table(["run", "step (M)", "tracking"], rows, (1, 2))))
  losses = [(t, n) for t, n in (("episode/policy_loss", "policy loss"), ("episode/v_loss", "value loss"), ("episode/entropy_loss", "entropy loss"))]
  loss_runs = [r for r in runs if any(tb[r].get(t) for t, _ in losses)]
  if loss_runs:
    for t, n in losses:
      ser = [(r, slot[r], curve(r, t)) for r in loss_runs if tb[r].get(t)]
      if not ser: continue
      rows = [[r, f"{x:.1f}", f"{y:.4g}"] for r, _, p in ser for x, y in p]
      out.append(chart(f"PPO {n}", {"policy loss": "How much each update changes the policy (PPO surrogate). It hovers near zero; steady, not spiking, is healthy.",
                                    "value loss": "How wrong the critic's prediction of future reward is. Falling = the critic has learned the task's payoffs.",
                                    "entropy loss": "Negative policy entropy (exploration). Rising toward zero = the policy is getting more decisive."}[n],
                       legend([(r, slot[r]) for r, _, _ in ser]) + line_chart(ser, n), table(["run", "step (M)", n], rows, (1, 2))))
  else:
    out.append('<p class="muted">PPO losses: train.py logged evaluation metrics only until this session; loss logging was switched on from g7.</p>')

  # ladder grades
  P = pts["points"]; ref = pts["reference"]
  labels = [f'{p["run"]}\n@{p["step"]:.0f}M' for p in P] + ["Matt m20\n(shipped)"]
  # Bar charts show one checkpoint per run (its milestone if it has a note, else its last grade) so labels stay legible;
  # every graded checkpoint is in the data tables.
  pick = {}
  for i, p in enumerate(P):
    if p["run"] not in pick or p.get("note") or not P[pick[p["run"]]].get("note"): pick[p["run"]] = i
  sel = sorted(pick.values()) + [len(P)]
  def few(gs): return [gs[i] for i in sel]
  groups = [(l, {k: p.get(k) for k in ("stand", "push_stand", "push_walk")}) for l, p in zip(labels, P + [ref])]
  keys = [("stand", "stand 10 s", 0), ("push_stand", "push while standing", 1), ("push_walk", "push while walking", 2)]
  rows = [[l.replace("\n", " "), *(str(g[k]) for k, _, _ in keys)] for l, g in groups]
  out.append("<h2>Skill checks (the ladder)</h2><p class=\"muted\">Each graded checkpoint ran 10 trials of each test on the CPU simulator. "
             "Passing the toddler tier needs 10/10 standing and 9/10 on each push test. The dashed line marks the pass bar for the push tests.</p>")
  out.append(chart("Toddler tier: trials passed out of 10", "Standing still for 10 s, and staying up when shoved (30 N·s, the race's shove) while standing and while walking.",
                   legend([(n, s) for _, n, s in keys], True) + bar_chart(few(groups), keys, "passes (of 10)", ref=("pass bar 9", 9), ymax=10),
                   table(["checkpoint", *(n for _, n, _ in keys)], rows, (1, 2, 3))))
  fg = [(l, {"force": p.get("force") if p.get("force") else None}) for l, p in zip(labels, P + [ref])]
  rows = [[l.replace("\n", " "), fmt(g["force"]) if g["force"] is not None else "–"] for l, g in fg]
  out.append(chart("How hard her feet hit the ground", "99th-percentile foot force while standing, in body weights (log scale). A person standing "
                   "is ~1; g3 and g4 hammered the floor at 20–76×. From g5 on she lands like Matt. (g2 shows nothing: she was sitting.)",
                   bar_chart(few(fg), [("force", "foot force (body weights)", 1)], "foot force", log=True, ref=("Matt m20", ref["force"])),
                   table(["checkpoint", "foot force (BW)"], rows, (1,))))
  jg = [(l, {"jerk": p.get("jerk")}) for l, p in zip(labels, P + [ref])]
  rows = [[l.replace("\n", " "), f'{g["jerk"]:.3f}'] for l, g in jg]
  out.append(chart("Smoothness (jerk while standing)", "Lower is smoother. The stomping runs (g3, g4) were 30× jerkier than Matt; the action-rate "
                   "penalty added in g5 brought her to Matt's level.",
                   bar_chart(few(jg), [("jerk", "jerk", 6)], "jerk", ref=("Matt m20", ref["jerk"])), table(["checkpoint", "jerk"], rows, (1,))))

  gp = [(l, p) for l, p in zip(labels, P) if p.get("grad") is not None]
  if gp:
    gp_pass = [(l, {"grad": p["grad"]}) for l, p in gp] + [("Matt m20\n(shipped)", {"grad": 98}), ("Matt m25\n(jog test)", {"grad": 95})]   # measured on this same test (rl_optimization_log.md); the dog's gates are different tests
    pass_rows = [[l.replace("\n", " "), f'{g["grad"]}/100'] for l, g in gp_pass]
    out.append(chart("Race Graduation Progress (Episodes Passed out of 100)",
                     "100 episodes of randomized race speed and turn commands. An agent must pass <b>90/100</b> episodes (dashed line) with zero NaN gradients to export production ONNX weights. "
                     f"Grandma's best: <b>{max(p['grad'] for _, p in gp)}/100</b> ({max(gp, key=lambda lp: lp[1]['grad'])[0].replace(chr(10), ' ')}); 0/100 until g10.",
                     bar_chart(gp_pass, [("grad", "graduation passes (/100)", 2)], "passes (/100)", ref=("gate 90/100", 90), ymax=100),
                     table(["checkpoint / agent", "episodes passed (/100)"], pass_rows, (1,))))
    gg = [(l, {"grad_err": p["grad_err"]}) for l, p in gp] + [("Matt m20\n(shipped)", {"grad_err": 0.176}), ("Matt m25\n(jog test)", {"grad_err": 0.178})]
    rows = [[l.replace("\n", " "), f'{p["grad"]}/100', f'{p["grad_err"]:.3f}'] for l, p in gp] + [["Matt m20 (shipped)", "98/100", "0.176"], ["Matt m25 (jog test)", "95/100", "0.178"]]
    out.append(chart("Walking on command: velocity tracking error (m/s)", "100 episodes of race driving: start standing, then three 4-second speed / turn "
                     "commands from her race range (0.6–1.2 m/s). Bars are the mean velocity error (lower is better). "
                     f"Until g9 she stood still when told to walk (error ~0.92 m/s); the lowest since is {min(p['grad_err'] for _, p in gp):.3f} m/s.",
                     bar_chart(gg, [("grad_err", "mean velocity error (m/s)", 3)], "velocity error", ref=("Matt m20 (0.176)", 0.176)),
                     table(["checkpoint", "episodes passed", "mean error (m/s)"], rows, (1, 2))))

  out.append("<h2>Every run</h2>" + table(["run", "start", "recipe change", "result"], [[E(r["run"]), E(r["start"]), E(r["change"]), r["result"]] for r in st["table"]]))
  out.append("<h2>Glossary</h2><ul>" + "".join(f"<li><b>{E(k)}</b>: {v}</li>" for k, v in st["glossary"].items()) + "</ul>")
  out.append(f'<p class="muted">Generated by training/report_8h.py from TensorBoard logs (runs/*/tb) and docs/20261109/grandma_ladder_points.json. '
             f'Details per run: rl_optimization_log.md.</p></main><div id="tip"></div><script>{JS}</script></body></html>')
  Path(a.out).write_text("".join(out), encoding="utf-8")
  print("wrote", a.out)


if __name__ == "__main__":
  main()
