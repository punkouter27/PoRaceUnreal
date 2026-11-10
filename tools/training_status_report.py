"""Agent training status report, for deciding what to train next. Plain words, annotated charts, one HTML file.

    python tools/training_status_report.py [--out docs/report/training_status_20261110.html]

Sources (all in the repo):
  docs/report/tb_final.json             TensorBoard scalars of the Go2 runs (training/tb_dump.py export)
  docs/20261109/grandma_ladder_points.json  Grandma checkpoints graded on the skill ladder
  docs/rl_optimization_log.md           graduation scores of Matt's runs and the Go2 specialist runs (copied below)
Matt's and Grandma's raw TensorBoard logs stayed on the training PC (training/runs is not in the repo), so their progress
is shown with their test scores, which is what decides whether a brain ships anyway.
"""
import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- data that lives only in the training log (docs/rl_optimization_log.md) -----------------------------------------
MATT_RUNS = [  # run, graduation score /100, note
  ("m14", 49, "first run through the child tier"), ("m15", 51, "plateau"), ("m16", 83, "turning fixed"), ("m17", 83, "plateau"),
  ("m18", 97, "first pass, but wobbly standing"), ("m19", 92, "steady standing, limp on the limit"), ("m20", 98, "SHIPPED: passes every test"),
  ("m21", 96, "same level"), ("m22", 99, "jog training: jog still falls"), ("m23", 89, "jog: worse"), ("m25", 95, "new stride clock: still no jog"),
]
STEEPLE = [("s2", 82.0), ("s4", 86.0), ("s5", 88.3), ("s6", 91.0), ("s7", 92.3)]   # hurdle course pass rate %, best checkpoint
SPRINT = [("r8", 0), ("r9", 0), ("r10", 0), ("r11", 2), ("r12", 8), ("r13", 10)]     # sprint test passes /10

# skill matrix: (skill, plain description) x agent -> (state, short text). States: pass / partial / fail / none
SKILLS = [
  ("Stand steady", "holds still for 10 s"),
  ("Shrug off a push", "a hard shove, standing and walking"),
  ("Walk / run on command", "follows the race speed it is told"),
  ("Turn on command", "steers round bends"),
  ("Get up after a fall", "stands itself back up"),
  ("Sprint / jog", "2.5 m/s and faster"),
  ("Banked turns", "sloped curves"),
  ("Hurdles", "steeplechase obstacles"),
  ("Works in Unreal", "moves exactly as in training"),
]
AGENTS = [
  {"name": "Blue", "kind": "robot dog (Go2)", "slot": 1, "level": "Expert", "tone": "good",
   "line": "Six brains, every skill test passed, races identical in Unreal.",
   "steps": "about 1 billion training steps across its brains",
   "skills": [("pass", "10/10"), ("pass", "30/30"), ("pass", "10/10 at 1.5 m/s"), ("pass", "yes"), ("pass", "30/30"),
              ("partial", "brain ready (2.36 m/s), not used in races yet"), ("pass", "30/30"), ("pass", "92 % of courses"), ("pass", "exact")]},
  {"name": "Matt", "kind": "human", "slot": 2, "level": "Racer", "tone": "good",
   "line": "Walks every race and passes the race test 98/100. Cannot jog, climb or get up.",
   "steps": "about 1.5 billion steps over 25 runs",
   "skills": [("pass", "10/10"), ("pass", "10/10"), ("partial", "98/100, but holds ~92 % of the asked speed"), ("pass", "10/10"),
              ("none", "not trained: lies still, reset after 5 s"), ("fail", "0/10: falls"), ("none", "flat tracks only"), ("none", "flat tracks only"),
              ("pass", "exact")]},
  {"name": "Grandma", "kind": "human", "slot": 3, "level": "Trained, not in the game", "tone": "warning",
   "line": "Passed her race test (94/100) but walks with a limp, and nobody has checked her in Unreal yet.",
   "steps": "about 690 million steps over 14 runs",
   "skills": [("pass", "10/10"), ("pass", "10/10"), ("partial", "94/100; limps (lopsided skeleton)"), ("none", "not tested"),
              ("none", "not trained"), ("none", "not trained"), ("none", "flat only"), ("none", "flat only"), ("fail", "not checked yet")]},
  {"name": "G1", "kind": "humanoid robot", "slot": 0, "level": "Not started", "tone": "critical",
   "line": "Body built, no brain. Waiting on a decision about its collision shapes.",
   "steps": "no training yet",
   "skills": [("none", "-")] * 9},
]
NEXT = [  # priority, job, what you get, GPU time, people time, confidence, why
  (1, "Bring Grandma into the game", "A third racer on the menu; the yellow flag can finally happen", "none",
   "half a day (MuJoCo 4 check, Unreal match, race tests)", "high",
   "Her brain already passed. The risk is only that the limp looks odd or trips her in the race tests."),
  (2, "Blue at Matt's physics setting", "Fairer mixed races: Blue is 9/10 instead of 10/10 on standing starts when Matt races", "1-2 h",
   "half a day (re-run every Blue check)", "high",
   "A short fine-tune from the shipped brain. Touches the most-checked racer, so all its gates re-run."),
  (3, "Fix Grandma's limp", "She walks evenly (her scanned skeleton has one leg 1.6 cm shorter)", "1-3 h",
   "a day (fix the skeleton, retrain, re-test)", "medium",
   "Skeleton fix first; then fine-tune from g14. From scratch would be a full night."),
  (4, "Teach Matt to jog", "Matt keeps up with Blue; sprint races", "3-5 h (2-4 runs)", "a day", "low-medium",
   "Two tries failed for the same reason: no 'both feet off the ground' phase. Needs a new reward."),
  (5, "Get-up for the humans", "Matt and Grandma stand back up instead of a 5 s reset", "a night (8 h+)", "1-2 days", "low",
   "A new skill from scratch; the dog's get-up took one run, humans are much harder."),
  (6, "Start G1", "A fourth racer", "1-2 nights", "2-3 days + a design decision", "low",
   "Needs your call on its collision shapes first; then a from-scratch run like Grandma's (about 690 M steps)."),
]

