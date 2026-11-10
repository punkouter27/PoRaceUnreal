using System;
using System.Collections.Generic;
using System.Linq;
using Mujoco;
using UnityEngine;

namespace PoRace {

/// <summary>Per-racer measurements shared by the broadcast layer, computed once per 50 Hz control step from mjData:
/// joint effort (|actuator_force| / forcerange, smoothed), mechanical power sum |tau * qdot|, base speed, foot strikes
/// (rising edge of a foot geom touching a world geom: floor, bank, rails, obstacles). Cube hits: ContactImpulse. Read only:
/// nothing here writes MuJoCo state.</summary>
public unsafe class RaceSensors : MonoBehaviour {
  public MultiRaceOrchestrator race;
  [Tooltip("Smoothing time constant for joint effort (s).")]
  public float effortTau = 0.15f;

  public class State {
    public readonly float[] effort;                            // per actuator, 0..1 of its forcerange, smoothed
    public float power, speed, energy, mass;                   // W, m/s, J, kg
    public Vector3 velocity;                                   // MuJoCo frame
    public readonly bool[] down;
    public int strikes;
    /// <summary>A1 fall risk 0..1 (tilt + roll/pitch rate, smoothed) and the wobble flag (risk held above the threshold).</summary>
    public float risk; public bool wobbling; public int wobbles;
    /// <summary>Stride frequency (Hz: touchdowns per second over the last ~2 s / number of feet, so a dog and a human
    /// read alike) and stride length (m: speed / stride frequency, one full cycle of every foot).</summary>
    public float cadence, stepLength;
    internal float over; internal double lastWobble = -1e9; internal int upAdr;
    internal readonly double[] strikeTimes = new double[40]; internal int strikeHead, strikeCount;
    internal readonly int[] footGeom, act, dof;
    internal readonly float[] forceMax;
    internal readonly bool[] now;
    internal int baseDof;
    public State(int actuators, int feet) {
      effort = new float[actuators]; act = new int[actuators]; dof = new int[actuators]; forceMax = new float[actuators];
      down = new bool[feet]; now = new bool[feet]; footGeom = new int[feet];
    }
  }

  /// <summary>(racer, foot index (Go2: 0..3 FL FR RL RR; Matt: 0..1 L R), Unity position, base speed m/s).</summary>
  public event Action<Racer, int, Vector3, float> FootStrike;
  /// <summary>A1: a racer still racing is about to go down (risk above wobbleRisk for wobbleHold s; 3 s apart per racer).</summary>
  public event Action<Racer> Wobble;
  [Tooltip("A1 fall-risk threshold and how long it must hold (s). Risk = 0.6 x tilt / tiltFull + 0.4 x roll/pitch rate / rateFull.")]
  public float wobbleRisk = 0.55f, wobbleHold = 0.1f, tiltFull = 0.25f, rateFull = 3f;

  readonly Dictionary<Racer, State> _s = new Dictionary<Racer, State>();
  int _step;
  public const float ForceRange = 24f;

  public State Of(Racer r) => r != null && _s.TryGetValue(r, out var s) ? s : null;

  void Awake() {
    if (!BroadcastUi.Wired(this, race, nameof(race))) return;
    MjScene.Instance.postUpdateEvent += OnPostStep;
  }
  void OnDestroy() { if (MjScene.InstanceExists) MjScene.Instance.postUpdateEvent -= OnPostStep; }

  void Init(MujocoLib.mjModel_* m) {
    int Id(MujocoLib.mjtObj t, string n) => MujocoLib.mj_name2id(m, (int)t, n);
    foreach (var r in race.Live) {
      var B = r.Body; if (B == null || !B.Ready) { _s.Clear(); return; }
      State s;
      if (r.matt == null) {
        var M = r.controller.Model;
        s = new State(Go2Model.Nu, 4);
        for (int i = 0; i < Go2Model.Nu; i++) { s.act[i] = M.ActId[i]; s.dof[i] = M.JointDof[i]; s.forceMax[i] = ForceRange; }
        for (int f = 0; f < 4; f++) s.footGeom[f] = Id(MujocoLib.mjtObj.mjOBJ_GEOM, M.Prefix + Go2Model.Legs[f]);
      } else {
        var H = r.matt.Spec;   // Matt or Grandma: names carry the body's prefix
        s = new State(H.Nu, 2);
        for (int i = 0; i < H.Nu; i++) {
          s.act[i] = Id(MujocoLib.mjtObj.mjOBJ_ACTUATOR, H.N(H.Joints[i]));
          s.dof[i] = m->jnt_dofadr[Id(MujocoLib.mjtObj.mjOBJ_JOINT, H.N(H.Joints[i]))];
          s.forceMax[i] = H.ForceMax[i];
        }
        s.footGeom[0] = Id(MujocoLib.mjtObj.mjOBJ_GEOM, H.N("left_foot")); s.footGeom[1] = Id(MujocoLib.mjtObj.mjOBJ_GEOM, H.N("right_foot"));
      }
      s.baseDof = B.BaseDof; s.upAdr = B.UpAdr;
      s.mass = (float)RacerMath.RootMass(m, B.BaseBody);
      _s[r] = s;
    }
  }

