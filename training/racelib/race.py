"""The race rules, ported from the Unity MultiRaceOrchestrator. Source/PoRaceUnreal/RaceRules.cpp is the same code.

Per physics step, before mj_step (Unity ran this after the previous step: the same state):
  every racer's update_state(), then the rules for it, then every racer's control().
Tactics (pass, avoid, block, the lateral step), the yellow flag, the handicap, bump counting and the contact audit are
Slice 5 (Unity's r3 rules). Pure pieces (YellowFlag, tactic) are module level so selftest.py can drive them without
physics; RaceRules.cpp's SelfTest prints the same lines.
"""
import math
from dataclasses import dataclass, field

from go2 import constants as C
from racelib.go2racer import FALLEN, RACING
from racelib.rng import SplitMix64
from racelib.track import Track, left

DT = C.SIM_DT
COUNTDOWN_STEPS = 750      # 3 s
STEER_GAIN = 1.5
SPEED_SPREAD = 0.06        # each race draws a cruise speed in [1 - spread, 1] x the racer's cruise
STUCK_STEPS = 125          # 0.5 s nearly stopped while asked for more than 1 m/s -> restart the command ramp
STUCK_SPEED = 0.3          # m/s
BACKOFF_STEPS = 300        # 1.2 s backing off at -0.5 m/s after six restarts gained under 0.3 m
OFF_TRACK = 1.0            # m beyond the half width -> back to the last checkpoint
TEST_LIMIT_STEPS = 150000  # 600 s: a test race that has not finished is called DNF

# Tactics: lane choice (Unity MultiRaceOrchestrator.Tactic)
MAX_LATERAL = 0.25         # m/s sideways command toward the chosen line (the brains trained on |vy| <= 0.8)
OFFSET_SLEW = 0.6 * DT     # the tactical offset moves at 0.6 m/s
PASS_GAP = 0.65            # m beside a slower racer when passing it
PASS_CLEAR = 1.0           # m ahead of it before a pass lets go
AVOID_GAP = 0.85           # m beside a racer that is down
MARGIN = 0.45              # m kept from the rail
OVERTAKE_HYST = 0.25       # m: a pair must be this far apart to count who is ahead

# Yellow flag (Unity proposals r3 A3)
YELLOW_SCALE = 0.8
YELLOW_STEPS = 1250        # out for at most 5 s
YELLOW_COOLDOWN = 3750     # then not again for 15 s

# Contact audit (Unity ContactAudit, proposals r3 B9)
AUDIT_CLASSES = ("foot-floor", "body-floor", "robot-robot", "self", "other")
FOOT_LIMIT, OTHER_LIMIT = 0.01, 0.025   # m of penetration
AUDIT_SUSTAIN_STEPS = 25                # 0.1 s past the limit in a row fails -ContactGate

COUNTDOWN, RACING_PHASE, FINISHED = "Countdown", "Racing", "Finished"


@dataclass
class Entry:
  name: str
  racer: object
  cruise: float
  max_yaw: float
  uses_unstick: bool
  holds_heading: bool = False   # steer to the track heading during the countdown (a brain that drifts on a zero command)
  impratio: float = 100.0       # the impratio its brain was trained at (the race runs at the grid's lowest)
  feet: tuple = ()              # foot geom names (prefixed), for the contact audit
  pace: float = 1.0             # share of the commanded speed it holds over a race (card 'pace'): the handicap's expectation
  lane: float = 0.0
  speed: float = 0.0
  aggression: float = 0.0
  head_start: float = 0.0
  spawn_s: float = 0.0          # arc length (laps included) a reset puts it back to
  distance: float = 0.0
  segment: int = 0
  lap: int = 0
  checkpoint: int = 0
  lateral: float = 0.0
  offset: float = 0.0           # tactical offset from the racing line (+ left)
  intent: str = ""              # "PASS L" / "PASS R" / "AVOID" / "BLOCK" / ""
  passing: int = -1             # index of the racer this one is getting past (-1: none)
  finish_time: float = -1.0
  place: int = 0
  state: str = RACING
  down: bool = False
  falls: int = 0
  stuck_steps: int = 0
  unsticks: int = 0
  unstick_dist: float = 0.0
  unstick_chain: int = 0
  backoff_steps: int = 0
  backoffs: int = 0
  off_track: int = 0
  passes: int = 0


