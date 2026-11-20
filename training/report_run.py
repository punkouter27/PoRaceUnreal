"""Training report for any run(s) (AGENTS.md: runs over 30 min get an HTML report with three milestone tiers, the top-3
metric charts and run-over-run deltas). Trainer image (needs tensorboard):

  python report_run.py --title "Matt m25" --out /docs/report/matt_m25.html \
      --run m25=runs/m25 --ladder m25=/docs/matt/ladder_m25.json --ladder m20=/docs/matt/ladder_m20_r3.json [--note "..."]

--run NAME=DIR (repeatable): TensorBoard scalars from DIR/tb. --ladder NAME=JSON (repeatable): matt/sim.py ladder output;
the first --ladder is "this run", the second the one it is compared with. Tiers: Toddler / Beginner = the ladder's
toddler checks (balance, pushes), Child / Intermediate = child (walk speeds, symmetry, force), Adult / Advanced = adult
(fast, turn, grade). Charts: eval episode reward, eval episode length, linear-velocity tracking. Self-contained HTML
(inline SVG, light / dark), no external assets."""

import argparse
import datetime
import html
import json
from pathlib import Path

from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

CHARTS = [
    ("eval/episode_reward", "Eval episode reward", "higher is better"),
    (
        "eval/avg_episode_length",
        "Eval episode length (control steps, max 1000)",
        "1000 = upright for the whole episode",
    ),
    (
        "eval/episode_reward/tracking_lin_vel",
        "Linear-velocity tracking reward",
        "how closely the body follows the commanded speed",
    ),
]
TIERS = [
    ("toddler", "Toddler / Beginner", "stand, ride out pushes"),
    ("child", "Child / Intermediate", "walk at three speeds: tracking, symmetry, foot force"),
    ("adult", "Adult / Advanced", "fast, turning, uphill"),
]
COLORS = ["#2563eb", "#ea8a2b", "#16a34a", "#9333ea"]


def scalars(d, tag):
    p = Path(d) / "tb"
    if not p.exists():
        return []
    ea = EventAccumulator(str(p), size_guidance={"scalars": 0})
    ea.Reload()
    return [(e.step, e.value) for e in ea.Scalars(tag)] if tag in ea.Tags().get("scalars", []) else []