  void OnPostStep(object sender, MjStepArgs a) {
    if (race == null || race.Live.Count == 0) return;
    if (_s.Count == 0) Init(a.model);
    if (_s.Count == 0 || _step++ % Go2Controller.Decimation != 0) return;
    var m = a.model; var d = a.data; float dt = Go2Controller.SimDt * Go2Controller.Decimation;
    float k = 1f - Mathf.Exp(-dt / effortTau);

    foreach (var kv in _s) {
      var s = kv.Value;
      float p = 0f;
      for (int i = 0; i < s.effort.Length; i++) {
        float tau = (float)d->actuator_force[s.act[i]];
        s.effort[i] += (Mathf.Min(1f, Mathf.Abs(tau) / s.forceMax[i]) - s.effort[i]) * k;
        p += Mathf.Abs(tau * (float)d->qvel[s.dof[i]]);
      }
      s.power = p; s.energy += p * dt;
      s.velocity = new Vector3((float)d->qvel[s.baseDof], (float)d->qvel[s.baseDof + 1], (float)d->qvel[s.baseDof + 2]);
      s.speed = new Vector2(s.velocity.x, s.velocity.y).magnitude;
      // A1 fall risk: tilt from the up vector (1 - z: 0 upright, 1 on its side) and the base's roll / pitch rate (free
      // joint angular velocity is in the body frame: x, y = roll, pitch).
      float tilt = 1f - (float)d->sensordata[s.upAdr + 2];
      float rate = new Vector2((float)d->qvel[s.baseDof + 3], (float)d->qvel[s.baseDof + 4]).magnitude;
      float raw = 0.6f * Mathf.Clamp01(tilt / tiltFull) + 0.4f * Mathf.Clamp01(rate / rateFull);
      s.risk += (raw - s.risk) * (1f - Mathf.Exp(-dt / 0.2f));
      var r = kv.Key; bool racing = r.state == RaceState.RACING && r.finishTime < 0 && race.Phase == RacePhase.Racing;
      s.over = racing && s.risk > wobbleRisk ? s.over + dt : 0f;
      if (s.wobbling && s.risk < 0.3f) s.wobbling = false;
      if (!s.wobbling && s.over >= wobbleHold && d->time - s.lastWobble > 3.0) {
        s.wobbling = true; s.wobbles++; s.lastWobble = d->time; Wobble?.Invoke(r);
      }
      // cadence: touchdowns in the last 2 s (ring of the last 40 strike times: a Go2 trot lands ~10 feet per second)
      int n = 0; for (int i = 0; i < s.strikeCount; i++) if (d->time - s.strikeTimes[i] <= 2.0) n++;
      s.cadence = n / 2f / s.footGeom.Length; s.stepLength = s.cadence > 0.1f ? s.speed / s.cadence : 0f;
    }

    // Foot contacts with world geoms (body 0), one pass over the contact list.
    foreach (var s in _s.Values) for (int f = 0; f < s.now.Length; f++) s.now[f] = false;
    for (int i = 0; i < d->ncon; i++) {
      int g1 = d->contact[i].geom1, g2 = d->contact[i].geom2;
      bool w1 = m->geom_bodyid[g1] == 0, w2 = m->geom_bodyid[g2] == 0;
      if (!(w1 ^ w2)) continue;
      int foot = w1 ? g2 : g1;
      foreach (var s in _s.Values) for (int f = 0; f < s.footGeom.Length; f++) if (s.footGeom[f] == foot) s.now[f] = true;
    }
    foreach (var kv in _s) {
      var s = kv.Value;
      for (int f = 0; f < s.now.Length; f++) {
        bool now = s.now[f];
        if (now && !s.down[f]) {
          s.strikes++;
          s.strikeTimes[s.strikeHead] = d->time; s.strikeHead = (s.strikeHead + 1) % s.strikeTimes.Length; s.strikeCount = Mathf.Min(s.strikeCount + 1, s.strikeTimes.Length);
          int g = s.footGeom[f];
          FootStrike?.Invoke(kv.Key, f, new Vector3((float)d->geom_xpos[3 * g], (float)d->geom_xpos[3 * g + 2], (float)d->geom_xpos[3 * g + 1]), s.speed);
        }
        s.down[f] = now;
      }
    }
  }

}

}
