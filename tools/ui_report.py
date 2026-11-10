"""The Slice 4 UI change report: each Unreal screen beside its Unity counterpart, and the race screens at three aspects.

    python tools/ui_report.py [--shots Saved/PoRace/shots] [--logs Saved/PoRace]

Writes SCREENSHOTS/slice4/ (the images it uses) and SCREENSHOTS/slice4_ui_report.html. The [Check] lines of the UI test
logs (uitest_<w>x<h>.log) and the loop test (loop10.log) go in the report as they are.
"""
import argparse
import html
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNITY = ROOT / "docs" / "unity_screens"
OUT = ROOT / "SCREENSHOTS"

PAIRS = [   # (title, Unity image, Unreal image (1280x720), what changed)
    ("Menu", "roster_after/menu_picked_00_3s.png", "Menu_1280x720.png",
     "One screen, no scrolling: track, racers (ready and not ready, with the reason), laps, START. START stays off until a racer that may race on the track is picked."),
    ("Racer intro", "loop_after/intro_blue.png", "FlatOval_0_intro_1280x720.png",
     "A card per racer before the countdown (name, kind, height, mass, brain, this race's cruise speed); the camera frames that racer."),
    ("Countdown", "loop_before/countdown.png", "FlatOval_1_grid_1280x720.png", "The countdown over the grid; top left the track, lap and standings; top right the pause gear."),
    ("Racing", "matt_after/race_01_14s.png", "PlanarSprint_2_racing.png", "Chase camera on the pack; build stamp bottom right (Slice 3 capture: the UI test stops at 4 s)."),
    ("Results", "loop_after/final_results.png", "FlatOval_5_results_1280x720.png",
     "The classified order (a called race shows DNF with the distance), then MENU, REMATCH, NEXT TRACK."),
]
ASPECTS = ["1280x720", "540x1170", "1680x720"]


def checks(path):
  if not path.exists():
    return ["(no log)"]
  text = path.read_text(encoding="utf-8", errors="replace")
  return [re.sub(r"^.*?LogRace: (Display: |Error: )?", "", l).strip() for l in text.splitlines()
          if "[Check]" in l or "RaceUiTest]" in l or "[Loop]" in l or "AutoLoops]" in l]


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--shots", type=Path, default=ROOT / "Saved" / "PoRace" / "shots")
  ap.add_argument("--logs", type=Path, default=ROOT / "Saved" / "PoRace")
  a = ap.parse_args()
  img = OUT / "slice4"
  img.mkdir(parents=True, exist_ok=True)

  def take(src: Path, name: str):
    if not src.exists():
      return None
    shutil.copyfile(src, img / name)
    return f"slice4/{name}"

  rows = []
  for title, unity, unreal, note in PAIRS:
    u = take(UNITY / unity, "unity_" + Path(unity).name)
    r = take(a.shots / unreal, unreal)
    cell = lambda p, alt: f'<img src="{p}" alt="{alt}">' if p else '<div class="missing">not captured</div>'  # noqa: E731
    rows.append(f"<section><h2>{title}</h2><p>{html.escape(note)}</p><div class='pair'><figure>{cell(u, 'Unity')}"
                f"<figcaption>Unity (before)</figcaption></figure><figure>{cell(r, 'Unreal')}<figcaption>Unreal (after)</figcaption></figure></div></section>")
  aspect = []
  for screen in ("Menu", "FlatOval_1_grid", "FlatOval_5_results"):
    figs = []
    for asp in ASPECTS:
      name = f"{screen}_{asp}.png"
      p = take(a.shots / name, name)
      figs.append(f"<figure>{f'<img src={chr(34)}{p}{chr(34)}>' if p else '<div class=missing>not captured</div>'}<figcaption>{asp}</figcaption></figure>")
    aspect.append(f"<h3>{screen.split('_')[-1].capitalize()}</h3><div class='row'>{''.join(figs)}</div>")
  logs = "".join(f"<h3>{name}</h3><pre>{html.escape(chr(10).join(checks(a.logs / name)))}</pre>"
                 for name in [f"uitest_{x}.log" for x in ASPECTS] + ["loop10.log"])

  page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Slice 4 UI report</title><style>
:root {{ --bg:#14161b; --ink:#e8e8ec; --dim:#9a9aa4; --gold:#ffd040; --panel:#1d2027; }}
body {{ margin:0; padding:16px; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,sans-serif; }}
h1 {{ color:var(--gold); margin:0 0 4px; }} h2 {{ margin:28px 0 4px; }} p {{ color:var(--dim); max-width:900px; }}
.pair, .row {{ display:flex; gap:12px; flex-wrap:wrap; align-items:flex-start; }}
figure {{ margin:0; flex:1 1 300px; max-width:640px; }} img {{ width:100%; border-radius:8px; border:1px solid #333; }}
.row figure {{ flex:1 1 200px; }} figcaption {{ color:var(--dim); font-size:13px; }}
.missing {{ padding:40px; text-align:center; background:var(--panel); border-radius:8px; color:var(--dim); }}
pre {{ background:var(--panel); padding:12px; border-radius:8px; overflow-x:auto; font-size:12px; }}
</style></head><body>
<h1>PoRace — Slice 4 UI report</h1><p>The game loop in Unreal: menu, racer intro, countdown, race, results. Unity screens on the left, Unreal on the right.
Captured by the UI test (<code>-RaceUiTest -AutoStart=1 -RaceLimit=4 -RaceShots=…</code>), so the results card shows a called race.</p>
{''.join(rows)}
<h2>Aspect ratios</h2><p>The same screens at 16:9, a 9:19.5 portrait phone (540x1170) and 21:9: the menu, the countdown on the grid and the results card. The layout check (below) asserts every group stays on screen and none overlap.</p>
{''.join(aspect)}
<h2>Checks</h2>{logs}
</body></html>"""
  (OUT / "slice4_ui_report.html").write_text(page, encoding="utf-8")
  print(f"wrote {OUT / 'slice4_ui_report.html'} ({len(list(img.iterdir()))} images)")


if __name__ == "__main__":
  main()