def move_towards(cur, target, delta):
  """Unity Mathf.MoveTowards."""
  return target if abs(target - cur) <= delta else cur + math.copysign(delta, target - cur)


def approx(a, b):
  """Unity Mathf.Approximately, in doubles."""
  return abs(b - a) < max(1e-6 * max(abs(a), abs(b)), 1e-300)


class YellowFlag:
  """Out when 2+ racers are down mid-race (3+ on the grid); in when fewer than 2 are down or after YELLOW_STEPS; then
  a cooldown so a long pile-up does not hold the field back for good."""

  def __init__(self, enabled):
    self.enabled = enabled
    self.out = False
    self.since = -1
    self.end = -(1 << 40)
    self.count = 0

  def update(self, step, racing, n_live, n_down):
    want = self.enabled and racing and n_live >= 3 and n_down >= 2
    if not self.out and want and step - self.end > YELLOW_COOLDOWN:
      self.out, self.since = True, step
      self.count += 1
    elif self.out and (n_down < 2 or step - self.since > YELLOW_STEPS or not racing):
      self.out, self.end = False, step


def room(entries, i, lat):
  """Clearance (m) at a lateral position from the nearest other running racer within 3 m along the track."""
  r, best = entries[i], 5.0
  for k, o in enumerate(entries):
    if k != i and o.finish_time < 0 and abs(o.distance - r.distance) < 3.0:
      best = min(best, abs(o.lateral - lat))
  return best


def tactic(entries, i, line, half_width):
  """Where racer i wants to be across the track (lateral, + left). Pass a slower or fallen racer up to 2.5 m (5 m if it
  is down) ahead and in the way, on the side with more room; an aggressive racer with an attacker within 1.5 m behind
  moves across to cover that line. Otherwise hold the racing line. Sets intent and passing."""
  r = entries[i]
  edge, me = half_width - MARGIN, line + r.offset
  if r.state != RACING:
    r.intent, r.passing = "", -1
    return me
  block, best_gap = -1, float("inf")
  for k, o in enumerate(entries):
    if k == i or o.finish_time >= 0:
      continue
    ds, down = o.distance - r.distance, o.state != RACING
    # a pass under way holds until the passer is PASS_CLEAR ahead, with the side window widened by the gap: without it
    # the passer drifted back once 0.55 m aside and cut across the slower racer's nose (Flat Oval handicap seed 1)
    held = k == r.passing
    if ds <= (-PASS_CLEAR if held else 0.0) or ds > (5.0 if down else 2.5) or abs(o.lateral - me) > (0.8 if down else 0.55) + (PASS_GAP if held else 0.0):
      continue
    if (down or o.speed * o.pace < r.speed * r.pace - 0.01) and ds < best_gap:   # slower: at the pace it holds
      best_gap, block = ds, k
  if block >= 0:
    b = entries[block]
    gap = AVOID_GAP if b.state != RACING else PASS_GAP
    lft, rgt = b.lateral + gap, b.lateral - gap
    room_l = room(entries, i, lft) if lft <= edge else -1.0
    room_r = room(entries, i, rgt) if rgt >= -edge else -1.0
    if room_l >= 0.0 or room_r >= 0.0:
      go_left = room_l > room_r or (approx(room_l, room_r) and me >= b.lateral)
      r.passing = block
      r.intent = "AVOID" if b.state != RACING else "PASS L" if go_left else "PASS R"
      return lft if go_left else rgt
  r.passing = -1
  if r.aggression > 0.5:
    for k, p in enumerate(entries):
      if k == i or p.passing != i:
        continue
      behind = r.distance - p.distance
      if 0.0 < behind < 1.5:
        r.intent = "BLOCK"
        return min(max(line + (p.lateral - line) * 0.4, -edge), edge)
  r.intent = ""
  return line


