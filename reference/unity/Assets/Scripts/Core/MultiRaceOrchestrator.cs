using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Mujoco;
using UnityEngine;
using UnityEngine.UI;

namespace PoRace {

public enum RacePhase { Countdown, Racing, Finished }

[Serializable]
public class Racer {
  public string name = "Racer";
  public Go2Controller controller;
  [Tooltip("Set instead of `controller` for a human racer (MattController: Matt or Grandma, its `human`).")]
  public MattController matt;
  /// <summary>The racing body, whichever creature it is.</summary>
  public IRacer Body => matt != null ? (IRacer)matt : controller;
  public AutoReset autoReset;
  [Tooltip("Root of this racer's MuJoCo subtree. Null for the first racer, which is always present.")]
  public GameObject mjRoot;
  public float cruiseSpeed = 1.5f;
  public Color color = Color.white;
  [NonSerialized] public float lane;           // lateral offset from the centerline, +left (m)
  [NonSerialized] public float speed;          // this race's cruise speed after the random draw
  [NonSerialized] public float distance;       // metres raced, laps included
  [NonSerialized] public float headStart;      // handicap start offset this race (m), 0 without -handicap
  [NonSerialized] public bool down;            // fell and not yet back to RACING (Recovered event)
  [NonSerialized] public int segment, lap, checkpoint, place;
  [NonSerialized] public double finishTime = -1;
  [NonSerialized] public RaceState state;
  [NonSerialized] public bool active = true;
  [NonSerialized] public float stuckFor; [NonSerialized] public int unsticks;
  [NonSerialized] public float unstickDist, backoff; [NonSerialized] public int unstickChain, backoffs;   // pinned-racer back-off (G.10)
  // Tactics (lane choice): offset is added to the racer's racing-line lane; intent is what the HUD arrow shows.
  [NonSerialized] public float lateral, offset, aggression;
  [NonSerialized] public string intent = "";
  [NonSerialized] public Racer passing;          // racer this one is trying to get past (null = none)
  [NonSerialized] public int falls, overtakes;
}

/// <summary>
/// Multi-racer race on any MapDefinition (PRD 4.2 / FR-13): N robots in ONE MuJoCo model, each driven by its own copy
/// of the validated locomotion + getup policies. Racers bump through solver contact only. Steering is the joystick
/// command: vx = cruise, yaw rate toward a look-ahead point on the racer's lane of the map centerline.
/// Lane draw and speed variation are random per race (seeded). MuJoCo frame: x, y on the ground, z up.
/// Headless: PoRace.exe -batchmode -nographics -raceTest [-timeScale 4] [-seed 7] [-racers 4 | -dogMask 5] [-matt] [-laps 2] [-raceFlipAt 20] [-noTactics]
/// </summary>
public unsafe class MultiRaceOrchestrator : MonoBehaviour {
  public MapDefinition map;
  public List<Racer> racers = new List<Racer>();
  public Text raceText, standingsText;
  public FollowCam followCam;
  /// <summary>The camera the broadcast layer draws for: the follow cam, else the main camera.</summary>
  public Camera ViewCamera => followCam != null ? followCam.GetComponent<Camera>() : Camera.main;
  public float countdownSeconds = 3f;
  public float steerGain = 1.5f;
  [Tooltip("Each race draws a cruise speed in [1 - speedSpread, 1] x the racer's cruiseSpeed.")]
  public float speedSpread = 0.06f;
  public bool randomizeGrid = true;

  [Tooltip("Lane choice: pass slower or fallen racers ahead, block a racer attacking from behind. Off = fixed lanes.")]
  public bool tactics = true;
  [Tooltip("Head starts so every racer's expected finish time is equal (-handicap, or the menu's Handicap chip).")]
  public bool handicap;
  [Tooltip("Max lateral command (m/s, body frame) used to move between lines; the policy was trained on |vy| <= 0.8.")]
  public float maxLateralCmd = 0.25f;
  [Tooltip("Proposals r3 A3: when 2+ racers are down at once, everyone still racing eases to yellowScale x cruise for up to " +
           "yellowSeconds (every policy is trained well below 0.8 x its cruise). Off in -raceTest unless -yellowFlag.")]
  public bool yellowFlag = true;
  public float yellowScale = 0.8f, yellowSeconds = 5f, yellowCooldown = 15f;

  // Race events for the broadcast layer (director, replay, audio, predictions, telemetry), raised from the physics
  // step (FixedUpdate, main thread).
  public event Action<Racer, Racer> Overtook;   // (passer, passed)
  public event Action<Racer> Fell, Recovered, Finished;
  public event Action<RacePhase> PhaseChanged;
  public event Action Restarted;
  /// <summary>Yellow flag out (true) / in (false).</summary>
  public event Action<bool> YellowChanged;
  public bool Yellow { get; private set; }
  /// <summary>-raceTest only: raised once before the player quits; listeners log their summary and may add a failed
  /// gate (the test then exits 4 instead of 0).</summary>
  public static event Action<MultiRaceOrchestrator> TestEnding;
  public static readonly List<string> TestGateFailures = new List<string>();
  /// <summary>Extra text appended to each standings row (strain marks, live win chance).</summary>
  public readonly List<Func<Racer, string>> standingsExtras = new List<Func<Racer, string>>();
  public IReadOnlyList<Racer> Live => _live;
  public float TotalLength => _total;
  /// <summary>Seconds left in the countdown (0 once racing). Holds at countdownSeconds while the racer intro runs.</summary>
  public float CountdownLeft => Phase == RacePhase.Countdown ? Mathf.Max(0f, countdownSeconds - Mathf.Max(0f, (float)(_sim - Math.Max(0, _t0)) - introSeconds)) : 0f;
  /// <summary>Racer intro before the countdown (RacerIntro sets it in Start; 0 in -raceTest and after a restart). The
  /// grid holds still on the start line meanwhile, exactly as in the countdown.</summary>
  [NonSerialized] public float introSeconds;
  /// <summary>Seconds of racer intro left (0 once the countdown runs).</summary>
  public float IntroLeft => Phase != RacePhase.Countdown ? 0f : _t0 < 0 ? introSeconds : Mathf.Max(0f, introSeconds - (float)(_sim - _t0));
  /// <summary>Ends the intro now: the countdown starts on the next physics step.</summary>
  public void SkipIntro() { introSeconds = _t0 < 0 ? 0f : Mathf.Min(introSeconds, (float)(_sim - _t0)); }
  [Tooltip("Interactive races: once the winner is home, the race is called this many seconds later (the rest DNF), so " +
           "the results card always comes up even when a racer cannot finish. Off in -raceTest.")]
  public float finishWindow = 60f;

  public RacePhase Phase { get; private set; } = RacePhase.Countdown;
  public double RaceTime { get; private set; }
  public int Laps { get; private set; } = 1;
  public int Seed { get; private set; }
  public int Bumps { get; private set; }
  public int BumpSteps { get; private set; }
  float _total; double _t0 = -1, _raceStart, _sim, _flipAt = -1; int _finished, _flips; bool _test, _testDone, _inBump;
  readonly System.Diagnostics.Stopwatch _sw = new System.Diagnostics.Stopwatch();
  double _stepMs, _maxMs; long _steps;
  List<Racer> _live = new List<Racer>();
  Transform _anchor; Vector3 _camForward = Vector3.right;

