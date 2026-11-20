"""The tactics and yellow-flag rules on made-up racers, no physics. FRaceRules::SelfTest (Unreal, -RaceSelfTest) prints
the same lines; scripts/selftest.ps1 diffs them. Also checks each line against what the rule should do.

    uv run --no-project --python 3.12 --with mujoco==4.0.0 --with onnxruntime --with numpy python selftest.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from racelib.go2racer import FALLEN, RACING, STUMBLE  # noqa: E402
from racelib.race import Entry, YellowFlag, tactic  # noqa: E402

# name, half width, who, line, rows (name, distance, lateral, speed, aggression, state, passing)
CASES = [
    ("pass", 1.5, 0, 0.0, [("A", 10.0, 0.0, 1.5, 0.2, RACING, -1), ("B", 11.5, 0.1, 1.2, 0.2, RACING, -1)]),
    (
        "pass-left",
        1.5,
        0,
        0.0,
        [
            ("A", 10.0, 0.0, 1.5, 0.2, RACING, -1),
            ("B", 11.0, -0.3, 1.2, 0.2, RACING, -1),
            ("C", 9.0, -0.9, 1.4, 0.2, RACING, -1),
        ],
    ),
    ("avoid", 1.5, 0, 0.0, [("A", 10.0, 0.0, 1.5, 0.2, RACING, -1), ("B", 14.0, 0.5, 1.6, 0.2, FALLEN, -1)]),
    ("pass-hold", 2.0, 0, 0.4, [("A", 10.3, 0.55, 1.5, 0.2, RACING, 1), ("B", 10.0, -0.05, 1.3, 0.2, RACING, -1)]),
    ("pass-done", 2.0, 0, 0.4, [("A", 11.1, 0.55, 1.5, 0.2, RACING, 1), ("B", 10.0, -0.05, 1.3, 0.2, RACING, -1)]),
    (
        "pass-wide",
        1.5,
        0,
        0.0,
        [("S", 10.0, 0.0, 1.5, 0.2, RACING, -1, 0.65), ("B", 11.5, 0.1, 1.2, 0.2, RACING, -1, 0.35)],
    ),
    (
        "alongside",
        1.5,
        0,
        0.0,
        [("S", 10.0, 0.1, 1.45, 0.2, RACING, -1, 0.65), ("B", 10.3, -0.1, 1.45, 0.2, RACING, -1, 0.35)],
    ),
    ("faster-ahead", 1.5, 0, 0.0, [("A", 10.0, 0.0, 1.2, 0.2, RACING, -1), ("B", 11.0, 0.0, 1.5, 0.2, RACING, -1)]),
    ("block", 1.5, 0, 0.3, [("C", 20.0, 0.3, 1.2, 0.8, RACING, -1), ("D", 19.0, -0.2, 1.5, 0.2, RACING, 0)]),
    ("no-block-timid", 1.5, 0, 0.3, [("C", 20.0, 0.3, 1.2, 0.3, RACING, -1), ("D", 19.0, -0.2, 1.5, 0.2, RACING, 0)]),
    ("boxed-in", 0.9, 0, 0.0, [("A", 0.0, 0.0, 1.5, 0.2, RACING, -1), ("B", 1.0, 0.0, 1.2, 0.2, RACING, -1)]),
    ("stumbling", 1.5, 0, 0.2, [("A", 10.0, 0.0, 1.5, 0.2, STUMBLE, -1), ("B", 11.0, 0.0, 1.2, 0.2, RACING, -1)]),
]

# what each rule must do (the intent, and the target lateral)
EXPECT = {
    "pass": ("PASS R", -0.55),  # equal room both sides, A is right of B: right, 0.65 m beside B
    "pass-left": ("PASS L", 0.35),  # C is down the right side: more room left
    "avoid": ("AVOID", -0.35),  # B is down: 0.85 m beside it, the left would be past the rail margin
    "pass-hold": ("PASS L", 0.6),  # alongside, 0.3 m ahead, 0.6 m aside: the pass holds its line
    "pass-done": ("-", 0.4),  # 1.1 m clear: back to its own line
    "pass-wide": ("PASS R", -0.6),  # a 0.65 m stroller passes a 0.35 m dog 0.70 m aside (half widths + 0.2)
    "alongside": ("ALONGSIDE", 0.6),  # level with a dog 0.2 m to its right: holds 0.70 m left of it
    "faster-ahead": ("-", 0.0),  # nobody slower ahead: hold the line
    "block": ("BLOCK", 0.45),  # aggressive C covers D's line: 40 % of the way (0.1), but never closer than 0.65 to D
    "no-block-timid": ("-", 0.3),  # aggression 0.3: holds its line
    "boxed-in": ("-", 0.0),  # no room either side on a narrow track: stay behind
    "stumbling": ("-", 0.2),  # no manoeuvres while stumbling
}


def lines():
    out = []
    for name, half_width, who, line, rows in CASES:
        entries = []
        for row in rows:
            n, dist, lat, speed, aggr, state, passing = row[:7]
            e = Entry(n, None, 1.5, 1.2, True)
            e.width = row[7] if len(row) > 7 else 0.35
            e.distance, e.lateral, e.speed, e.aggression, e.state, e.passing = dist, lat, speed, aggr, state, passing
            entries.append(e)
        v = tactic(entries, who, line, half_width)
        e = entries[who]
        out.append(
            f"tactic {name}: target={v:.4f} intent={e.intent or '-'} passing={entries[e.passing].name if e.passing >= 0 else '-'}"
        )
    for live in (3, 2):
        y = YellowFlag(True)
        log = ""
        for s in range(10000):
            was = y.out
            y.update(s, True, live, 2 if (100 <= s < 2000 or 3000 <= s < 9000) else 0)
            if y.out != was:
                log += f" {'out' if y.out else 'in'}@{s}"
        out.append(f"yellow live={live}:{log or ' none'} count={y.count}")
    return out


def main():
    fails = 0
    for ln in lines():
        print(f"[SelfTest] {ln}")
        if ln.startswith("tactic "):
            name = ln.split(":")[0][7:]
            target = float(ln.split("target=")[1].split(" ")[0])
            want = EXPECT[name]
            got_intent = ln.split("intent=")[1].rsplit(" passing=", 1)[0]
            if got_intent != want[0] or abs(target - want[1]) > 1e-9:
                print(f"  FAIL: want intent {want[0]} target {want[1]}")
                fails += 1
    # yellow: out 2 s after... out at once, in after 5 s (1250 steps), 15 s cooldown, out again, in after 5 s
    want_y = ["yellow live=3: out@100 in@1351 out@5102 in@6353 count=2", "yellow live=2: none count=0"]
    for w in want_y:
        if w not in lines():
            print(f"  FAIL: want {w}")
            fails += 1
    print(f"[SelfTest] {'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
