"""The reference race: one race on CPU MuJoCo with the real brains, printing the same result line Unreal prints.

    uv run --no-project --python 3.12 --with mujoco==4.0.0 --with onnxruntime --with numpy python race.py planar_sprint --seed 1
      [--racers blue,matt] [--laps 2] [--flip-at 20] [--mjb Saved/PoRace/model_bound_<track>.mjb] [--log race.jsonl]

--mjb steps the model Unreal ran (saved by the controller) instead of the track XML: then Unreal and Python step the
same numbers, and the finish times should match exactly.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import mujoco

sys.path.insert(0, str(Path(__file__).parent))
from go2.sim import brain  # noqa: E402
from racelib.go2racer import Go2Racer  # noqa: E402
from racelib.human import HumanRacer  # noqa: E402
from racelib.model import apply_numbers, apply_option  # noqa: E402
from racelib.race import Entry, Race  # noqa: E402
from racelib.track import Track  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def load(track_id, mjb):
  """The track model with the fingerprints' exact numbers, as URacerController::BindRace makes it: the track's options
  and world, then every racer's body (by prefix), then mj_setConst (racelib/model.py)."""
  fp = json.loads((ROOT / "training" / "models" / "tracks" / f"{track_id}_fingerprint.json").read_text())
  m = mujoco.MjModel.from_binary_path(str(mjb)) if mjb else mujoco.MjModel.from_xml_path(str(ROOT / fp["model"]))
  apply_option(m, fp["option"])
  missing = apply_numbers(m, fp["world"])
  for r in fp["racers"]:
    missing += apply_numbers(m, json.loads((ROOT / r["fingerprint"]).read_text())["model"], r["prefix"])
  assert missing == 0, f"{missing} names of the fingerprints are not in the model"
  d = mujoco.MjData(m)
  mujoco.mj_setConst(m, d)
  return m, d, fp


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("track")
  ap.add_argument("--seed", type=int, default=1)
  ap.add_argument("--laps", type=int, default=0)
  ap.add_argument("--flip-at", type=float, default=-1.0)
  ap.add_argument("--racers", help="comma-separated racer names on the grid (default: every racer of the track model)")
  ap.add_argument("--mjb", type=Path)
  ap.add_argument("--log", type=Path, help="JSONL: every racer's distance and state at 10 Hz")
  a = ap.parse_args()

  m, d, fp = load(a.track, a.mjb)
  mujoco.mj_resetData(m, d)   # as FRaceRules::Setup: reset, the draw (each racer reset onto its slot), one forward
  want = [n.strip().lower() for n in a.racers.split(",")] if a.racers else None
  entries, parked = [], []
  for r in fp["racers"]:
    card = json.loads((ROOT / "training" / "characters" / f"{r['card']}.json").read_text())
    if card["kind"] == "human":
      creature = json.loads((ROOT / card["fingerprint"]).read_text())
      racer = HumanRacer(m, d, r["prefix"], card, creature, brain(r["brain"]))
    else:
      racer = Go2Racer(m, d, r["prefix"], brain(r["brain"]), brain(r["getupBrain"]), r["homeHeight"])
    if want is not None and r["name"].lower() not in want:
      parked.append(racer)
      continue
    entries.append(Entry(r["name"], racer, r["cruise"], r["maxYawRate"], r["usesUnstick"], card.get("holdsHeadingAtRest", False), card.get("impratio", 100.0)))
  race = Race(Track.load(a.track), entries, a.seed, laps=a.laps, flip_at=a.flip_at, parked=parked)
  mujoco.mj_forward(m, d)
  log = a.log.open("w") if a.log else None
  t0 = time.perf_counter()
  while not race.over:
    race.pre_step()
    race.control()
    mujoco.mj_step(m, d)
    if log and race.step % 25 == 0:
      log.write(json.dumps({"step": race.step, "phase": race.phase, "t": round(race.race_time(), 3),
                            "racers": [[e.name, round(e.distance, 3), e.state, e.racer.mode] for e in entries]}) + "\n")
  print(f"[Race] {race.result_line()}")
  print(f"[Perf] {race.step} physics steps in {time.perf_counter() - t0:.1f} s on the CPU")
  return 0 if race.phase == "Finished" else 1


if __name__ == "__main__":
  sys.exit(main())