  void Awake() {
    int dogs = racers.Count(r => r.matt == null);
    int all = (1 << dogs) - 1, mask = RaceConfig.fromMenu ? RaceConfig.dogMask & all : all;
    bool matt = RaceConfig.fromMenu && RaceConfig.matt, grandma = RaceConfig.fromMenu && RaceConfig.grandma;
    int laps = RaceConfig.fromMenu ? RaceConfig.laps : 0; int seed = RaceConfig.fromMenu ? RaceConfig.seed : -1;
    if (RaceConfig.fromMenu && RaceConfig.handicap) handicap = true;
    // Time.timeScale outlives scene loads: a load during an instant replay (0) or an INCIDENT slow motion (0.4) - the
    // autoplay's next race, the Menu button - would otherwise freeze or slow the new race for good.
    Time.timeScale = 1f;
    if (CliArgs.RaceTest) _test = true;
    if (CliArgs.Has("-noTactics")) tactics = false;   // fixed lanes, as before tactics existed (regression runs)
    if (_test) yellowFlag = CliArgs.Has("-yellowFlag");   // regression races stay bit-identical to r2
    if (CliArgs.Has("-matt")) matt = true;
    if (CliArgs.Has("-grandma")) grandma = true;
    if (CliArgs.Has("-handicap")) handicap = true;
    if (CliArgs.TryFloat("-timeScale", out float ts)) Time.timeScale = ts;
    if (CliArgs.TryDouble("-raceFlipAt", out double flip)) _flipAt = flip;
    if (CliArgs.TryInt("-seed", out int sd)) seed = sd;
    // -racers and -dogMask both set the mask: the later flag on the line wins, as before
    bool hasRacers = CliArgs.TryInt("-racers", out int nr), dm = CliArgs.TryInt("-dogMask", out int dmv);
    if (hasRacers && (!dm || Array.LastIndexOf(CliArgs.All, "-racers") > Array.LastIndexOf(CliArgs.All, "-dogMask"))) mask = (1 << Mathf.Clamp(nr, 1, dogs)) - 1;
    else if (dm) mask = dmv & all;   // bit k = k-th dog of the roster (1 = Blue, 2 = Red, ...)
    if (CliArgs.TryInt("-laps", out int lp)) laps = lp;
    Laps = map.closed ? Mathf.Clamp(laps > 0 ? laps : map.defaultLaps, 1, 5) : 1;
    _total = map.Length * Laps;
    Seed = seed >= 0 ? seed : Environment.TickCount & 0xFFFF;
    // Matt's policy is trained on flat ground only (training/matt/env.py): no banks, no obstacles.
    if (matt && map.terrain != "flat") { Debug.Log($"[Race] Matt sits out {map.displayName} ({map.terrain}): flat-ground policy"); matt = false; }
    if (grandma && map.terrain != "flat") { Debug.Log($"[Race] Grandma sits out {map.displayName} ({map.terrain}): flat-ground policy"); grandma = false; }
    if (grandma && !racers.Any(r => r.matt != null && r.matt.human == Human.Grandma)) { Debug.Log("[Race] no Grandma in this scene"); grandma = false; }
    // One MuJoCo model for all racers. Matt trained at impratio 1 (at the dogs' 100 a 90 kg body's floor forces explode,
    // rl_optimization_log.md); with him on the grid the shared model compiles at 1, the dogs' gates at 1: R0 / R2 10/10,
    // R1 9/10. Dogs-only races keep 100.
    if (matt || grandma) { var gs = MjGlobalSettings.Instance; var o = gs.GlobalOptions; o.ImpRatio = MattSpec.ImpRatio; gs.GlobalOptions = o; }   // both humans: impratio 1
    if (mask == 0 && !matt && !grandma) mask = 1;   // never an empty grid (e.g. Matt alone picked, then a banked map)

    // Racers not on the grid are removed from the MuJoCo model before MjScene compiles it (in Start): the dogs picked on
    // the menu roster (RaceConfig.dogMask) race, Matt joins when picked (-matt).
    for (int i = 0, k = 0; i < racers.Count; i++) {
      if (RaceConfig.fromMenu && racers[i].matt == null && k < RaceConfig.Dogs.Length) racers[i].name = RaceConfig.Dogs[k].name;
      racers[i].active = racers[i].matt != null ? (racers[i].matt.human == Human.Grandma ? grandma : matt) : (mask >> k++ & 1) != 0;
      if (racers[i].active) continue;
      if (racers[i].mjRoot == null) { Park(racers[i]); continue; }
      racers[i].mjRoot.SetActive(false); racers[i].Body.gameObject.SetActive(false);
      // A human's skinned body is a separate visual root (MattBuilder) that MattSkin poses; off the grid it would stand
      // in its bind pose on the start line, so it goes too.
      if (racers[i].matt != null)
        foreach (var sk in FindObjectsByType<MattSkin>(FindObjectsInactive.Include, FindObjectsSortMode.None))
          if (sk.visual != null && (sk.controller == racers[i].matt || (sk.controller == null && racers[i].matt.human == Human.Matt))) sk.visual.gameObject.SetActive(false);
    }
    for (int i = 0; i < racers.Count; i++) racers[i].color = RacerPalette.Get(i, racers[i].color);   // colour-blind set if on
    _live = racers.Where(r => r.active).ToList();
    Draw();
    MjScene.Instance.preUpdateEvent += (s, a) => _sw.Restart();
    MjScene.Instance.postUpdateEvent += OnPostStep;
  }

  void Start() {
    TrackZBufferFix.Apply(this);
  }

  /// <summary>The first dog's bodies are the base of the shared MuJoCo model (no mjRoot to remove) and its GameObject
  /// carries the HUD telemetry and the cube pool, so off the grid it stays in the model: hidden, holding its home pose
  /// on the floor plane 40 m outside the track.</summary>
  void Park(Racer r) {
    var lo = map.PointAt(0f, out _);
    for (float s = 0f; s < map.Length; s += 2f) lo = Vector2.Min(lo, map.PointAt(s, out _));
    r.Body.SpawnMj = new Vector3(lo.x - 40f, lo.y - 40f, r.Body.HomeHeight);
    foreach (var rend in r.Body.BaseTransform.GetComponentsInChildren<Renderer>()) rend.enabled = false;
  }

  /// <summary>Random lane draw and speed variation for this race, reproducible from Seed.</summary>
  void Draw() {
    var rng = new System.Random(Seed); _orderFrame = -1;
    var lanes = map.LaneOffsets(_live.Count).ToList();
    if (randomizeGrid) lanes = lanes.OrderBy(_ => rng.Next()).ToList();
    float fastest = 0f;
    for (int i = 0; i < _live.Count; i++) {
      _live[i].lane = lanes[i];
      _live[i].speed = _live[i].cruiseSpeed * (1f - speedSpread * (float)rng.NextDouble());
      fastest = Mathf.Max(fastest, _live[i].speed);
    }
    foreach (var r in _live) {
      // Handicap: a head start that makes every expected finish time equal (Matt walks ~0.8 m/s, the dogs ~1.5).
      r.headStart = handicap ? Mathf.Min(0.5f * _total, _total * (1f - r.speed / fastest)) : 0f;
      // Progress() walks segments forward from 0 within the current lap, so a head start of a lap or more sets the lap
      r.distance = r.headStart; r.segment = 0; r.lap = map.closed ? (int)(r.headStart / map.Length) : 0; r.checkpoint = 0; r.finishTime = -1; r.place = 0; r.stuckFor = 0; r.unsticks = 0;
      r.unstickDist = 0; r.backoff = 0; r.unstickChain = 0; r.backoffs = 0;
      r.offset = 0; r.lateral = r.lane; r.intent = ""; r.passing = null; r.falls = 0; r.overtakes = 0; r.state = RaceState.RACING; r.down = false;
      Spawn(r, r.headStart);
    }
    // Drawn after the grid so the lane / speed draw of a seed stays exactly as before.
    foreach (var r in _live) r.aggression = (float)rng.NextDouble();
    _ahead.Clear();
  }

