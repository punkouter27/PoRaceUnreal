using System.Collections.Generic;
using Mujoco;
using UnityEngine;

namespace PoRace {

/// <summary>Proposals r3 B9: "no clipping" measured on every race. Each physics step it reads mjData.contact and keeps,
/// per contact class, the deepest penetration (dist &lt; 0) and how long a class stayed past its limit:
///   foot-floor (a racer's foot geom on a world geom), body-floor (any other racer geom on a world geom), robot-robot,
///   self (two geoms of the same racer), cube.
/// MuJoCo contacts are soft (solref / solimp), so a resting body sits a few mm in by design; Matt lying down sits
/// 1.7 cm into his pelvis capsule (contactProbe, 2026-10-28). Limits: feet 1 cm, everything else 2.5 cm; a class past
/// its limit for more than 0.1 s straight fails -raceTest when run with -contactGate (exit 4, MultiRaceOrchestrator.TestEnding);
/// without it the summary is logged only. First measurement (2026-11-09, Planar Sprint seed 7): foot-floor peaks
/// 2.5-2.7 cm and stays over 1 cm for 0.14-0.18 s (dogs and Matt alike, unchanged physics since F.4), robot-robot
/// 2.2-3.2 cm for under 0.01 s: soft-contact sink under the race solver (iterations 1), not a regression. Read only.</summary>
public unsafe class ContactAudit : MonoBehaviour {
  public MultiRaceOrchestrator race;
  public float footLimit = 0.01f, otherLimit = 0.025f, sustain = 0.1f;

  enum C { FootFloor, BodyFloor, RobotRobot, Self, Cube, Count }
  static readonly string[] Names = { "foot-floor", "body-floor", "robot-robot", "self", "cube" };
  readonly double[] _max = new double[(int)C.Count], _over = new double[(int)C.Count], _worstRun = new double[(int)C.Count];
  readonly double[] _stepDeep = new double[(int)C.Count];
  readonly long[] _contacts = new long[(int)C.Count];
  readonly HashSet<int> _feet = new HashSet<int>();
  readonly Dictionary<int, int> _rootOf = new Dictionary<int, int>();   // racer root body -> racer index
  long _steps; bool _init;
  static readonly bool Enforce = CliArgs.Has("-contactGate");

  void Awake() {
    if (!BroadcastUi.Wired(this, race, nameof(race))) return;
    MjScene.Instance.postUpdateEvent += OnStep;
    MultiRaceOrchestrator.TestEnding += Report;
  }
  void OnDestroy() {
    if (MjScene.InstanceExists) MjScene.Instance.postUpdateEvent -= OnStep;
    MultiRaceOrchestrator.TestEnding -= Report;
  }

  void Init(MujocoLib.mjModel_* m) {
    _init = true;
    for (int i = 0; i < race.Live.Count; i++) {
      var b = race.Live[i].Body; if (b == null || !b.Ready) { _init = false; _feet.Clear(); _rootOf.Clear(); return; }
      _rootOf[m->body_rootid[b.BaseBody]] = i;
      foreach (var f in b.FootGeomNames) { int g = MujocoLib.mj_name2id(m, (int)MujocoLib.mjtObj.mjOBJ_GEOM, f); if (g >= 0) _feet.Add(g); }
    }
  }

  void OnStep(object sender, MjStepArgs a) {
    if (race.Live.Count == 0) return;
    var m = a.model; var d = a.data;
    if (!_init) Init(m);
    if (!_init || race.Phase == RacePhase.Countdown) return;
    _steps++;
    for (int c = 0; c < _stepDeep.Length; c++) _stepDeep[c] = 0;
    for (int i = 0; i < d->ncon; i++) {
      double dist = d->contact[i].dist; if (dist >= 0) continue;
      int g1 = d->contact[i].geom1, g2 = d->contact[i].geom2;
      int r1 = m->body_rootid[m->geom_bodyid[g1]], r2 = m->body_rootid[m->geom_bodyid[g2]];
      bool racer1 = _rootOf.ContainsKey(r1), racer2 = _rootOf.ContainsKey(r2);
      C cls;
      if (racer1 && racer2) cls = r1 == r2 ? C.Self : C.RobotRobot;
      else if (racer1 || racer2) {
        int other = racer1 ? r2 : r1, mine = racer1 ? g1 : g2;
        if (other != 0) cls = C.Cube;   // a free body that is not a racer: the pooled cubes
        else cls = _feet.Contains(mine) ? C.FootFloor : C.BodyFloor;
      } else continue;                  // cube on floor, world on world
      int k = (int)cls; double depth = -dist;
      _contacts[k]++;
      if (depth > _stepDeep[k]) _stepDeep[k] = depth;
      if (depth > _max[k]) _max[k] = depth;
    }
    double dt = m->opt.timestep;
    for (int c = 0; c < _stepDeep.Length; c++) {
      double lim = c == (int)C.FootFloor ? footLimit : otherLimit;
      _over[c] = _stepDeep[c] > lim ? _over[c] + dt : 0;
      if (_over[c] > _worstRun[c]) _worstRun[c] = _over[c];
    }
  }

  void Report(MultiRaceOrchestrator r) {
    var sb = new System.Text.StringBuilder("[ContactAudit]");
    for (int c = 0; c < Names.Length; c++) {
      double lim = c == (int)C.FootFloor ? footLimit : otherLimit;
      sb.Append($" {Names[c]} max {_max[c] * 100:F2} cm (limit {lim * 100:F1}, longest over {_worstRun[c]:F2} s, {_contacts[c]} contacts) |");
      if (_worstRun[c] > sustain && Enforce) MultiRaceOrchestrator.TestGateFailures.Add($"{Names[c]} penetration over {lim * 100:F1} cm for {_worstRun[c]:F2} s");
    }
    sb.Append($" {_steps} steps");
    Debug.Log(sb.ToString());
  }
}

}
