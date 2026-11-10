"""The race, in plain Python + CPU MuJoCo: the reference every other runtime is checked against.

  track.py     a track as data: centre line, lanes, banking, curves (Unreal: RaceTrack.h)
  rng.py       the seeded random draw (Unreal: RaceRng.h)
  go2racer.py  one Go2 in a shared model: brains, get-up switch, auto-reset (Unreal: RacerGo2.h)
  race.py      the race rules: countdown, steering, checkpoints, un-stick, finish (Unreal: RaceRules.h)

Every timer is a whole number of physics steps (4 ms), so both runtimes count the same way.
"""