class ContactAudit:
  """'No clipping', measured: per contact class the deepest penetration and the longest run of steps past its limit
  (feet on the floor 1 cm, everything else 2.5 cm). Read only."""

  def __init__(self, m, entries):
    self.roots = {int(m.body_rootid[e.racer.base]) for e in entries}
    self.feet = set()
    for e in entries:
      for f in e.feet:   # the whole name, or a "_"-suffix of it (Unreal's model: URLab's "{Actor}_" prefix, RaceNames.h)
        g = next(i for i in range(m.ngeom) if m.geom(i).name == f or m.geom(i).name.endswith("_" + f))
        self.feet.add(g)
    n = len(AUDIT_CLASSES)
    self.max, self.run, self.worst, self.contacts = [0.0] * n, [0] * n, [0] * n, [0] * n
    self.steps = 0

  def step(self, m, d):
    self.steps += 1
    deep = [0.0] * len(AUDIT_CLASSES)
    for i in range(d.ncon):
      c = d.contact[i]
      if c.dist >= 0.0:
        continue
      g1, g2 = int(c.geom[0]), int(c.geom[1])
      r1, r2 = int(m.body_rootid[m.geom_bodyid[g1]]), int(m.body_rootid[m.geom_bodyid[g2]])
      a, b = r1 in self.roots, r2 in self.roots
      if a and b:
        k = 3 if r1 == r2 else 2
      elif a or b:
        other, mine = (r2, g1) if a else (r1, g2)
        k = 4 if other != 0 else 0 if mine in self.feet else 1
      else:
        continue
      depth = -c.dist
      self.contacts[k] += 1
      deep[k] = max(deep[k], depth)
      self.max[k] = max(self.max[k], depth)
    for k in range(len(AUDIT_CLASSES)):
      lim = FOOT_LIMIT if k == 0 else OTHER_LIMIT
      self.run[k] = self.run[k] + 1 if deep[k] > lim else 0
      self.worst[k] = max(self.worst[k], self.run[k])

  def failures(self):
    return [f"{AUDIT_CLASSES[k]} penetration over {(FOOT_LIMIT if k == 0 else OTHER_LIMIT) * 100:.1f} cm for {self.worst[k] * DT:.2f} s"
            for k in range(len(AUDIT_CLASSES)) if self.worst[k] > AUDIT_SUSTAIN_STEPS]

  def line(self):
    parts = [f"{AUDIT_CLASSES[k]} max {self.max[k] * 100:.2f} cm (limit {(FOOT_LIMIT if k == 0 else OTHER_LIMIT) * 100:.1f}, "
             f"longest over {self.worst[k] * DT:.2f} s, {self.contacts[k]} contacts)" for k in range(len(AUDIT_CLASSES))]
    return " | ".join(parts) + f" | {self.steps} steps"