  void Spawn(Racer r, float s) {
    var p = map.LanePoint(s, r.lane, out var t);
    // On a bank the uphill feet of a level-spawned dog would start inside the surface: lift by the slope over the stance.
    float lateral = Vector2.Dot(p - map.PointAt(s, out _), MapDefinition.Left(t)), bank = Mathf.Abs(map.BankAt(s)) * Mathf.Deg2Rad;
    // Obstacles (steeplechase): spawn 10 cm above the tallest block under the stance and drop onto it, as in training.
    float block = map.ObstacleHeightAt(p, 0.45f); if (block > 0f) block += 0.1f;
    r.Body.SpawnMj = new Vector3(p.x, p.y, r.Body.HomeHeight + map.SurfaceHeight(s, lateral) + 0.2f * Mathf.Tan(bank) + block);
    r.Body.SpawnYaw = Mathf.Atan2(t.y, t.x);
  }

  double _yellowSince = -1, _yellowEnd = -1e9;
  /// <summary>A3 yellow flag: out when 2+ racers are down mid-race (3+ on the grid), in when fewer than 2 are down or
  /// after yellowSeconds; then a cooldown so a long pile-up doesn't hold the field back for good.</summary>
  void UpdateYellow() {
    int down = 0; foreach (var r in _live) if (r.down && r.finishTime < 0) down++;
    bool want = yellowFlag && Phase == RacePhase.Racing && _live.Count >= 3 && down >= 2;
    if (!Yellow && want && _sim - _yellowEnd > yellowCooldown) { Yellow = true; _yellowSince = _sim; YellowChanged?.Invoke(true); }
    else if (Yellow && (down < 2 || _sim - _yellowSince > yellowSeconds || Phase != RacePhase.Racing)) { Yellow = false; _yellowEnd = _sim; YellowChanged?.Invoke(false); }
  }

  public void Restart() {
    Phase = RacePhase.Countdown; _t0 = -1; RaceTime = 0; _finished = 0; Bumps = 0; BumpSteps = 0; _firstFinish = -1; _overFor = 0;
    introSeconds = 0f; _firstFinishSim = -1;   // a restart goes straight to the countdown
    if (Yellow) { Yellow = false; YellowChanged?.Invoke(false); }
    _yellowEnd = -1e9;
    Seed = (Seed * 1103515245 + 12345) & 0xFFFF;   // a new draw each restart
    Draw();
    foreach (var r in _live) { r.Body.StartLocomotion(); r.Body.ResetToHome(); }
    Restarted?.Invoke(); PhaseChanged?.Invoke(Phase);
  }

  /// <summary>Advance the racer's segment so its projection stays inside it; returns metres raced including laps.</summary>
  float Progress(Racer r, Vector2 pos, out float lateral) {
    int n = map.SegmentCount; float t = 0, len = 1; Vector2 dir = Vector2.right, a = Vector2.zero;
    for (int guard = 0; guard < n + 1; guard++) {
      a = map.P(r.segment); dir = (map.P(r.segment + 1) - a); len = dir.magnitude; dir /= len;
      t = Vector2.Dot(pos - a, dir);
      if (t <= len) break;
      if (r.segment + 1 < n) r.segment++;
      else if (map.closed) { r.segment = 0; r.lap++; }
      else break;   // past the end of an open track
    }
    lateral = Vector2.Dot(pos - a, MapDefinition.Left(dir));
    float along = map.closed ? Mathf.Clamp(t, 0f, len) : Mathf.Max(0f, t);
    return r.lap * map.Length + map.SegmentStart(r.segment) + along;
  }