SLOT = {1: "--s1", 2: "--s2", 3: "--s3"}
STATE_ICON = {"pass": ("✓", "--good", "Passed"), "partial": ("◐", "--warn", "Partly"), "fail": ("✗", "--bad", "Failed"),
              "none": ("–", "--muted", "Not trained")}


def esc(s):
  return html.escape(str(s))


# --- small SVG chart kit ---------------------------------------------------------------------------------------------
class Chart:
  """A line/dot chart in one SVG: one x and one y axis, recessive grid, annotated points, hover tooltips."""

  def __init__(self, w, h, x0, x1, y0, y1, xlab, ylab, xfmt=lambda v: f"{v:g}", yfmt=lambda v: f"{v:g}", xticks=None, yticks=None):
    self.w, self.h = w, h
    self.l, self.r, self.t, self.b = 60, 72, 18, 46   # right margin: room for the direct label
    self.x0, self.x1, self.y0, self.y1 = x0, x1, y0, y1
    self.parts = []
    self.xlab, self.ylab, self.xfmt, self.yfmt = xlab, ylab, xfmt, yfmt
    self.xticks, self.yticks = xticks, yticks

  def X(self, v):
    return self.l + (v - self.x0) / (self.x1 - self.x0) * (self.w - self.l - self.r)

  def Y(self, v):
    return self.h - self.b - (v - self.y0) / (self.y1 - self.y0) * (self.h - self.t - self.b)

  def axes(self):
    p = []
    for v in self.yticks:
      y = self.Y(v)
      p.append(f'<line class="grid" x1="{self.l}" x2="{self.w - self.r}" y1="{y:.1f}" y2="{y:.1f}"/>')
      p.append(f'<text class="tick" x="{self.l - 8}" y="{y + 4:.1f}" text-anchor="end">{esc(self.yfmt(v))}</text>')
    for v in self.xticks:
      x = self.X(v)
      p.append(f'<text class="tick" x="{x:.1f}" y="{self.h - self.b + 18}" text-anchor="middle">{esc(self.xfmt(v))}</text>')
    p.append(f'<line class="axis" x1="{self.l}" x2="{self.w - self.r}" y1="{self.Y(self.y0):.1f}" y2="{self.Y(self.y0):.1f}"/>')
    p.append(f'<text class="axlab" x="{(self.l + self.w - self.r) / 2:.1f}" y="{self.h - 6}" text-anchor="middle">{esc(self.xlab)}</text>')
    p.append(f'<text class="axlab" x="14" y="{(self.t + self.h - self.b) / 2:.1f}" text-anchor="middle" transform="rotate(-90 14 {(self.t + self.h - self.b) / 2:.1f})">{esc(self.ylab)}</text>')
    return p

  def line(self, pts, var, label=None, tip=lambda x, y: ""):
    d = " ".join(f"{'M' if i == 0 else 'L'}{self.X(x):.1f},{self.Y(y):.1f}" for i, (x, y) in enumerate(pts))
    self.parts.append(f'<path d="{d}" fill="none" stroke="var({var})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
    for x, y in pts:
      self.dot(x, y, var, tip(x, y), r=4)
    if label:
      x, y = pts[-1]
      self.parts.append(f'<text class="dlabel" x="{self.X(x) + 8:.1f}" y="{self.Y(y) + 4:.1f}">{esc(label)}</text>')

  def dot(self, x, y, var, tip, r=4.5):
    self.parts.append(f'<circle cx="{self.X(x):.1f}" cy="{self.Y(y):.1f}" r="{r}" fill="var({var})" stroke="var(--surface)" stroke-width="2"/>'
                      f'<circle class="hit" cx="{self.X(x):.1f}" cy="{self.Y(y):.1f}" r="12" data-tip="{esc(tip)}"/>')

  def hline(self, v, text):
    y = self.Y(v)
    self.parts.append(f'<line class="goal" x1="{self.l}" x2="{self.w - self.r}" y1="{y:.1f}" y2="{y:.1f}"/>'
                      f'<text class="goaltext" x="{self.l + 6}" y="{y - 6:.1f}" text-anchor="start">{esc(text)}</text>')

  def note(self, x, y, text, dx=0, dy=-34, anchor="middle"):
    """An annotation: a leader line from the point to a short label."""
    px, py = self.X(x), self.Y(y)
    tx, ty = px + dx, py + dy
    self.parts.append(f'<line class="leader" x1="{px:.1f}" y1="{py:.1f}" x2="{tx:.1f}" y2="{ty + 4:.1f}"/>'
                      f'<text class="note" x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}">{esc(text)}</text>')

  def svg(self, title):
    body = "".join(self.axes() + self.parts)
    return f'<svg viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>{body}</svg>'


def go2_curves():
  tb = json.loads((ROOT / "docs/report/tb_final.json").read_text())
  out = {}
  for tag in ("eval/episode_reward", "eval/avg_episode_length", "eval/episode_reward/tracking_lin_vel"):
    r1 = [(s / 1e6, v) for s, v in tb["r1"][tag][:2]]                      # 0 -> 23 M, then resumed as r1b
    r1b = [(r1[-1][0] + s / 1e6, v) for s, v in tb["r1b"][tag]]
    out[tag] = r1 + r1b[1:]
  return out


def table(headers, rows):
  h = "".join(f"<th>{esc(x)}</th>" for x in headers)
  b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
  return f'<div class="scroll"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--out", type=Path, default=ROOT / "docs/report/training_status_20261110.html")
  a = ap.parse_args()

  # 1. the three TensorBoard metrics, Blue's flat-ground brain (the one every race uses)
  c = go2_curves()
  rew, ln, trk = c["eval/episode_reward"], c["eval/avg_episode_length"], c["eval/episode_reward/tracking_lin_vel"]
  xt = [0, 50, 100, 150, 200]
  ch1 = Chart(520, 280, 0, 230, 0, 30, "training so far (millions of practice steps)", "score", xticks=xt, yticks=[0, 10, 20, 30])
  ch1.line(rew, "--s1", "Blue", lambda x, y: f"{x:.0f} M steps: score {y:.1f}")
  ch1.note(rew[1][0], rew[1][1], "learned to stand and walk", dx=30, dy=60, anchor="start")
  ch1.note(rew[-1][0], rew[-1][1], "levelled off: done", dx=-20, dy=60, anchor="end")
  ch2 = Chart(520, 280, 0, 230, 0, 1000, "training so far (millions of practice steps)", "seconds without falling", xticks=xt,
              yticks=[0, 250, 500, 750, 1000], yfmt=lambda v: f"{v / 50:.0f} s")
  ch2.hline(1000, "the whole 20 s test")
  ch2.line(ln, "--s1", "Blue", lambda x, y: f"{x:.0f} M steps: stays up {y / 50:.1f} of 20 s")
  ch2.note(0, ln[0][1], "falls after 7 s", dx=40, dy=30, anchor="start")
  ymax = max(v for _, v in trk) * 1.1
  ch3 = Chart(520, 280, 0, 230, 0, ymax, "training so far (millions of practice steps)", "speed-following points",
              xticks=xt, yticks=[0, 200, 400, 600, 800], yfmt=lambda v: f"{v:.0f}")
  ch3.line(trk, "--s1", "Blue", lambda x, y: f"{x:.0f} M steps: {y:.0f} points")
  ch3.note(trk[1][0], trk[1][1], "walks, but not at the asked speed", dx=30, dy=40, anchor="start")
  ch3.note(trk[-1][0], trk[-1][1], "matches the asked speed", dx=-20, dy=60, anchor="end")

  # 2. the humans: the race test score, run by run
  ch4 = Chart(520, 300, -0.5, len(MATT_RUNS) - 0.5, 0, 100, "Matt's training runs, in order", "race test score (of 100)",
              xticks=list(range(len(MATT_RUNS))), yticks=[0, 25, 50, 75, 100], xfmt=lambda v: MATT_RUNS[int(v)][0])
  ch4.hline(90, "pass mark 90")
  ch4.line([(i, s) for i, (_, s, _) in enumerate(MATT_RUNS)], "--s2", "Matt", lambda x, y: f"{MATT_RUNS[int(x)][0]}: {y:.0f}/100, {MATT_RUNS[int(x)][2]}")
  i20 = [r[0] for r in MATT_RUNS].index("m20")
  ch4.note(i20, 98, "m20 shipped (98)", dx=0, dy=110)
  ch4.note(2, 83, "turning fixed", dx=10, dy=60, anchor="start")
  ch4.note(9, 89, "jog tries: no jog", dx=0, dy=60, anchor="middle")

  pts = json.loads((ROOT / "docs/20261109/grandma_ladder_points.json").read_text())
  lin = pts["lineage"]
  gp = sorted([(lin[p["run"]] + p["step"], p["grad"], p["run"]) for p in pts["points"] if p.get("grad") is not None], key=lambda t: t[0])
  ch5 = Chart(520, 300, 200, 660, 0, 100, "Grandma's training so far (millions of practice steps)", "race test score (of 100)",
              xticks=[200, 300, 400, 500, 600], yticks=[0, 25, 50, 75, 100])
  ch5.hline(90, "pass mark 90")
  ch5.line([(x, y) for x, y, _ in gp], "--s3", "Grandma", lambda x, y: f"{x:.0f} M steps: {y:.0f}/100")
  ch5.note(gp[0][0], gp[0][1], "stood, but would not walk", dx=10, dy=-40, anchor="start")
  ch5.note(gp[-1][0], gp[-1][1], "g14 passed (94)", dx=-30, dy=90, anchor="end")
  ch5.note(387.4, 2, "first passes, falls standing", dx=-10, dy=-70, anchor="end")

  # 3. Blue's specialist skills
  ch6 = Chart(520, 280, -0.5, len(STEEPLE) - 0.5, 70, 100, "hurdle-course runs", "courses finished (%)",
              xticks=list(range(len(STEEPLE))), yticks=[70, 80, 90, 100], xfmt=lambda v: STEEPLE[int(v)][0])
  ch6.hline(90, "pass 90 %")
  ch6.line([(i, v) for i, (_, v) in enumerate(STEEPLE)], "--s1", None, lambda x, y: f"{STEEPLE[int(x)][0]}: {y:.0f} %")
  ch6.note(len(STEEPLE) - 1, STEEPLE[-1][1], "s7 shipped", dx=-30, dy=50, anchor="end")
  ch7 = Chart(520, 280, -0.5, len(SPRINT) - 0.5, 0, 10, "sprint runs", "sprint tests passed (of 10)",
              xticks=list(range(len(SPRINT))), yticks=[0, 5, 10], xfmt=lambda v: SPRINT[int(v)][0])
  ch7.hline(9, "pass 9")
  ch7.line([(i, v) for i, (_, v) in enumerate(SPRINT)], "--s1", None, lambda x, y: f"{SPRINT[int(x)][0]}: {y:.0f}/10")
  ch7.note(3, 2, "lighter effort penalty", dx=-10, dy=-60, anchor="end")

  # skill matrix
  head = "".join(f'<th><span class="sw" style="background:var({SLOT.get(ag["slot"], "--muted")})"></span>{esc(ag["name"])}</th>' for ag in AGENTS)
  rows = []
  for k, (skill, desc) in enumerate(SKILLS):
    cells = []
    for ag in AGENTS:
      st, txt = ag["skills"][k]
      icon, var, word = STATE_ICON[st]
      cells.append(f'<td class="cell"><span class="st" style="color:var({var})" aria-label="{word}">{icon}</span> <b>{word}</b><br><span class="sub">{esc(txt)}</span></td>')
    rows.append(f'<tr><th class="rowh">{esc(skill)}<br><span class="sub">{esc(desc)}</span></th>{"".join(cells)}</tr>')
  matrix = f'<div class="scroll"><table class="matrix"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'

  def level_bar(ag):
    passed = sum(1.0 if s == "pass" else 0.5 if s == "partial" else 0.0 for s, _ in ag["skills"])
    pct = passed / len(SKILLS) * 100
    var = SLOT.get(ag["slot"], "--muted")
    return pct, (f'<div class="bar" role="img" aria-label="{pct:.0f} % of skills"><div style="width:{pct:.0f}%;background:var({var})"></div></div>'
                 f'<div class="sub">{passed:g} of {len(SKILLS)} skills ({pct:.0f} %)</div>')

  tone_icon = {"good": "✓", "warning": "!", "critical": "✗"}
  cards = []
  for ag in AGENTS:
    _, bar = level_bar(ag)
    tv = {"good": "--good", "warning": "--warn", "critical": "--bad"}[ag["tone"]]
    cards.append(f'<div class="card"><div class="cardhead"><span class="sw big" style="background:var({SLOT.get(ag["slot"], "--muted")})"></span>'
                 f'<div><div class="name">{esc(ag["name"])}</div><div class="sub">{esc(ag["kind"])}</div></div></div>'
                 f'<div class="level"><span class="badge" style="border-color:var({tv})"><span style="color:var({tv})">{tone_icon[ag["tone"]]}</span> {esc(ag["level"])}</span></div>'
                 f'{bar}<p>{esc(ag["line"])}</p><div class="sub">{esc(ag["steps"])}</div></div>')

  nxt = table(["#", "Train next", "What you get", "GPU time", "Your/my time", "Odds it works", "Notes"],
              [(str(p), f"<b>{esc(j)}</b>", esc(w), esc(g), esc(t), esc(c), esc(n)) for p, j, w, g, t, c, n in NEXT])

  page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Training Status</title>
<style>
:root {{ color-scheme: light; --surface:#fcfcfb; --page:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --good:#0ca30c; --warn:#c98500; --bad:#d03b3b; --ring:rgba(11,11,11,0.10); --note:#52514e; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark; --surface:#1a1a19; --page:#0d0d0d; --ink:#f0efec; --ink2:#c3c2b7;
  --grid:#2c2c2a; --axis:#383835; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#0ca30c; --warn:#fab219; --bad:#e66767; --ring:rgba(255,255,255,0.10); --note:#c3c2b7; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --surface:#1a1a19; --page:#0d0d0d; --ink:#f0efec; --ink2:#c3c2b7; --grid:#2c2c2a; --axis:#383835;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --good:#0ca30c; --warn:#fab219; --bad:#e66767; --ring:rgba(255,255,255,0.10); --note:#c3c2b7; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--page); color:var(--ink); font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1080px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:28px; margin:0 0 4px; }} h2 {{ font-size:20px; margin:40px 0 6px; }} h3 {{ font-size:16px; margin:20px 0 4px; }}
p {{ max-width:760px; color:var(--ink2); margin:6px 0 12px; }} .sub {{ color:var(--muted); font-size:13px; }}
.callout {{ background:var(--surface); border:1px solid var(--ring); border-left:4px solid var(--warn); border-radius:10px; padding:12px 16px; margin:16px 0; max-width:820px; }}
.callout p {{ margin:4px 0; color:var(--ink); }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr)); gap:12px; }}
.card {{ background:var(--surface); border:1px solid var(--ring); border-radius:12px; padding:14px; }}
.card p {{ font-size:14px; color:var(--ink); margin:8px 0; }}
.cardhead {{ display:flex; gap:10px; align-items:center; }} .name {{ font-weight:700; font-size:18px; }}
.sw {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px; vertical-align:baseline; }} .sw.big {{ width:14px; height:34px; border-radius:4px; margin:0; }}
.badge {{ display:inline-block; border:1.5px solid; border-radius:999px; padding:1px 10px; font-weight:600; font-size:13px; margin:10px 0 8px; }}
.bar {{ height:10px; background:var(--grid); border-radius:5px; overflow:hidden; }} .bar div {{ height:100%; border-radius:5px; }}
.panel, .card {{ min-width:0; }}
.panel {{ background:var(--surface); border:1px solid var(--ring); border-radius:12px; padding:12px 12px 4px; margin:10px 0; }}
.grid2 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr)); gap:12px; }}
svg {{ width:100%; height:auto; display:block; font-family:inherit; }}
.grid {{ stroke:var(--grid); stroke-width:1; }} .axis {{ stroke:var(--axis); stroke-width:1; }}
.tick {{ fill:var(--muted); font-size:12px; }} .axlab {{ fill:var(--ink2); font-size:12px; }}
.dlabel {{ fill:var(--ink); font-size:13px; font-weight:600; }}
.goal {{ stroke:var(--ink2); stroke-width:1; stroke-dasharray:4 4; }} .goaltext {{ fill:var(--ink2); font-size:12px; }}
.leader {{ stroke:var(--note); stroke-width:1; }} .note {{ fill:var(--note); font-size:12.5px; font-style:italic; }}
.hit {{ fill:transparent; cursor:pointer; }}
#tip {{ position:fixed; pointer-events:none; background:var(--ink); color:var(--surface); padding:6px 10px; border-radius:6px; font-size:13px; display:none; max-width:280px; z-index:5; }}
.scroll {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; background:var(--surface); border-radius:12px; overflow:hidden; font-size:14px; }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--grid); vertical-align:top; }}
thead th {{ font-size:13px; color:var(--ink2); }} .matrix td, .matrix th {{ min-width:150px; }} .rowh {{ font-weight:600; }}
.st {{ font-weight:700; font-size:16px; }}
.legend {{ display:flex; gap:16px; flex-wrap:wrap; font-size:13px; color:var(--ink2); margin:6px 0; }}
details {{ margin-top:8px; }} summary {{ cursor:pointer; color:var(--ink2); }}
</style></head><body><main>
<h1>Agent training status</h1>
<div class="sub">10 November 2026 · PoRace on Unreal · for deciding what to train next</div>

