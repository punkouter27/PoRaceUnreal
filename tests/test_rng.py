"""SplitMix64 (racelib/rng.py) is the race's seeded dice; Source/PoRaceUnreal/RaceRng.h must match it bit for bit."""

import re
from pathlib import Path

from racelib.rng import SplitMix64

ROOT = Path(__file__).resolve().parent.parent


def test_reference_vector():
    # SplitMix64 reference outputs for seed 0 (Vigna's splitmix64.c)
    r = SplitMix64(0)
    assert [r.next_u64() for _ in range(3)] == [0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F]


def test_same_seed_same_sequence_and_ranges():
    a, b = SplitMix64(42), SplitMix64(42)
    xs = [a.uniform() for _ in range(1000)]
    assert xs == [b.uniform() for _ in range(1000)]
    assert all(0.0 <= x < 1.0 for x in xs)
    assert all(0 <= a.below(5) < 5 for _ in range(1000))
    items = list(range(10))
    shuffled = SplitMix64(7).shuffle(items)
    assert sorted(shuffled) == items and shuffled == SplitMix64(7).shuffle(items) and items == list(range(10))


def test_cpp_generator_uses_the_same_constants():
    src = (ROOT / "Source" / "PoRaceUnreal" / "RaceRng.h").read_text(encoding="utf-8")
    for const in ("0x9E3779B97F4A7C15", "0xBF58476D1CE4E5B9", "0x94D049BB133111EB"):
        assert re.search(const + "ull", src, re.IGNORECASE), const