  void OnPostStep(object sender, MjStepArgs a) {
    double ms = _sw.Elapsed.TotalMilliseconds;
    var d = a.data; double t = d->time; _sim = t;
    if (_live.Count == 0) return;
    foreach (var r in _live) if (!r.Body.Ready) return;
    if (t > 1.0) { _stepMs += ms; _steps++; if (ms > _maxMs) _maxMs = ms; }
    if (_t0 < 0) _t0 = t;

    if (Phase == RacePhase.Countdown && t - _t0 >= introSeconds + countdownSeconds) { Phase = RacePhase.Racing; _raceStart = t; PhaseChanged?.Invoke(Phase); }
    if (Phase == RacePhase.Racing) RaceTime = t - _raceStart;
    if (Phase == RacePhase.Racing && _flipAt >= 0 && RaceTime >= _flipAt) { _flipAt = -1; Leader().Body.KnockOver(); _flips++; }

    foreach (var r in _live) {
      var c = r.Body;
      var pos = new Vector2((float)d->qpos[c.BaseQpos], (float)d->qpos[c.BaseQpos + 1]);
      float yaw = (float)RacerMath.Yaw(d->qpos, c.BaseQpos);
      var was = r.state;
      r.state = r.autoReset != null ? r.autoReset.State : RaceState.RACING;
      if (Phase == RacePhase.Racing && r.finishTime < 0) {
        if (r.state == RaceState.FALLEN_RECOVERING && was != RaceState.FALLEN_RECOVERING) { r.falls++; r.down = true; Fell?.Invoke(r); }
        // a real getup passes FALLEN -> STUMBLE -> RACING: recovered on the first RACING after a fall
        if (r.state == RaceState.RACING && r.down) { r.down = false; Recovered?.Invoke(r); }
      }
      if (Phase == RacePhase.Countdown && c.HoldsHeadingAtRest) {
        // A policy that drifts on a zero command (Matt: 15-60 deg left in 3 s) holds the track heading through the
        // countdown instead, so it starts pointing the right way.
        map.PointAt(r.headStart, out var t0);
        float e0 = Mathf.DeltaAngle(yaw * Mathf.Rad2Deg, Mathf.Atan2(t0.y, t0.x) * Mathf.Rad2Deg) * Mathf.Deg2Rad;
        c.Command = new Vector3(0f, 0f, Mathf.Clamp(steerGain * e0, -c.MaxYawRate, c.MaxYawRate)); continue;
      }
      if (Phase == RacePhase.Countdown || r.finishTime >= 0) { c.Command = Vector3.zero; continue; }
      if (Phase == RacePhase.Finished) { c.Command = Vector3.zero; continue; }   // called by finishWindow: DNF, stand down

      float dist = Progress(r, pos, out float lateral);
      r.distance = Mathf.Min(dist, _total); r.lateral = lateral;
      if (dist >= _total) { r.finishTime = RaceTime; r.place = ++_finished; if (_finished == 1) _firstFinishSim = RaceTime; c.Command = Vector3.zero; Finished?.Invoke(r); continue; }
      int cp = Mathf.FloorToInt(dist / map.checkpointSpacing);
      if (cp > r.checkpoint) { r.checkpoint = cp; Spawn(r, cp * map.checkpointSpacing); }

      // Lane choice: the racing line (lane x the map's squeeze) plus this racer's tactical offset, slewed at 0.6 m/s.
      // Banked sections are a no-manoeuvre zone: the slope policy's weak spot is restarting uphill from a standstill
      // (rl_optimization_log.md, F.8), and sideways moves on the bank caused exactly that (Banked Oval seed 2 DNF).
      float line = LineAt(r, dist); bool banked = Mathf.Abs(map.BankAt(dist)) > 0.5f || Mathf.Abs(map.BankAt(dist + map.lookAhead)) > 0.5f;
      if (tactics) r.offset = Mathf.MoveTowards(r.offset, banked ? 0f : Tactic(r, line) - line, 0.6f * Go2Controller.SimDt);
      if (banked) { r.intent = ""; r.passing = null; }
      var target = map.LanePoint(dist + map.lookAhead, r.lane, out var tanAhead) + MapDefinition.Left(tanAhead) * r.offset;
      float err = Mathf.DeltaAngle(yaw * Mathf.Rad2Deg, Mathf.Atan2(target.y - pos.y, target.x - pos.x) * Mathf.Rad2Deg) * Mathf.Deg2Rad;
      // Small sideways step toward the chosen line (body frame ~ track frame while the heading error is small).
      float latErr = line + r.offset - lateral;
      float latCmd = tactics && !banked && Mathf.Abs(latErr) > 0.1f && Mathf.Abs(err) < 0.5f ? Mathf.Clamp(latErr, -maxLateralCmd, maxLateralCmd) : 0f;
      float yawMax = c.MaxYawRate;   // the policy's trained yaw-rate envelope
      c.Command = new Vector3(r.speed * (Yellow ? yellowScale : 1f) * Mathf.Max(0.3f, Mathf.Cos(err)), latCmd, Mathf.Clamp(steerGain * err, -yawMax, yawMax));
      // Un-stick: upright, asked to go fast, but (nearly) stopped for half a second -> restart the command ramp.
      float vx = (float)d->qvel[c.BaseDof], vy = (float)d->qvel[c.BaseDof + 1];
      bool stuck = c.UsesUnstick && c.Locomoting && c.FilteredCommand.x > 1.0f && vx * vx + vy * vy < 0.3f * 0.3f;
      r.stuckFor = stuck ? r.stuckFor + Go2Controller.SimDt : 0f;
      if (r.stuckFor > 0.5f) {
        c.RestartCommandRamp(); r.stuckFor = 0f; r.unsticks++;
        // Pinned (six restarts in a row, under 0.3 m gained): restarting from a standstill against an 8 cm hurdle never
        // clears it (Steeplechase seed 3, Blue at 90 m: 796 restarts, DNF). Back off ~0.6 m, then come again with a run-up.
        r.unstickChain = dist - r.unstickDist < 0.3f ? r.unstickChain + 1 : 1; r.unstickDist = dist;
        if (r.unstickChain >= 6) { r.backoff = 1.2f; r.unstickChain = 0; r.backoffs++; }
      }
      if (r.backoff > 0f) { r.backoff -= Go2Controller.SimDt; c.Command = new Vector3(-0.5f, 0f, Mathf.Clamp(steerGain * err, -yawMax, yawMax)); }
      if (Mathf.Abs(lateral) > map.halfWidth + 1f) c.ResetToHome();   // left the track: back to the last checkpoint
    }
    if (Phase == RacePhase.Racing) DetectOvertakes();
    UpdateYellow();
    if (Phase == RacePhase.Racing && _finished == _live.Count) { Phase = RacePhase.Finished; PhaseChanged?.Invoke(Phase); }
    // Interactive: call the race finishWindow s after the winner (a fallen human may never finish), so it always ends.
    float winWindow = (Tournament.InMatch || Tournament.InMassRace) ? Mathf.Min(finishWindow, 3.5f) : finishWindow;
    if (!_test && winWindow > 0f && Phase == RacePhase.Racing && _finished > 0 && RaceTime - _firstFinishSim > winWindow) { Phase = RacePhase.Finished; PhaseChanged?.Invoke(Phase); }

    // Robot-vs-robot contacts this step (bump mechanics are pure solver contact; this only counts them).
    if (Phase == RacePhase.Racing) {
      var m = a.model; bool any = false;
      for (int i = 0; i < d->ncon; i++) {
        int b1 = m->body_rootid[m->geom_bodyid[d->contact[i].geom1]], b2 = m->body_rootid[m->geom_bodyid[d->contact[i].geom2]];
        if (b1 != b2 && IsRobotRoot(b1) && IsRobotRoot(b2)) { any = true; break; }
      }
      if (any) { BumpSteps++; if (!_inBump) { Bumps++; _inBump = true; } } else _inBump = false;
    }

    if (_test && !_testDone && (Phase == RacePhase.Finished || RaceTime > 600)) {
      _testDone = true;
      bool ok = Phase == RacePhase.Finished;
      Debug.Log($"[Race4] {(ok ? "FINISHED" : "DNF")} map={map.displayName} laps={Laps} length={_total:F1}m seed={Seed} | " + string.Join(" | ", Standings().Select(r =>
          $"{r.name} {(r.finishTime >= 0 ? r.finishTime.ToString("F2", CultureInfo.InvariantCulture) + "s" : "DNF@" + r.distance.ToString("F0") + "m")} lane={r.lane:F1} v={r.speed:F2} resets={(r.autoReset != null ? r.autoReset.Resets : 0)} unstuck={r.unsticks}{(r.backoffs > 0 ? " backoffs=" + r.backoffs : "")} falls={r.falls} passes={r.overtakes}"))
          + $" | flips={_flips} bumps={Bumps} bumpTime={BumpSteps * Go2Controller.SimDt:F2}s");
      double mean = _steps > 0 ? _stepMs / _steps : 0;
      Debug.Log($"[Perf4] {_live.Count} racers: physics step mean {mean:F4} ms max {_maxMs:F3} ms | per 50 Hz control step {mean * Go2Controller.Decimation:F3} ms (budget 5.0)");
      TestEnding?.Invoke(this);
      if (TestGateFailures.Count > 0) Debug.LogError("[RaceTest] gate failures: " + string.Join("; ", TestGateFailures));
      Application.Quit(!ok ? 1 : TestGateFailures.Count > 0 ? 4 : 0);
    }
  }

  /// <summary>Lateral position of the racer's racing line at arc length s (lane x the lap's squeeze).</summary>
  float LineAt(Racer r, float s) {
    float u = map.closed ? Mathf.Repeat(s, map.Length) / map.Length : Mathf.Clamp01(s / map.Length);
    return r.lane * map.laneScale.Evaluate(u);
  }

  const float PassGap = 0.65f, Margin = 0.45f;