<div class="callout"><p><b>Nothing is training right now.</b> There's no hourly update to give and no finish time to estimate.
The last training session ended on 10 November at 04:40 UTC (Grandma). Since then the work has been moving the game to Unreal,
which reuses the trained brains as they are. The charts below are the recorded training history. The time estimates are for the
jobs you could start next, worked out from how long similar runs took on the RTX 2060 the past runs used. This PC has an
RTX 5070 Ti (12 GB), so expect them to finish sooner.</p></div>

<h2>Where each agent stands</h2>
<p>"Skills" counts the nine abilities in the table further down: a pass counts 1, a partial pass counts ½.</p>
<div class="cards">{"".join(cards)}</div>

<h2>The three main training signals</h2>
<p>These are the three numbers training logs most closely (in TensorBoard), shown for Blue's everyday racing brain, the one
every race uses. Read them like a learner's report card. <b>Score</b> is the overall mark the learner is chasing. <b>Seconds without
falling</b> shows whether it stays on its feet for the whole 20 s test. <b>Speed-following points</b> show whether it goes the
speed it's told. Hover over a dot to see its value.</p>
<div class="grid2">
<div class="panel"><h3>1 · Score</h3>{ch1.svg("Blue's training score rising from 0 to about 26 and levelling off")}</div>
<div class="panel"><h3>2 · Seconds without falling (of a 20 s test)</h3>{ch2.svg("Blue's time on its feet rising from 7 s to the full 20 s")}</div>
<div class="panel"><h3>3 · Speed-following points</h3>{ch3.svg("Blue's speed-following rising as it learned to match the asked speed")}</div>
</div>
<p>All three curves rise, then go flat. A flat line is the signal to stop: more practice no longer helps, so the run was ended
and the brain was put through its skill tests.</p>