@dataclass
class Race:
  track: Track
  entries: list
  seed: int
  laps: int = 1
  flip_at: float = -1.0
  flip_count: int = 1           # racers knocked over at flip_at: the leader, then the next in the standings
  randomize_grid: bool = True
  tactics: bool = True
  handicap: bool = False
  yellow_flag: bool = False     # off in tests unless asked (Unity: -yellowFlag); on in interactive races
  audit: bool = False
  intro_steps: int = 0          # racers stand on the grid this long before the countdown (the HUD's racer intro)
  finish_window_steps: int = 0  # interactive: the race is called this long after the winner (0: off, as in tests)
  limit_steps: int = TEST_LIMIT_STEPS   # the race is called this long after the start
  phase: str = COUNTDOWN
  step: int = 0
  race_start: int = -1
  finished: int = 0
  flips: int = 0
  called: bool = False          # ended by the finish window or the limit: the rest are classified by distance
  first_finish: int = -1
  bumps: int = 0                # robot-robot contacts while racing: separate touches, and steps in contact
  bump_steps: int = 0
  in_bump: bool = False
  yellow_steps: int = 0         # steps the yellow flag was out
  events: list = field(default_factory=list)
  parked: list = field(default_factory=list)   # racers of the track model not on the grid: held still off the track

  def __post_init__(self):
    self.laps = min(max(self.laps if self.laps > 0 else self.track.default_laps, 1), 5) if self.track.closed else 1
    self.total = self.track.length * self.laps
    self.yellow = YellowFlag(self.yellow_flag)
    self.ahead = {}
    m = self.entries[0].racer.m
    self.roots = [int(m.body_rootid[e.racer.base]) for e in self.entries]
    self.auditor = ContactAudit(m, self.entries) if self.audit else None
    self.draw()

  # --- grid ----------------------------------------------------------------------------------------------------------
  def draw(self):
    """The grid's impratio, lanes and speeds for this race (from the seed), every racer on its grid slot (its head
    start ahead with the handicap), the rest parked."""
    m = self.entries[0].racer.m
    m.opt.impratio = min(e.impratio for e in self.entries)
    rng = SplitMix64(self.seed)
    lanes = self.track.lane_offsets(len(self.entries))
    if self.randomize_grid:
      lanes = rng.shuffle(lanes)
    fastest = 0.0
    for e, lane in zip(self.entries, lanes):
      e.lane = lane
      e.speed = e.cruise * (1.0 - SPEED_SPREAD * rng.uniform())
      fastest = max(fastest, e.speed * e.pace)
    for e in self.entries:
      e.aggression = rng.uniform()
      # a head start that makes every expected finish time equal (Unity's, with the speed it actually holds); at most
      # half the race
      e.head_start = min(0.5 * self.total, self.total * (1.0 - e.speed * e.pace / fastest)) if self.handicap else 0.0
      e.distance = e.head_start
      e.lap = int(e.head_start / self.track.length) if self.track.closed else 0
      e.lateral = e.lane
      self.spawn(e, e.head_start)
      e.racer.reset_to_spawn()
    x0 = min(p[0] for p in self.track.points) - 40.0
    y0 = min(p[1] for p in self.track.points) - 40.0
    for k, r in enumerate(self.parked):
      r.spawn = (x0, y0 + 3.0 * k, r.home_height + 5.0)
      r.spawn_yaw = 0.0
      r.reset_to_spawn()

  def hold_parked(self):
    """Parked racers float still 5 m above the floor, 40 m off the track: never a contact, never a brain."""
    for r in self.parked:
      d = r.d
      x, y, z = r.spawn
      d.qpos[r.root_q:r.root_q + 7] = [x, y, z, 1.0, 0.0, 0.0, 0.0]
      d.qvel[r.root_v:r.root_v + 6] = 0
      d.qvel[r.vadr] = 0

  def spawn(self, e, s):
    """Where a reset puts this racer: its lane at arc length s, facing along the track."""
    e.spawn_s = s
    p, t = self.track.lane_point(s, e.lane)
    lat = (p[0] - self.track.point_at(s)[0][0]) * left(t)[0] + (p[1] - self.track.point_at(s)[0][1]) * left(t)[1]
    bank = math.radians(abs(self.track.bank_at(s)))
    z = e.racer.home_height + self.track.surface_height(s, lat) + 0.2 * math.tan(bank)
    e.racer.spawn = (p[0], p[1], z)
    e.racer.spawn_yaw = math.atan2(t[1], t[0])

  def resync(self, e):
    """After a reset: the progress walk restarts at the spawn's segment. It only walks forward, so from the segment the
    racer had reached it measured a racer put back on a curve as off the track, and reset it again every step
    (Flat Oval with the handicap, seed 3: 124075 off-track resets; the Unity rules have the same walk)."""
    e.segment = self.track.segment_at(e.spawn_s)
    e.lap = int(e.spawn_s / self.track.length) if self.track.closed else 0

  # --- progress ------------------------------------------------------------------------------------------------------
  def progress(self, e, pos):
    """Metres raced (laps included), walking e.segment forward; also the lateral offset from the centre line."""
    tr = self.track
    t, ln, a, d = 0.0, 1.0, (0.0, 0.0), (1.0, 0.0)
    for _ in range(tr.n + 1):
      a, b = tr.P(e.segment), tr.P(e.segment + 1)
      dx, dy = b[0] - a[0], b[1] - a[1]
      ln = math.sqrt(dx * dx + dy * dy)
      d = (dx / ln, dy / ln)
      t = (pos[0] - a[0]) * d[0] + (pos[1] - a[1]) * d[1]
      if t <= ln:
        break
      if e.segment + 1 < tr.n:
        e.segment += 1
      elif tr.closed:
        e.segment = 0
        e.lap += 1
      else:
        break
    l = left(d)
    lateral = (pos[0] - a[0]) * l[0] + (pos[1] - a[1]) * l[1]
    along = min(max(t, 0.0), ln) if tr.closed else max(0.0, t)
    return e.lap * tr.length + tr.cum[e.segment] + along, lateral

  def race_time(self):
    return (self.step - self.race_start) * DT if self.race_start >= 0 else 0.0

  def standings(self):
    key = lambda e: 1e6 - e.finish_time if e.finish_time >= 0 else e.distance  # noqa: E731
    return sorted(self.entries, key=key, reverse=True)   # stable: ties keep grid order

  def detect_overtakes(self):
    """Pairwise 'who is ahead' with 0.25 m hysteresis, so two racers side by side do not count passes every step."""
    n = len(self.entries)
    for i in range(n):
      for j in range(i + 1, n):
        a, b = self.entries[i], self.entries[j]
        if a.finish_time >= 0 or b.finish_time >= 0:
          continue
        dd = a.distance - b.distance
        now = 1 if dd > OVERTAKE_HYST else -1 if dd < -OVERTAKE_HYST else 0
        if now == 0:
          continue
        before = self.ahead.get((i, j))
        if before is not None and before != now:
          passer, passed = (a, b) if now > 0 else (b, a)
          passer.passes += 1
          self.events.append((self.step, "pass", passer.name, passed.name))
        self.ahead[(i, j)] = now

  def count_bumps(self, m, d):
    """Robot-robot contact this step (the bump itself is pure solver contact; this only counts it)."""
    roots = self.roots
    hit = False
    for i in range(d.ncon):
      c = d.contact[i]
      r1, r2 = int(m.body_rootid[m.geom_bodyid[c.geom[0]]]), int(m.body_rootid[m.geom_bodyid[c.geom[1]]])
      if r1 != r2 and r1 in roots and r2 in roots:
        hit = True
        break
    if hit:
      self.bump_steps += 1
      if not self.in_bump:
        self.bumps += 1
        self.in_bump = True
    else:
      self.in_bump = False

  # --- one physics step ----------------------------------------------------------------------------------------------
  def pre_step(self):
    """The rules for this step. Call before mj_step; then each racer's control(), then mj_step."""
    m, d = self.entries[0].racer.m, self.entries[0].racer.d
    if self.phase == COUNTDOWN and self.step >= self.intro_steps + COUNTDOWN_STEPS:
      self.phase = RACING_PHASE
      self.race_start = self.step
    rt = self.race_time()
    if self.phase == RACING_PHASE and 0 <= self.flip_at <= rt:
      self.flip_at = -1.0
      order = [e for e in self.standings() if e.finish_time < 0]
      for e in order[:self.flip_count]:
        e.racer.knock_over()
        self.flips += 1
    if self.auditor and self.phase == RACING_PHASE:
      self.auditor.step(m, d)

    self.hold_parked()
    for i, e in enumerate(self.entries):
      r = e.racer
      was = e.state
      if r.update_state():
        self.resync(e)
      e.state = r.state
      if self.phase == RACING_PHASE and e.finish_time < 0:
        if e.state == FALLEN and was != FALLEN:
          e.falls += 1
          e.down = True
          self.events.append((self.step, "fell", e.name))
        if e.state == RACING and e.down:
          e.down = False
          self.events.append((self.step, "up", e.name))
      if self.phase == COUNTDOWN and e.holds_heading:
        _, t0 = self.track.point_at(e.head_start)
        e0 = math.remainder(math.atan2(t0[1], t0[0]) - r.yaw(), 2.0 * math.pi)
        r.target[:] = (0.0, 0.0, min(max(STEER_GAIN * e0, -e.max_yaw), e.max_yaw))
        continue
      if self.phase != RACING_PHASE or e.finish_time >= 0:
        r.target[:] = 0
        continue

      pos = r.pos()
      dist, lateral = self.progress(e, pos)
      e.distance, e.lateral = min(dist, self.total), lateral
      if dist >= self.total:
        e.finish_time = rt
        self.finished += 1
        e.place = self.finished
        if self.first_finish < 0:
          self.first_finish = self.step
        r.target[:] = 0
        continue
      cp = math.floor(dist / self.track.checkpoint_spacing)
      if cp > e.checkpoint:
        e.checkpoint = cp
        self.spawn(e, cp * self.track.checkpoint_spacing)

      # Lane choice: the racing line (lane x the lap's squeeze) plus this racer's tactical offset, slewed at 0.6 m/s.
      # Banks are a no-manoeuvre zone (sideways moves on the bank stalled the slope brain uphill: Unity F.8).
      tr = self.track
      line = e.lane * tr.lane_scale(dist)
      banked = abs(tr.bank_at(dist)) > 0.5 or abs(tr.bank_at(dist + tr.look_ahead)) > 0.5
      if self.tactics:
        e.offset = move_towards(e.offset, 0.0 if banked else tactic(self.entries, i, line, tr.half_width) - line, OFFSET_SLEW)
      if banked:
        e.intent, e.passing = "", -1
      tp, tan = tr.lane_point(dist + tr.look_ahead, e.lane)
      lt = left(tan)
      tx, ty = tp[0] + lt[0] * e.offset, tp[1] + lt[1] * e.offset
      err = math.remainder(math.atan2(ty - pos[1], tx - pos[0]) - r.yaw(), 2.0 * math.pi)
      yaw_rate = min(max(STEER_GAIN * err, -e.max_yaw), e.max_yaw)
      lat_err = line + e.offset - lateral
      vy = min(max(lat_err, -MAX_LATERAL), MAX_LATERAL) if self.tactics and not banked and abs(lat_err) > 0.1 and abs(err) < 0.5 else 0.0
      vx = e.speed * (YELLOW_SCALE if self.yellow.out else 1.0) * max(0.3, math.cos(err))
      stuck = e.uses_unstick and r.locomoting and float(r.cmd[0]) > 1.0 and r.planar_speed2() < STUCK_SPEED * STUCK_SPEED
      e.stuck_steps = e.stuck_steps + 1 if stuck else 0
      if e.stuck_steps > STUCK_STEPS:
        r.restart_command_ramp()
        e.stuck_steps = 0
        e.unsticks += 1
        e.unstick_chain = e.unstick_chain + 1 if dist - e.unstick_dist < 0.3 else 1
        e.unstick_dist = dist
        if e.unstick_chain >= 6:
          e.backoff_steps, e.unstick_chain = BACKOFF_STEPS, 0
          e.backoffs += 1
      if e.backoff_steps > 0:
        e.backoff_steps -= 1
        vx, vy = -0.5, 0.0
      r.target[:] = (vx, vy, yaw_rate)
      if abs(lateral) > self.track.half_width + OFF_TRACK:
        r.reset_to_spawn()
        self.resync(e)
        e.off_track += 1

    if self.phase == RACING_PHASE:
      self.detect_overtakes()
    was_out = self.yellow.out
    self.yellow.update(self.step, self.phase == RACING_PHASE, len(self.entries),
                       sum(1 for e in self.entries if e.down and e.finish_time < 0))
    if self.yellow.out != was_out:
      self.events.append((self.step, "yellow" if self.yellow.out else "green"))
    if self.yellow.out:
      self.yellow_steps += 1
    if self.phase == RACING_PHASE and self.finished == len(self.entries):
      self.phase = FINISHED
    elif self.phase == RACING_PHASE and ((self.finish_window_steps > 0 and self.first_finish >= 0 and self.step - self.first_finish >= self.finish_window_steps)
                                         or self.step - self.race_start >= self.limit_steps):
      self.phase = FINISHED
      self.called = True
    if self.phase == RACING_PHASE:
      self.count_bumps(m, d)

  def control(self):
    for e in self.entries:
      e.racer.control()
    self.step += 1

  @property
  def over(self):
    return self.phase == FINISHED

  def result_line(self):
    """One line per race, the Unity -raceTest format, so old and new results diff."""
    ok = self.phase == FINISHED and not self.called
    rows = []
    for e in self.standings():
      t = f"{e.finish_time:.2f}s" if e.finish_time >= 0 else f"DNF@{e.distance:.0f}m"
      rows.append(f"{e.name} {t} lane={e.lane:.1f} v={e.speed:.2f}{f' head={e.head_start:.1f}m' if e.head_start > 0 else ''} "
                  f"resets={e.racer.resets} offtrack={e.off_track} "
                  f"unstuck={e.unsticks}{f' backoffs={e.backoffs}' if e.backoffs else ''} falls={e.falls} passes={e.passes}")
    yellow = f" yellows={self.yellow.count} yellowTime={self.yellow_steps * DT:.2f}s" if self.yellow.count else ""
    return (f"{'FINISHED' if ok else 'CALLED' if self.called and self.finished else 'DNF'} map={self.track.name} laps={self.laps} length={self.total:.1f}m seed={self.seed} | "
            + " | ".join(rows) + f" | flips={self.flips} bumps={self.bumps} bumpTime={self.bump_steps * DT:.2f}s{yellow}")