  /// <summary>Where this racer wants to be across the track (lateral, + left). Pass a slower or fallen racer that is
  /// up to 2.5 m (5 m if it is down) ahead and in the way, on the side with more room; an aggressive racer with an
  /// attacker within 1.5 m behind moves across to cover that line. Otherwise hold the racing line.</summary>
  float Tactic(Racer r, float line) {
    float edge = map.halfWidth - Margin, me = line + r.offset;
    if (r.state != RaceState.RACING) { r.intent = ""; r.passing = null; return me; }   // no manoeuvres while stumbling
    Racer block = null; float bestGap = float.MaxValue;
    foreach (var o in _live) {
      if (o == r || o.finishTime >= 0) continue;
      float ds = o.distance - r.distance; bool down = o.state != RaceState.RACING;
      if (ds <= 0f || ds > (down ? 5f : 2.5f) || Mathf.Abs(o.lateral - me) > (down ? 0.8f : 0.55f)) continue;
      if ((down || o.speed < r.speed - 0.01f) && ds < bestGap) { bestGap = ds; block = o; }
    }
    if (block != null) {
      float gap = block.state != RaceState.RACING ? 0.85f : PassGap;
      float left = block.lateral + gap, right = block.lateral - gap;
      float roomL = left <= edge ? Room(r, left) : -1f, roomR = right >= -edge ? Room(r, right) : -1f;
      if (roomL >= 0f || roomR >= 0f) {
        bool goLeft = roomL > roomR || (Mathf.Approximately(roomL, roomR) && me >= block.lateral);
        r.passing = block; r.intent = block.state != RaceState.RACING ? "AVOID" : goLeft ? "PASS L" : "PASS R";
        return goLeft ? left : right;
      }
    }
    r.passing = null;
    if (r.aggression > 0.5f) {
      foreach (var p in _live) {
        if (p == r || p.passing != r) continue;
        float behind = r.distance - p.distance;
        if (behind > 0f && behind < 1.5f) { r.intent = "BLOCK"; return Mathf.Clamp(Mathf.Lerp(line, p.lateral, 0.4f), -edge, edge); }
      }
    }
    r.intent = "";
    return line;
  }

  /// <summary>Clearance (m) at a candidate lateral position from the nearest other racer within 3 m along the track.</summary>
  float Room(Racer r, float lat) {
    float best = 5f;
    foreach (var o in _live) if (o != r && o.finishTime < 0 && Mathf.Abs(o.distance - r.distance) < 3f) best = Mathf.Min(best, Mathf.Abs(o.lateral - lat));
    return best;
  }

  // Pairwise "who is ahead" with 0.25 m hysteresis, so two racers side by side do not fire overtakes every step.
  readonly Dictionary<(Racer, Racer), int> _ahead = new Dictionary<(Racer, Racer), int>();
  void DetectOvertakes() {
    for (int i = 0; i < _live.Count; i++) for (int j = i + 1; j < _live.Count; j++) {
      Racer a = _live[i], b = _live[j];
      if (a.finishTime >= 0 || b.finishTime >= 0) continue;
      float d = a.distance - b.distance; int now = d > 0.25f ? 1 : d < -0.25f ? -1 : 0;
      if (now == 0) continue;
      if (_ahead.TryGetValue((a, b), out int before) && before != now) {
        var passer = now > 0 ? a : b; var passed = now > 0 ? b : a; passer.overtakes++;
        Overtook?.Invoke(passer, passed);
      }
      _ahead[(a, b)] = now;
    }
  }

  bool IsRobotRoot(int body) { foreach (var r in _live) if (r.Body.BaseBody == body) return true; return false; }
  readonly List<Racer> _order = new List<Racer>(); int _orderFrame = -1;
  static float StandingKey(Racer r) => r.finishTime >= 0 ? 1e6f - (float)r.finishTime : r.distance;
  /// <summary>Live racers, best first. Outside the physics step the order is sorted once per rendered frame into a
  /// shared list (director, lighting, HUD); inside it (distances and finishes change between calls, rare callers)
  /// every call sorts into a new list.</summary>
  List<Racer> Standings() {
    if (Time.inFixedTimeStep) { var fresh = new List<Racer>(_live.Count); SortInto(fresh); return fresh; }
    if (_orderFrame != Time.frameCount) { _orderFrame = Time.frameCount; SortInto(_order); }
    return _order;
  }
  void SortInto(List<Racer> order) {
    order.Clear();
    foreach (var r in _live) {   // insertion sort: stable like OrderByDescending (ties keep grid order)
      int i = order.Count; float k = StandingKey(r);
      while (i > 0 && StandingKey(order[i - 1]) < k) i--;
      order.Insert(i, r);
    }
  }
  public Racer Leader() { var s = Standings(); foreach (var r in s) if (r.finishTime < 0) return r; return s[0]; }

  double _firstFinish = -1, _firstFinishSim = -1; float _overFor;

  /// <summary>Self-running app (RaceConfig.autoplay): a race ends when everyone is home, 45 s after the winner, or at
  /// 5 minutes (Matt cannot finish yet); 6 s later the next race loads.</summary>
  void AutoplayNext() {
    if (!RaceConfig.autoplay || _test) return;
    // 30 fps cap: re-applied here because the Mobile quality level (GfxTier) switches vsync back on when it loads
    if (QualitySettings.vSyncCount != 0 || Application.targetFrameRate != 30) { QualitySettings.vSyncCount = 0; Application.targetFrameRate = 30; }
    if (_firstFinish < 0 && _finished > 0) _firstFinish = RaceTime;
    bool over = Phase == RacePhase.Finished || (Phase == RacePhase.Racing && ((_firstFinish >= 0 && RaceTime - _firstFinish > 45) || RaceTime > 300));
    if (!over) return;
    _overFor += Time.unscaledDeltaTime;
    if (_overFor > 6f) { _overFor = float.NegativeInfinity; RaceConfig.LaunchNextAutoplay(); }
  }

  readonly List<Racer> _run = new List<Racer>();
  readonly System.Text.StringBuilder _sb = new System.Text.StringBuilder(); float _standingsNext;