<h2>The humans: race test score, run by run</h2>
<p>Matt's and Grandma's raw training logs stayed on the training PC, so their charts use the score that decides whether a brain
ships: the <b>race test</b>, 100 random runs at race speeds and turns. 90 is the pass mark.</p>
<div class="grid2">
<div class="panel"><h3>Matt</h3>{ch4.svg("Matt's race test score by run, from 49 to 98, with m20 shipped")}</div>
<div class="panel"><h3>Grandma</h3>{ch5.svg("Grandma's race test score from 0 to 94 over her training")}</div>
</div>

<h2>Blue's specialist brains</h2>
<div class="grid2">
<div class="panel"><h3>Hurdles (steeplechase)</h3>{ch6.svg("Hurdle course pass rate rising from 82 to 92 percent")}</div>
<div class="panel"><h3>Sprint (2.5 m/s)</h3>{ch7.svg("Sprint test passes rising from 0 to 10 of 10")}</div>
</div>

<h2>Skill by skill</h2>
<div class="legend"><span><b style="color:var(--good)">✓</b> Passed</span><span><b style="color:var(--warn)">◐</b> Partly</span>
<span><b style="color:var(--bad)">✗</b> Failed</span><span><b style="color:var(--muted)">–</b> Not trained / not tested</span></div>
{matrix}

