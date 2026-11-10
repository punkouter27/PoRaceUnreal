"""The race rules, ported from the Unity MultiRaceOrchestrator. Source/PoRaceUnreal/RaceRules.cpp is the same code.

Per physics step, before mj_step (Unity ran this after the previous step: the same state):
  every racer's update_state(), then the rules for it, then every racer's control().
Tactics (passing, blocking) and the yellow flag arrive in Slice 5; this is the single-file race of Slice 2.
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
  lane: float = 0.0
  speed: float = 0.0
  aggression: float = 0.0
  distance: float = 0.0
  segment: int = 0
  lap: int = 0
  checkpoint: int = 0
  lateral: float = 0.0
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


@dataclass
class Race:
  track: Track
  entries: list
  seed: int
  laps: int = 1
  flip_at: float = -1.0
  randomize_grid: bool = True
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
  events: list = field(default_factory=list)
  parked: list = field(default_factory=list)   # racers of the track model not on the grid: held still off the track

  def __post_init__(self):
    self.laps = min(max(self.laps if self.laps > 0 else self.track.default_laps, 1), 5) if self.track.closed else 1
    self.total = self.track.length * self.laps
    self.draw()

  # --- grid ----------------------------------------------------------------------------------------------------------
  def draw(self):
    """The grid's impratio, lanes and speeds for this race (from the seed), every racer on its grid slot, the rest parked."""
    m = self.entries[0].racer.m
    m.opt.impratio = min(e.impratio for e in self.entries)
    rng = SplitMix64(self.seed)
    lanes = self.track.lane_offsets(len(self.entries))
    if self.randomize_grid:
      lanes = rng.shuffle(lanes)
    for e, lane in zip(self.entries, lanes):
      e.lane = lane
      e.speed = e.cruise * (1.0 - SPEED_SPREAD * rng.uniform())
    for e in self.entries:
      e.aggression = rng.uniform()
      self.spawn(e, 0.0)
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
    p, t = self.track.lane_point(s, e.lane)
    lat = (p[0] - self.track.point_at(s)[0][0]) * left(t)[0] + (p[1] - self.track.point_at(s)[0][1]) * left(t)[1]
    bank = math.radians(abs(self.track.bank_at(s)))
    z = e.racer.home_height + self.track.surface_height(s, lat) + 0.2 * math.tan(bank)
    e.racer.spawn = (p[0], p[1], z)
    e.racer.spawn_yaw = math.atan2(t[1], t[0])

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

  def leader(self):
    order = self.standings()
    return next((e for e in order if e.finish_time < 0), order[0])

  def standings(self):
    key = lambda e: 1e6 - e.finish_time if e.finish_time >= 0 else e.distance  # noqa: E731
    return sorted(self.entries, key=key, reverse=True)   # stable: ties keep grid order

  # --- one physics step ----------------------------------------------------------------------------------------------
  def pre_step(self):
    """The rules for this step. Call before mj_step; then each racer's control(), then mj_step."""
    if self.phase == COUNTDOWN and self.step >= self.intro_steps + COUNTDOWN_STEPS:
      self.phase = RACING_PHASE
      self.race_start = self.step
    rt = self.race_time()
    if self.phase == RACING_PHASE and 0 <= self.flip_at <= rt:
      self.flip_at = -1.0
      self.leader().racer.knock_over()
      self.flips += 1

    self.hold_parked()
    for e in self.entries:
      r = e.racer
      was = e.state
      r.update_state()
      e.state = r.state
      if self.phase == RACING_PHASE and e.finish_time < 0:
        if e.state == FALLEN and was != FALLEN:
          e.falls += 1
          e.down = True
        if e.state == RACING and e.down:
          e.down = False
      if self.phase == COUNTDOWN and e.holds_heading:
        _, t0 = self.track.point_at(0.0)
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

      tp, _ = self.track.lane_point(dist + self.track.look_ahead, e.lane)
      err = math.remainder(math.atan2(tp[1] - pos[1], tp[0] - pos[0]) - r.yaw(), 2.0 * math.pi)
      yaw_rate = min(max(STEER_GAIN * err, -e.max_yaw), e.max_yaw)
      vx = e.speed * max(0.3, math.cos(err))
      vy = 0.0
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
        e.off_track += 1

    if self.phase == RACING_PHASE and self.finished == len(self.entries):
      self.phase = FINISHED
    elif self.phase == RACING_PHASE and ((self.finish_window_steps > 0 and self.first_finish >= 0 and self.step - self.first_finish >= self.finish_window_steps)
                                         or self.step - self.race_start >= self.limit_steps):
      self.phase = FINISHED
      self.called = True

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
      rows.append(f"{e.name} {t} lane={e.lane:.1f} v={e.speed:.2f} resets={e.racer.resets} offtrack={e.off_track} "
                  f"unstuck={e.unsticks}{f' backoffs={e.backoffs}' if e.backoffs else ''} falls={e.falls} passes={e.passes}")
    return (f"{'FINISHED' if ok else 'CALLED' if self.called and self.finished else 'DNF'} map={self.track.name} laps={self.laps} length={self.total:.1f}m seed={self.seed} | "
            + " | ".join(rows) + f" | flips={self.flips}")