  void Update() {
    TrackZBufferFix.EnsureFloorLowered();
    if (_live.Count == 0) return;
    AutoplayNext();
    var order = Standings();
    if (followCam != null) {
      // Frame the pack: an anchor at the mean position of the racers still running, looking along the track there.
      if (_anchor == null) {
        _anchor = new GameObject("PackAnchor").transform; followCam.target = _anchor;
        followCam.groundHeight = u => map.SurfaceHeightAt(new Vector2(u.x, u.z));   // Unity (x, z) = MuJoCo (x, y)
      }
      var run = _run; run.Clear();
      foreach (var r in order) if (r.finishTime < 0 && r.Body.BaseTransform != null) run.Add(r);
      if (run.Count == 0) foreach (var r in order) if (r.Body.BaseTransform != null) run.Add(r);
      if (run.Count > 0) {
        var sum = Vector3.zero; float dsum = 0; foreach (var r in run) { sum += r.Body.BaseTransform.position; dsum += r.distance; }
        _anchor.position = sum / run.Count;
        map.PointAt(dsum / run.Count, out var tan);
        _camForward = Vector3.Slerp(_camForward, new Vector3(tan.x, 0f, tan.y), 1f - Mathf.Exp(-2.5f * Time.deltaTime)).normalized;
        followCam.forward = _camForward;
      }
    }
    if (raceText != null && raceText.enabled) {   // PhaseBadge replaces it on the broadcast HUD
      string head = Phase == RacePhase.Countdown ? Mathf.CeilToInt(CountdownLeft).ToString()
                  : Phase == RacePhase.Racing ? "GO" : "FINISH";
      raceText.text = $"{head}\n{RaceTime:F2} s";
    }
    // Standings text at 10 Hz: rebuilding the rich-text rows (and the canvas mesh) every frame costs ~100 strings
    if (standingsText != null && standingsText.enabled && Time.unscaledTime >= _standingsNext) {   // StandingsChips replaces it
      _standingsNext = Time.unscaledTime + 0.1f;
      var sb = _sb; sb.Clear();
      for (int i = 0; i < order.Count; i++) {
        var r = order[i];
        string st = r.finishTime >= 0 ? r.finishTime.ToString("F2", CultureInfo.InvariantCulture) + " s"
                  : (map.closed ? $"L{Mathf.Min(r.lap + 1, Laps)}/{Laps}  " : "") + $"{r.distance:F0} m" + (r.state == RaceState.RACING ? "" : r.state == RaceState.STUMBLE ? "  stumble" : "  DOWN");
        sb.Append($"{i + 1}. {BroadcastUi.Paint(r.name, r.color)}  {st}");
        if (Phase == RacePhase.Countdown && r.headStart > 0.5f) sb.Append($"  +{r.headStart:F0} m start");
        foreach (var extra in standingsExtras) sb.Append(extra(r));
        sb.Append('\n');
      }
      sb.Append($"<size=18>{map.displayName}   bumps {Bumps}</size>");
      standingsText.text = sb.ToString();
    }
  }
}

/// <summary>Eliminates Z-buffer flickering (Z-fighting) across all race tracks without altering MuJoCo physics:
///   1. Lowers `go2_scene/floor` transform visually to y = -0.045 m in LateUpdate (after MjScene has compiled the
///      collision plane at z = 0 in Start), so the floor plane never Z-fights with the track surface or banks.
///   2. Replaces overlapping `tile_{i}_{t}`, `start_line`, and flat `mark_*` cubes with a single stitched 4-submesh
///      (TrackA, TrackB, Line, Marker) mitered ribbon mesh where every 5 m tile and every 30 cm start/checkpoint stripe
///      shares exact boundary vertices with 0.000 m overlap (zero coplanar surfaces).
///   3. Insets every odd rail visual mesh (`rail_L1`, `rail_R1`, ...) by 1.5 mm so overlapping rail joints never Z-fight.
///   4. Locks `Trackside` LODGroups to LOD0 (preserving static batching while avoiding decimated LOD1 Z-fighting) and
///      tightens camera near/far clip planes for optimal 24-bit depth precision.</summary>
public static class TrackZBufferFix {
  static Transform _floorTr;
  static bool _floorLowered;

  public static void Apply(MultiRaceOrchestrator race) {
    _floorLowered = false;
    _floorTr = null;
    if (race == null || race.map == null || BroadcastUi.Headless) return;

    var mjRoot = GameObject.Find("go2_scene");
    if (mjRoot != null) {
      _floorTr = mjRoot.transform.Find("floor");
      if (_floorTr != null) {
        var mr = _floorTr.GetComponent<MeshRenderer>();
        if (mr != null) mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
      }

      // Inset every odd rail's visual mesh by ~1.5 mm so overlapping rail corners/joints never Z-fight
      var railsTr = mjRoot.transform.Find("rails");
      if (railsTr != null) {
        for (int i = 0; i < railsTr.childCount; i++) {
          if ((i & 1) == 0) continue;
          var child = railsTr.GetChild(i);
          var rmf = child.GetComponent<MeshFilter>();
          if (rmf != null && rmf.sharedMesh != null && rmf.sharedMesh.isReadable) {
            var rmesh = UnityEngine.Object.Instantiate(rmf.sharedMesh);
            rmesh.name = child.name + "_vis_inset";
            var rv = rmesh.vertices;
            for (int k = 0; k < rv.Length; k++) {
              rv[k].x *= 0.994f;
              rv[k].y *= 0.994f;
              rv[k].z *= 0.965f;
            }
            rmesh.vertices = rv;
            rmesh.RecalculateBounds();
            rmf.sharedMesh = rmesh;
          }
        }
      }
    }

    // Replace overlapping tile_*, start_line, and flat mark_* cubes with a single stitched 4-submesh ribbon
    var vis = GameObject.Find("TrackVisuals");
    if (vis != null) {
      Material matA = null, matB = null, matLine = null, matMark = null;
      for (int i = 0; i < vis.transform.childCount; i++) {
        var ch = vis.transform.GetChild(i);
        string n = ch.name;
        var mr = ch.GetComponent<MeshRenderer>();
        if (n.StartsWith("tile_")) {
          if (mr != null) {
            if (matA == null) matA = mr.sharedMaterial;
            else if (matB == null && mr.sharedMaterial != matA) matB = mr.sharedMaterial;
            mr.enabled = false;
          }
        } else if (n == "start_line") {
          if (mr != null) {
            matLine = mr.sharedMaterial;
            mr.enabled = false;   // stitched into TrackRibbon_Seamless with 0 overlap
          }
        } else if (n.StartsWith("mark_")) {
          float s = 25f;
          float.TryParse(n.Substring(5), out s);
          bool onBank = Mathf.Abs(race.map.BankAt(s)) > 1e-3f;
          if (mr != null) {
            if (matMark == null) matMark = mr.sharedMaterial;
            if (!onBank) {
              mr.enabled = false;   // flat marks are stitched directly into TrackRibbon_Seamless with 0 overlap
            } else {
              var pos = ch.position;
              ch.position = new Vector3(pos.x, race.map.SurfaceHeight(s, 0f) + 0.015f, pos.z);
              var sc = ch.localScale;
              ch.localScale = new Vector3(0.30f, 0.006f, sc.z);
              mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            }
          }
        } else if (n.StartsWith("vis")) {
          var pos = ch.position;
          ch.position = new Vector3(pos.x, pos.y + 0.004f, pos.z);
        }
      }

      if (matA != null) {
        if (matB == null) matB = matA;
        if (matLine == null) matLine = matA;
        if (matMark == null) matMark = matLine;
        BuildSeamlessRibbon(race.map, vis.transform, matA, matB, matLine, matMark);
      }
    }

    // Replace Trackside stand meshes with clean non-overlapping geometry (matching tools/blender/trackside_props.py)
    // so the pre-baked static batch in sharedassets with coplanar side walls never Z-fights
    var trackside = GameObject.Find("Trackside");
    if (trackside != null) {
      Material baseLit = null;
      var visGo = GameObject.Find("TrackVisuals");
      if (visGo != null) {
        var anyMr = visGo.GetComponentInChildren<MeshRenderer>();
        if (anyMr != null) baseLit = anyMr.sharedMaterial;
      }
      Mesh standMesh = baseLit != null ? BuildCleanGrandstandMesh(baseLit, out Material[] standMats) : null;
      Material[] cachedStandMats = standMesh != null ? BuildGrandstandMaterials(baseLit) : null;

      for (int i = 0; i < trackside.transform.childCount; i++) {
        var prop = trackside.transform.GetChild(i);
        var lodGroup = prop.GetComponent<LODGroup>();
        var r0 = prop.Find("lod0")?.GetComponent<Renderer>();
        var r1 = prop.Find("lod1")?.GetComponent<Renderer>();
        if (prop.name == "stand" && standMesh != null && cachedStandMats != null) {
          if (r0 != null) r0.enabled = false;
          if (r1 != null) r1.enabled = false;
          if (lodGroup != null) lodGroup.enabled = false;
          var cleanGo = new GameObject("clean_stand");
          cleanGo.transform.SetParent(prop, false);
          cleanGo.AddComponent<MeshFilter>().sharedMesh = standMesh;
          var cmr = cleanGo.AddComponent<MeshRenderer>();
          cmr.sharedMaterials = cachedStandMats;
        } else if (lodGroup != null && r0 != null) {
          if (r1 != null) r1.enabled = false;
          lodGroup.SetLODs(new[] { new LOD(0.01f, new[] { r0 }) });
        }
      }
    }

    var cam = race.ViewCamera;
    if (cam != null) {
      if (cam.nearClipPlane < 0.3f) cam.nearClipPlane = 0.35f;
      if (cam.farClipPlane > 240f) cam.farClipPlane = 220f;
    }
  }