<h2>What to train next: my ranking</h2>
<p>Ranked by how much each job improves the races for the effort, starting with the safe wins. "GPU time" is the machine
training time. "Your/my time" covers checks, fixes and the Unreal side.</p>
{nxt}
<p><b>My recommendation:</b> do 1 and 2 first. They're cheap, very likely to work, and change what you see in races:
a third racer, and fairer mixed races. Then 3. Leave 4–6 until jog or sprint tracks, or a fourth racer, are actually wanted.</p>

<details><summary>Where these numbers come from</summary>
<p>Blue's charts: the TensorBoard export <code>docs/report/tb_final.json</code> (runs r1 then r1b, 7–8 October). Matt's scores and
Blue's specialist runs: <code>docs/rl_optimization_log.md</code>. Grandma: <code>docs/20261109/grandma_ladder_points.json</code>.
Unreal results: the Slice 1–5 reports in <code>docs/20261110/</code>. Built by <code>tools/training_status_report.py</code>.</p></details>
</main>
<div id="tip" role="tooltip"></div>
<script>
const tip = document.getElementById('tip');
document.querySelectorAll('.hit').forEach(h => {{
  h.addEventListener('mouseenter', () => {{ tip.textContent = h.dataset.tip; tip.style.display = 'block'; }});
  h.addEventListener('mousemove', e => {{ tip.style.left = Math.min(e.clientX + 14, innerWidth - 290) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; }});
  h.addEventListener('mouseleave', () => {{ tip.style.display = 'none'; }});
  h.addEventListener('click', e => {{ tip.textContent = h.dataset.tip; tip.style.display = 'block'; tip.style.left = Math.min(e.clientX + 14, innerWidth - 290) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; }});
}});
</script>
</body></html>"""
  a.out.write_text(page, encoding="utf-8")
  print(f"wrote {a.out}")


if __name__ == "__main__":
  main()