def svg(series, w=520, h=220):
    pts = [p for s in series for p in s[2]]
    if not pts:
        return "<p>(no data)</p>"
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    if x1 == x0:
        x1 = x0 + 1
    if y1 == y0:
        y1 = y0 + 1
    pad = 0.06 * (y1 - y0)
    y0 -= pad
    y1 += pad
    X = lambda x: 48 + (x - x0) / (x1 - x0) * (w - 60)
    Y = lambda y: h - 28 - (y - y0) / (y1 - y0) * (h - 40)
    out = [
        f'<svg viewBox="0 0 {w} {h}" role="img" class="chart">',
        f'<line x1="48" y1="{h - 28}" x2="{w - 12}" y2="{h - 28}" class="axis"/><line x1="48" y1="12" x2="48" y2="{h - 28}" class="axis"/>',
        f'<text x="44" y="{Y(y1 - pad) + 4:.0f}" class="tick" text-anchor="end">{y1 - pad:.3g}</text><text x="44" y="{Y(y0 + pad) + 4:.0f}" class="tick" text-anchor="end">{y0 + pad:.3g}</text>',
        f'<text x="48" y="{h - 10}" class="tick">{x0 / 1e6:.0f}M</text><text x="{w - 12}" y="{h - 10}" class="tick" text-anchor="end">{x1 / 1e6:.0f}M steps</text>',
    ]
    for name, col, s in series:
        if s:
            out.append(
                f'<polyline fill="none" stroke="{col}" stroke-width="2" points="{" ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in s)}"><title>{html.escape(name)}</title></polyline>'
            )
    out.append("</svg>")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run", action="append", default=[])
    ap.add_argument("--ladder", action="append", default=[])
    ap.add_argument("--note", action="append", default=[])
    a = ap.parse_args()
    runs = [r.split("=", 1) for r in a.run]
    ladders = [(n, json.loads(Path(p).read_text())) for n, p in (l.split("=", 1) for l in a.ladder) if Path(p).exists()]
    E = html.escape
    parts = [f"<h1>{E(a.title)}</h1><p>Generated {datetime.date.today().isoformat()} by training/report_run.py.</p>"]
    for n in a.note:
        parts.append(f"<p>{E(n)}</p>")

    # milestone tiers
    parts.append("<h2>Milestones</h2>")
    if ladders:
        me, lad = ladders[0]
        ref = ladders[1] if len(ladders) > 1 else None
        parts.append('<div class="tiers">')
        for key, label, what in TIERS:
            rows = [(k.split("/", 1)[1], v) for k, v in lad.items() if k.startswith(key + "/")]
            if not rows:
                parts.append(
                    f'<section class="tier na"><h3>{label}</h3><p>{what}</p><p class="state">not reached (an earlier tier failed)</p></section>'
                )
                continue
            ok = all(v["passes"] >= v["need"] for _, v in rows)
            lis = []
            for name, v in rows:
                d = ""
                if ref:
                    rv = next(
                        (
                            rv
                            for rk, rv in ref[1].items()
                            if rk.split("/", 1)[-1].split(" ")[0] == name.split(" ")[0] and rk.startswith(key + "/")
                        ),
                        None,
                    )
                    if rv:
                        d = f' <span class="delta">({ref[0]}: {rv["passes"]}/10, err {rv["err"]:.3f})</span>'
                lis.append(
                    f"<li><b>{E(name)}</b>: {v['passes']}/10 (need {v['need']}), err {v['err']:.3f}, symmetry {v['sym']:.3f}, force {v['force']:.2f} BW"
                    f"{', hf ' + format(v['hf'], '.3f') if 'hf' in v else ''}{d}</li>"
                )
            parts.append(
                f'<section class="tier {"pass" if ok else "fail"}"><h3>{label}</h3><p>{what}</p><p class="state">{"PASS" if ok else "FAIL"} ({me})</p><ul>{"".join(lis)}</ul></section>'
            )
        parts.append("</div>")
    else:
        parts.append("<p>No ladder results yet.</p>")

    # charts
    parts.append("<h2>Top three metrics</h2><div class='charts'>")
    for tag, title, why in CHARTS:
        series = [(n, COLORS[i % len(COLORS)], scalars(d, tag)) for i, (n, d) in enumerate(runs)]
        legend = " ".join(f'<span style="color:{c}">■ {E(n)}</span>' for n, c, s in series if s)
        last = "; ".join(
            f"{n} last {s[-1][1]:.3g} at {s[-1][0] / 1e6:.1f}M (first {s[0][1]:.3g})" for n, c, s in series if s
        )
        parts.append(
            f"<figure><figcaption><b>{E(title)}</b>: {E(why)}<br>{legend}</figcaption>{svg(series)}<p class='small'>{E(last)}</p></figure>"
        )
    parts.append("</div>")

    # deltas
    if len(ladders) > 1:
        me, lad = ladders[0]
        rn, ref = ladders[1]
        parts.append(
            f"<h2>Run-over-run: {E(me)} vs {E(rn)}</h2><table><tr><th>check</th><th>{E(rn)}</th><th>{E(me)}</th><th>change in error</th></tr>"
        )
        for k, v in lad.items():
            r = next((rv for rk, rv in ref.items() if rk.split(" ")[0] == k.split(" ")[0]), None)
            if r is None:
                continue
            parts.append(
                f"<tr><td>{E(k)}</td><td>{r['passes']}/10, err {r['err']:.3f}</td><td>{v['passes']}/10, err {v['err']:.3f}</td><td>{v['err'] - r['err']:+.3f}</td></tr>"
            )
        parts.append("</table>")

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(a.title)}</title><style>
:root{{--bg:#f6f7f9;--fg:#1c2230;--muted:#5d6678;--card:#fff;--line:#dfe3ea;--ok:#1f7a4d;--bad:#b3261e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14171d;--fg:#e6e9ef;--muted:#9aa3b2;--card:#1c2028;--line:#2b313c;--ok:#4cc38a;--bad:#f2867d}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif}} main{{max-width:1100px;margin:0 auto;padding:24px 16px}}
p,li{{color:var(--muted)}} b{{color:var(--fg)}} .small{{font-size:13px}} .delta{{font-size:13px}}
.tiers{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}} @media (max-width:800px){{.tiers{{grid-template-columns:1fr}}}}
.tier{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}} .tier h3{{margin:0}}
.tier.pass .state{{color:var(--ok);font-weight:700}} .tier.fail .state{{color:var(--bad);font-weight:700}} .tier.na{{opacity:.6}}
.charts{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} @media (max-width:800px){{.charts{{grid-template-columns:1fr}}}}
figure{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px}} .chart{{width:100%;height:auto}}
.axis{{stroke:var(--line)}} .tick{{fill:var(--muted);font-size:11px}}
table{{border-collapse:collapse;width:100%;background:var(--card)}} td,th{{border:1px solid var(--line);padding:6px 8px;text-align:left}}
</style></head><body><main>{"".join(parts)}</main></body></html>"""
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(page)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