  /// <summary>Called from MultiRaceOrchestrator.Update after MjScene.Start has compiled the physics model at z = 0.</summary>
  public static void EnsureFloorLowered() {
    if (_floorLowered || _floorTr == null) return;
    _floorLowered = true;
    _floorTr.position = new Vector3(0f, -0.045f, 0f);
  }

  static Material[] BuildGrandstandMaterials(Material baseLit) {
    Material Make(string name, Color col) {
      var m = new Material(baseLit) { name = name };
      m.color = col;
      if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", col);
      return m;
    }
    return new[] {
      Make("StandConcrete", new Color(0.55f, 0.56f, 0.58f)),
      Make("StandRoof", new Color(0.90f, 0.91f, 0.94f)),
      Make("StandSteel", new Color(0.26f, 0.28f, 0.32f)),
      Make("SeatRed", new Color(0.84f, 0.16f, 0.12f)),
      Make("SeatBlue", new Color(0.14f, 0.38f, 0.84f)),
      Make("SeatYellow", new Color(0.95f, 0.76f, 0.12f))
    };
  }

  static Mesh BuildCleanGrandstandMesh(Material baseLit, out Material[] mats) {
    mats = null;
    var verts = new List<Vector3>();
    var norms = new List<Vector3>();
    var subTris = new List<int>[6];
    for (int i = 0; i < 6; i++) subTris[i] = new List<int>();

    void AddQuad(Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector3 n, int sub) {
      int k = verts.Count;
      verts.Add(a); verts.Add(b); verts.Add(c); verts.Add(d);
      norms.Add(n); norms.Add(n); norms.Add(n); norms.Add(n);
      subTris[sub].Add(k); subTris[sub].Add(k + 1); subTris[sub].Add(k + 2);
      subTris[sub].Add(k); subTris[sub].Add(k + 2); subTris[sub].Add(k + 3);
    }

    // Blender (bx, by, bz) maps to Unity (bx, bz, -by)
    void AddBox(Vector3 size, Vector3 centerBlender, int sub, float tiltXDeg = 0f) {
      Vector3 c = new Vector3(centerBlender.x, centerBlender.z, -centerBlender.y);
      Vector3 h = new Vector3(size.x * 0.5f, size.z * 0.5f, size.y * 0.5f);
      Quaternion rot = Mathf.Abs(tiltXDeg) > 1e-3f ? Quaternion.Euler(-tiltXDeg, 0f, 0f) : Quaternion.identity;
      Vector3 P(float sx, float sy, float sz) => c + rot * new Vector3(sx * h.x, sy * h.y, sz * h.z);

      // +Y top, -Y bottom, +Z front (facing track), -Z back, +X right, -X left (clockwise winding in Unity)
      AddQuad(P(-1, 1, -1), P(-1, 1, 1), P(1, 1, 1), P(1, 1, -1), rot * Vector3.up, sub);
      AddQuad(P(-1, -1, 1), P(-1, -1, -1), P(1, -1, -1), P(1, -1, 1), rot * Vector3.down, sub);
      AddQuad(P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1), P(-1, -1, 1), rot * Vector3.forward, sub);
      AddQuad(P(-1, -1, -1), P(-1, 1, -1), P(1, 1, -1), P(1, -1, -1), rot * Vector3.back, sub);
      AddQuad(P(1, -1, -1), P(1, 1, -1), P(1, 1, 1), P(1, -1, 1), rot * Vector3.right, sub);
      AddQuad(P(-1, -1, 1), P(-1, 1, 1), P(-1, 1, -1), P(-1, -1, -1), rot * Vector3.left, sub);
    }

    const float L = 6.0f, depth = 0.7f, rise = 0.45f, zLift = 0.008f;
    for (int t = 0; t < 3; t++) {
      float y0 = 0.3f + t * depth;
      float tierW = L - (2 - t) * 0.016f;
      float tierD = depth - 0.008f;
      float tierH = rise * (t + 1) - zLift;
      AddBox(new Vector3(tierW, tierD, tierH), new Vector3(0f, y0 + depth * 0.5f, zLift + tierH * 0.5f), 0);
      float seatH = 0.16f;
      float seatZ = zLift + tierH + seatH * 0.5f + 0.004f;
      AddBox(new Vector3(tierW - 0.2f, 0.22f, seatH), new Vector3(0f, y0 + 0.2f, seatZ), 3 + (t % 3));
    }
    float back = 0.3f + 3f * depth + 0.008f;
    float wallH = 3.0f - zLift;
    AddBox(new Vector3(L + 0.016f, 0.15f, wallH), new Vector3(0f, back + 0.075f, zLift + wallH * 0.5f), 0);
    foreach (float x in new[] { -L * 0.5f + 0.15f, L * 0.5f - 0.15f }) {
      foreach (float y in new[] { 0.15f, back - 0.02f }) {
        AddBox(new Vector3(0.12f, 0.12f, 3.08f), new Vector3(x, y, zLift + 1.54f), 2);
      }
    }
    AddBox(new Vector3(L + 0.4f, back + 0.5f, 0.1f), new Vector3(0f, back * 0.5f + 0.05f, 3.16f), 1, -6f);

    var mesh = new Mesh { name = "Grandstand_ZeroZFight", subMeshCount = 6 };
    mesh.SetVertices(verts);
    mesh.SetNormals(norms);
    for (int i = 0; i < 6; i++) mesh.SetTriangles(subTris[i], i);
    mesh.RecalculateBounds();
    return mesh;
  }

