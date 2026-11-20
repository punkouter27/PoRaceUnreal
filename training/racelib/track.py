"""A track as data (training/tracks/<id>.json). The centre line is a polyline in the MuJoCo frame (x forward, y left,
metres); rails, lanes, grid, checkpoints and steering targets all follow from it. Port of the Unity MapDefinition;
Source/PoRaceUnreal/RaceTrack.cpp is the same maths.
"""

import json
import math
from pathlib import Path

TRACKS = Path(__file__).resolve().parent.parent / "tracks"


def curve(keys, t, default):
    """A Unity AnimationCurve: cubic Hermite between keys (tangents per unit t), clamped outside the keys."""
    if not keys:
        return default
    if t <= keys[0]["t"]:
        return keys[0]["v"]
    if t >= keys[-1]["t"]:
        return keys[-1]["v"]
    i = 0
    while keys[i + 1]["t"] <= t:
        i += 1
    k0, k1 = keys[i], keys[i + 1]
    dt = k1["t"] - k0["t"]
    if math.isinf(k0["out"]) or math.isinf(k1["in"]):  # a stepped key
        return k0["v"]
    s = (t - k0["t"]) / dt
    s2, s3 = s * s, s * s * s
    return (
        (2 * s3 - 3 * s2 + 1) * k0["v"]
        + (s3 - 2 * s2 + s) * dt * k0["out"]
        + (-2 * s3 + 3 * s2) * k1["v"]
        + (s3 - s2) * dt * k1["in"]
    )


def left(t):
    return (-t[1], t[0])


class Track:
    def __init__(self, data: dict):
        self.data = data
        self.id = data["id"]
        self.name = data["displayName"]
        self.terrain = data["terrain"]
        self.closed = bool(data["closed"])
        self.default_laps = int(data["defaultLaps"])
        self.half_width = float(data["halfWidth"])
        self.grid_slots = int(data["gridSlots"])
        self.lane_spacing = float(data["laneSpacing"])
        self.checkpoint_spacing = float(data["checkpointSpacing"])
        self.look_ahead = float(data["lookAhead"])
        self.points = [(float(p["x"]), float(p["y"])) for p in data["centerline"]]
        self.lane_keys = data.get("laneScale") or []
        self.bank_keys = data.get("bankDeg") or []
        n = len(self.points)
        self.n = n if self.closed else n - 1
        self.cum = [0.0]
        for i in range(self.n):
            a, b = self.P(i), self.P(i + 1)
            self.cum.append(self.cum[-1] + math.sqrt((b[0] - a[0]) * (b[0] - a[0]) + (b[1] - a[1]) * (b[1] - a[1])))
        self.length = self.cum[-1]

    @staticmethod
    def load(track_id: str) -> "Track":
        return Track(json.loads((TRACKS / f"{track_id}.json").read_text(encoding="utf-8")))

    def P(self, i):
        n = len(self.points)
        return self.points[i % n] if self.closed else self.points[min(max(i, 0), n - 1)]

    def wrap(self, s):
        """s into [0, length): fmod, then one length added to a negative remainder (RaceTrack.cpp does the same)."""
        r = math.fmod(s, self.length)
        return r + self.length if r < 0 else r

    def u(self, s):
        """Fraction of a lap at arc length s (closed tracks wrap, open ones clamp)."""
        return self.wrap(s) / self.length if self.closed else min(max(s / self.length, 0.0), 1.0)

    def point_at(self, s):
        """Point and unit tangent at arc length s. Closed tracks wrap; open tracks extrapolate past the ends."""
        if self.closed:
            s = self.wrap(s)
        i = 0
        if s >= self.length:
            i = self.n - 1
        elif s > 0:
            while i < self.n - 1 and self.cum[i + 1] <= s:
                i += 1
        a, b = self.P(i), self.P(i + 1)
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.sqrt(dx * dx + dy * dy)
        t = (dx / ln, dy / ln)
        return (a[0] + t[0] * (s - self.cum[i]), a[1] + t[1] * (s - self.cum[i])), t

    def segment_at(self, s):
        """The segment holding arc length s (point_at's search; closed tracks wrap)."""
        if self.closed:
            s = self.wrap(s)
        i = 0
        if s >= self.length:
            i = self.n - 1
        elif s > 0:
            while i < self.n - 1 and self.cum[i + 1] <= s:
                i += 1
        return i

    def lane_scale(self, s):
        return curve(self.lane_keys, self.u(s), 1.0)

    def lane_point(self, s, lane):
        """Lane centre at arc length s for a lane offset (+ left of travel), the lap's squeeze applied."""
        p, t = self.point_at(s)
        l, k = left(t), lane * self.lane_scale(s)
        return (p[0] + l[0] * k, p[1] + l[1] * k), t

    def bank_at(self, s):
        return curve(self.bank_keys, self.u(s), 0.0)

    @property
    def bank_half_width(self):
        return self.half_width + 0.15

    def surface_height(self, s, lateral):
        """Surface z at arc length s, lateral offset (+ left). The pivot edge stays flush with the floor."""
        b = self.bank_at(s)
        if abs(b) < 1e-3:
            return 0.0
        return max(0.0, self.bank_half_width - math.copysign(1.0, b) * lateral) * math.tan(math.radians(abs(b)))

    def lane_offsets(self, n):
        """Lane offsets for n racers, centred, leftmost first; squeezed when more racers than grid slots."""
        spacing = (
            min(self.lane_spacing, 2.0 * (self.half_width - 0.35) / (n - 1))
            if n > self.grid_slots
            else self.lane_spacing
        )
        return [((n - 1) * 0.5 - i) * spacing for i in range(n)]