  static void BuildSeamlessRibbon(MapDefinition map, Transform visRoot, Material matA, Material matB, Material matLine, Material matMark) {
    var old = visRoot.Find("TrackRibbon_Seamless");
    if (old != null) UnityEngine.Object.Destroy(old.gameObject);

    int n = map.SegmentCount;
    float w = map.halfWidth + 0.15f;
    int vertsCount = map.closed ? n : n + 1;
    var centre = new List<Vector2>(vertsCount);
    var left = new List<Vector2>(vertsCount);
    var right = new List<Vector2>(vertsCount);

    for (int i = 0; i < vertsCount; i++) {
      Vector2 p = map.P(i);
      Vector2 dPrev = (map.closed || i > 0) ? (p - map.P(i - 1)).normalized : (map.P(i + 1) - p).normalized;
      Vector2 dNext = (map.closed || i < n) ? (map.P(i + 1) - p).normalized : dPrev;
      Vector2 nrm = (MapDefinition.Left(dPrev) + MapDefinition.Left(dNext)).normalized;
      float k = 1f / Mathf.Max(0.5f, Vector2.Dot(nrm, MapDefinition.Left(dNext)));
      if (!map.closed) p += (i == 0 ? -dNext * 6f : i == n ? dPrev * 6f : Vector2.zero);
      centre.Add(p);
      left.Add(p + nrm * w * k);
      right.Add(p - nrm * w * k);
    }

    bool Banked(float s0, float s1) =>
        Mathf.Abs(map.BankAt(s0)) > 1e-3f ||
        Mathf.Abs(map.BankAt(s1)) > 1e-3f ||
        Mathf.Abs(map.BankAt(0.5f * (s0 + s1))) > 1e-3f;

    var verts = new List<Vector3>();
    var norms = new List<Vector3>();
    var trisA = new List<int>();
    var trisB = new List<int>();
    var trisLine = new List<int>();
    var trisMark = new List<int>();
    const float yTop = 0.002f, yBot = -0.025f;

    void AddQuad(Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector3 normal, List<int> tris) {
      int idx = verts.Count;
      verts.Add(a); verts.Add(b); verts.Add(c); verts.Add(d);
      norms.Add(normal); norms.Add(normal); norms.Add(normal); norms.Add(normal);
      tris.Add(idx); tris.Add(idx + 2); tris.Add(idx + 1);
      tris.Add(idx); tris.Add(idx + 3); tris.Add(idx + 2);
    }

    // Collect arc-length intervals (in world segment coordinates) for start_line and checkpoint marks
    const float lineHalfWidth = 0.16f;   // 32 cm wide start line
    const float markHalfWidth = 0.15f;   // 30 cm wide checkpoint lines (never sub-pixel at 25-75m)

    for (int i = 0; i < n; i++) {
      int j = (i + 1) % vertsCount;
      float s0 = map.SegmentStart(i), segLen = map.SegmentLength(i);
      float extStart = (!map.closed && i == 0) ? -6f : 0f;
      float extEnd = (!map.closed && i == n - 1) ? 6f : 0f;
      float totalWorldLen = (centre[j] - centre[i]).magnitude;

      // Build sorted split points u in [0, 1] along this segment for 5m tiles + start_line + checkpoint marks
      var splits = new List<float> { 0f, 1f };
      int tiles = Mathf.Max(1, Mathf.RoundToInt(totalWorldLen / 5f));
      for (int t = 1; t < tiles; t++) splits.Add((float)t / tiles);

      float WorldUFromArcS(float arcS) {
        float localS = (arcS - s0) - extStart;
        return Mathf.Clamp01(localS / Mathf.Max(1e-4f, totalWorldLen));
      }
      float ArcSFromWorldU(float u) => s0 + extStart + u * totalWorldLen;

      // Start line at arc s = 0.6 m
      if (0.6f >= s0 + extStart && 0.6f <= s0 + segLen + extEnd) {
        splits.Add(WorldUFromArcS(0.6f - lineHalfWidth));
        splits.Add(WorldUFromArcS(0.6f + lineHalfWidth));
      }
      // Checkpoint marks every map.checkpointSpacing
      for (float ms = map.checkpointSpacing; ms < map.Length - 0.5f; ms += map.checkpointSpacing) {
        if (ms >= s0 + extStart && ms <= s0 + segLen + extEnd && Mathf.Abs(map.BankAt(ms)) <= 1e-3f) {
          splits.Add(WorldUFromArcS(ms - markHalfWidth));
          splits.Add(WorldUFromArcS(ms + markHalfWidth));
        }
      }

      splits.Sort();
      var uniqueU = new List<float>(splits.Count);
      foreach (float u in splits) {
        if (uniqueU.Count == 0 || u - uniqueU[uniqueU.Count - 1] > 1e-4f) uniqueU.Add(u);
      }

      for (int k = 0; k < uniqueU.Count - 1; k++) {
        float u0 = uniqueU[k], u1 = uniqueU[k + 1];
        float sMid = ArcSFromWorldU(0.5f * (u0 + u1));
        if (Banked(Mathf.Clamp(sMid - 0.2f, 0f, map.Length), Mathf.Clamp(sMid + 0.2f, 0f, map.Length))) continue;

        Vector2 la = Vector2.Lerp(left[i], left[j], u0);
        Vector2 lb = Vector2.Lerp(left[i], left[j], u1);
        Vector2 ra = Vector2.Lerp(right[i], right[j], u0);
        Vector2 rb = Vector2.Lerp(right[i], right[j], u1);

        List<int> targetTris;
        if (Mathf.Abs(sMid - 0.6f) <= lineHalfWidth + 0.01f) {
          targetTris = trisLine;
        } else {
          bool isMark = false;
          for (float ms = map.checkpointSpacing; ms < map.Length - 0.5f; ms += map.checkpointSpacing) {
            if (Mathf.Abs(sMid - ms) <= markHalfWidth + 0.01f && Mathf.Abs(map.BankAt(ms)) <= 1e-3f) {
              isMark = true;
              break;
            }
          }
          if (isMark) {
            targetTris = trisMark;
          } else {
            int tileIdx = Mathf.Clamp(Mathf.FloorToInt(0.5f * (u0 + u1) * tiles), 0, tiles - 1);
            targetTris = ((i + tileIdx) % 2 == 0) ? trisA : trisB;
          }
        }

        Vector3 vRa = new Vector3(ra.x, yTop, ra.y);
        Vector3 vRb = new Vector3(rb.x, yTop, rb.y);
        Vector3 vLb = new Vector3(lb.x, yTop, lb.y);
        Vector3 vLa = new Vector3(la.x, yTop, la.y);
        AddQuad(vRa, vRb, vLb, vLa, Vector3.up, targetTris);

        Vector3 vRaBot = new Vector3(ra.x, yBot, ra.y);
        Vector3 vRbBot = new Vector3(rb.x, yBot, rb.y);
        Vector3 vLbBot = new Vector3(lb.x, yBot, lb.y);
        Vector3 vLaBot = new Vector3(la.x, yBot, la.y);
        AddQuad(vRaBot, vRbBot, vRb, vRa, Vector3.right, targetTris);
        AddQuad(vLbBot, vLaBot, vLa, vLb, Vector3.left, targetTris);
      }
    }

    var mesh = new Mesh {
      name = "TrackRibbon_Seamless",
      indexFormat = UnityEngine.Rendering.IndexFormat.UInt32,
      subMeshCount = 4
    };
    mesh.SetVertices(verts);
    mesh.SetNormals(norms);
    mesh.SetTriangles(trisA, 0);
    mesh.SetTriangles(trisB, 1);
    mesh.SetTriangles(trisLine, 2);
    mesh.SetTriangles(trisMark, 3);
    mesh.RecalculateBounds();

    var go = new GameObject("TrackRibbon_Seamless");
    go.transform.SetParent(visRoot, false);
    go.AddComponent<MeshFilter>().sharedMesh = mesh;
    var mr = go.AddComponent<MeshRenderer>();
    mr.sharedMaterials = new[] { matA, matB, matLine, matMark };
    mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
    mr.receiveShadows = true;
  }
}

}
