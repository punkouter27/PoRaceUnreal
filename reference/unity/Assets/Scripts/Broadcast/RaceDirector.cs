using System.Linq;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UI;

namespace PoRace {

public enum Shot { Pack, Leader, Battle, Trackside, Overhead, Incident, Finish, Replay }

/// <summary>Feature 2, the automatic director. Race events are scored and the camera cuts to the best shot:
/// overtake = BATTLE (side-on, both racers), fall = INCIDENT (orbit + slow motion), leader in the last 6 m = FINISH
/// (fixed at the line), a pile-up of contacts = OVERHEAD, redline = close LEADER chase on that racer; otherwise it
/// rotates PACK / LEADER / TRACKSIDE. A shot holds at least 2.5 s unless something clearly more important happens.
/// PACK hands the camera back to FollowCam; every other shot drives the camera here. C toggles auto / manual
/// (tap the shot label on a phone); in manual, C steps through the shots. Visual only: never touches MuJoCo.</summary>
[DefaultExecutionOrder(200)]
public class RaceDirector : MonoBehaviour {
  public MultiRaceOrchestrator race;
  public FollowCam followCam;
  public StrainMonitor strain;
  [OptionalRef] public RaceSensors sensors;   // A1 wobble warnings (pre-roll the INCIDENT shot before a fall)
  public bool auto = true;
  public float minHold = 2.5f, maxHold = 6f;
  [Tooltip("Time scale during an INCIDENT shot (interactive only).")]
  public float slowMotion = 0.4f;

  public Shot Current { get; private set; } = Shot.Pack;
  public Racer Subject { get; private set; }
  Racer _other; float _since, _score, _slowUntil, _lastOverhead = -100f; int _bumps, _rotation;
  Vector3 _fixed, _vel, _shakeOffset; float _fixedS, _orbit, _trauma, _shakeRoll, _leadAway = 1f; bool _leadFront;
  public float maxShakeOffset = 0.12f, maxShakeRoll = 2.5f, traumaDecay = 1.4f;
  Camera _cam; Text _label; Button _labelButton;
  bool _inReplay, _calm;

  void Start() {
    if (!BroadcastUi.Wired(this, race, nameof(race))) return;
    if (followCam == null) followCam = race.followCam;
    if (strain == null) strain = FindAnyObjectByType<StrainMonitor>();
    if (BroadcastUi.Headless || followCam == null) { enabled = false; return; }
    _cam = followCam.GetComponent<Camera>();
    race.Overtook += (a, b) => Want(Shot.Battle, a, b, 6f);
    race.Fell += r => Want(Shot.Incident, r, null, 9f);
    race.Finished += r => { if (r.place == 1) Want(Shot.Finish, r, null, 8f); };
    race.Restarted += () => { Cut(Shot.Pack, null, null, 0f); Time.timeScale = 1f; };
    if (strain != null) strain.Redline += r => Want(Shot.Leader, r, null, 3f);
    // A1: cut to the racer about to fall, without slow motion (it may stay up); the fall itself (score 9) keeps the shot.
    if (sensors != null) sensors.Wobble += r => {
      _calm = true; Want(Shot.Incident, r, null, 7f); _calm = false;
      BroadcastTicker.Post($"{BroadcastUi.Paint(r.name, r.color)} is wobbling!", 3f);
    };
    _labelButton = BroadcastUi.Button(BroadcastUi.Root, "ShotLabel", "", Vector2.zero, Vector2.zero, new Vector2(180, 204), new Vector2(524, 40), new Color(0, 0, 0, 0.55f), 22, ToggleAuto);
    _label = _labelButton.GetComponentInChildren<Text>(); _label.alignment = TextAnchor.MiddleLeft; _label.rectTransform.offsetMin = new Vector2(12, 0);
  }

  void ToggleAuto() { auto = !auto; if (auto) Cut(Shot.Pack, null, null, 0f); }

  /// <summary>Instant replay takes the camera (RaceReplay): orbit the subject while frames play back.</summary>
  public void BeginReplay(Racer subject) { _inReplay = true; Cut(Shot.Replay, subject, null, 100f); }
  public void EndReplay() { _inReplay = false; Cut(Shot.Pack, null, null, 0f); }
  /// <summary>H.1 camera shake: trauma 0..1 adds up from every source and decays at traumaDecay per second; the shake
  /// is trauma squared, so small knocks stay subtle and pile-ups shake hard.</summary>
  public void AddTrauma(float amount) { if (amount > 0f) _trauma = Mathf.Min(1f, _trauma + amount); }
  public void Shake(float amplitude, float seconds) => AddTrauma(amplitude * seconds * 12f);

  void Want(Shot shot, Racer subject, Racer other, float score) {
    if (!auto || _inReplay || race.Phase == RacePhase.Countdown) return;
    float held = Time.unscaledTime - _since;
    if (score > _score + 3f || (held > minHold && score >= _score * 0.5f)) Cut(shot, subject, other, score);
  }

  void Cut(Shot shot, Racer subject, Racer other, float score) {
    Current = shot; Subject = subject; _other = other; _score = score; _since = Time.unscaledTime; _vel = Vector3.zero; _orbit = 0f;
    followCam.enabled = shot == Shot.Pack;
    if (shot == Shot.Leader && subject != null) {
      // Framing fixed for the whole shot (a mid-shot flip would swing the camera through the racer): the side away from
      // the nearest rival within 3 m (cross(f, up) is track-left, +lateral), and head-on when that rival is under 2.5 m
      // behind, since it then stands right beside a chase camera (a passing human's arm filled the frame).
      Racer near = null;
      foreach (var o in race.Live) if (o != subject && Mathf.Abs(o.distance - subject.distance) < 3f && (near == null || Mathf.Abs(o.distance - subject.distance) < Mathf.Abs(near.distance - subject.distance))) near = o;
      _leadAway = near == null || subject.lateral >= near.lateral ? 1f : -1f;
      _leadFront = near != null && near.distance < subject.distance && subject.distance - near.distance < 2.5f;
    }
    if (shot == Shot.Trackside && subject != null) {
      // Ahead of the subject, just inside the far rail, at the subject's eye level: the racer runs toward the lens.
      // Outside the rail the grandstands and the rail itself filled half the frame; the shot cuts away (Update) 4 m
      // before the racer would reach the lens, so a 1.9 m human never fills the screen.
      float s = subject.distance + 10f; _fixedS = s; var p = race.map.PointAt(s, out var t); var left = MapDefinition.Left(t);
      float side = subject.lateral >= 0 ? -1f : 1f, w = race.map.halfWidth - 0.3f;   // far side: the racer passes wide of the lens
      var mj = p + left * side * w; _fixed = new Vector3(mj.x, race.map.SurfaceHeight(s, side * w) + (subject.matt != null ? 1.35f : 0.75f), mj.y);
    }
    if (shot == Shot.Finish) {
      // 5 m past the line, inside the rail on the far side from the winner, 1.3 m up: it runs through the arch toward
      // the lens. (Outside the rail at 0.7 m the rail and the arch's crossbar filled the frame.)
      var p = race.map.PointAt(race.map.closed ? 0f : race.map.Length, out var t);
      float side = subject != null && subject.lateral >= 0 ? -1f : 1f;
      var mj = p + t * 5f + MapDefinition.Left(t) * side * (race.map.halfWidth - 0.35f);
      _fixed = new Vector3(mj.x, race.map.SurfaceHeightAt(mj) + 1.3f, mj.y);
    }
    if (shot == Shot.Incident && !_calm && !BroadcastUi.Headless && Time.timeScale >= 0.99f) { Time.timeScale = slowMotion; _slowUntil = Time.unscaledTime + 1.6f; }
  }

  Vector3 Pos(Racer r) => r != null && r.Body.BaseTransform != null ? r.Body.BaseTransform.position : Vector3.zero;
  Vector3 Fwd(Racer r) { race.map.PointAt(r.distance, out var t); return new Vector3(t.x, 0f, t.y); }

  static readonly Shot[] ManualShots = { Shot.Pack, Shot.Leader, Shot.Trackside, Shot.Overhead };
  static readonly Shot[] AutoCycle = { Shot.Pack, Shot.Leader, Shot.Trackside };

  void Update() {
    UndoShake();
    if (Keyboard.current != null && Keyboard.current.cKey.wasPressedThisFrame) {
      if (auto) auto = false;
      else Cut(ManualShots[(System.Array.IndexOf(ManualShots, Current) + 1) % ManualShots.Length], race.Leader(), null, 0f);
    }
    if (_slowUntil > 0 && Time.unscaledTime > _slowUntil && !_inReplay) { Time.timeScale = 1f; _slowUntil = 0; }
    if (race.Phase == RacePhase.Countdown && Current != Shot.Pack && !_inReplay) Cut(Shot.Pack, null, null, 0f);

    float held = Time.unscaledTime - _since;
    if (auto && !_inReplay && race.Phase != RacePhase.Countdown) {
      // A burst of contacts (10 new bumps) shows from above, at most every 15 s: the ovals bump all the time.
      if (race.Bumps > _bumps + 10 && Time.unscaledTime - _lastOverhead > 15f) { _bumps = race.Bumps; _lastOverhead = Time.unscaledTime; Want(Shot.Overhead, race.Leader(), null, 4f); }
      var lead = race.Leader();
      if (lead != null && lead.finishTime < 0 && race.TotalLength - lead.distance < 6f && Current != Shot.Finish) Want(Shot.Finish, lead, null, 7f);
      bool stale = held > maxHold || (Current == Shot.Trackside && Subject != null && Subject.distance > _fixedS - 4f)
                   || (Current == Shot.Incident && Subject != null && Subject.state == RaceState.RACING && held > minHold);
      if (stale && race.Phase == RacePhase.Racing) {
        var next = AutoCycle[_rotation++ % AutoCycle.Length];
        var subj = next == Shot.Leader ? lead : race.Live[Random.Range(0, race.Live.Count)];
        Cut(next, subj, null, 2f);
      }
    }
    if (_label != null) {
      string who = Subject == null ? "" : _other != null ? $"  {BroadcastUi.Paint(Subject.name, Subject.color)} vs {BroadcastUi.Paint(_other.name, _other.color)}" : "  " + BroadcastUi.Paint(Subject.name, Subject.color);
      _label.text = $"{BroadcastUi.Paint("●", BroadcastUi.Live)} CAM {(int)Current + 1}  {Current.ToString().ToUpperInvariant()}{who}{(auto ? "" : "   MANUAL")}";
    }
  }

  void LateUpdate() {
    if (_cam == null || Current == Shot.Pack) { ApplyShake(); return; }
    float dt = Time.unscaledDeltaTime; var tr = _cam.transform;
    Vector3 want, look;
    var subj = Subject ?? race.Leader();
    switch (Current) {
      case Shot.Leader: {
        var f = Fwd(subj); var p = Pos(subj);
        want = p + f * (_leadFront ? 2.2f : -1.7f) + Vector3.up * (subj.matt != null ? 1.1f : 0.75f) + Vector3.Cross(f, Vector3.up) * (0.45f * _leadAway);   // framing: Cut
        if (_leadFront) { look = p + Vector3.up * 0.1f; break; } look = p + f * 1.2f + Vector3.up * 0.1f; break; }   // 0.55 m sat on the floor markings
      case Shot.Battle: {
        var a = Pos(subj); var b = _other != null ? Pos(_other) : a; var mid = (a + b) * 0.5f; var f = Fwd(subj);
        // Side-on from the half of the track with more room (cross(up, f) points to the right of travel), kept
        // inside the rails so they never block the shot.
        float midLat = 0.5f * (subj.lateral + (_other != null ? _other.lateral : subj.lateral));
        var side = Vector3.Cross(Vector3.up, f).normalized * (midLat >= 0f ? 1f : -1f);
        float room = race.map.halfWidth - 0.15f + Mathf.Abs(midLat);
        want = mid + side * Mathf.Min(1.4f + 0.5f * Vector3.Distance(a, b), room) + Vector3.up * 0.6f + f * 0.4f; look = mid + Vector3.up * 0.1f; break; }
      case Shot.Trackside: want = _fixed; look = Pos(subj) + Vector3.up * 0.15f; break;
      case Shot.Overhead: { var c = followCam.target != null ? followCam.target.position : Pos(subj); var f = Fwd(subj); want = c - f * 2.5f + Vector3.up * 7f; look = c; break; }
      case Shot.Finish: want = _fixed; look = Pos(subj) + Vector3.up * 0.15f; break;
      case Shot.Incident: case Shot.Replay: {
        _orbit += dt * (Current == Shot.Replay ? 0.5f : 0.35f); var p = Pos(subj);
        want = p + new Vector3(Mathf.Cos(_orbit), 0f, Mathf.Sin(_orbit)) * 1.3f + Vector3.up * 0.55f; look = p + Vector3.up * 0.1f; break; }
      default: want = tr.position; look = Pos(subj); break;
    }
    if (followCam.groundHeight != null) want.y = Mathf.Max(want.y, followCam.groundHeight(want) + 0.25f);
    // Fixed shots and the head-on leader shot are placed exactly: easing toward a point the racer runs at shortens the
    // gap by the smoothing lag (the dog filled the frame), worse with -timeScale. The head-on offset rides with the racer.
    bool moving = Current != Shot.Trackside && Current != Shot.Finish && !(Current == Shot.Leader && _leadFront);
    tr.position = moving && Held() > 0.05f ? Vector3.SmoothDamp(tr.position, want, ref _vel, 0.25f, Mathf.Infinity, dt) : want;
    tr.rotation = Quaternion.LookRotation((look - tr.position).normalized, Vector3.up);
    ApplyShake();
  }

  float Held() => Time.unscaledTime - _since;

  /// <summary>Perlin offset and roll on top of whoever placed the camera this frame (FollowCam or a shot above).</summary>
  void ApplyShake() {
    if (_cam == null || _trauma <= 0f) return;
    float s = _trauma * _trauma, t = Time.unscaledTime * 22f; var tr = _cam.transform;
    float N(float seed) => Mathf.PerlinNoise(t, seed) * 2f - 1f;
    _shakeOffset = tr.rotation * new Vector3(N(1.3f), N(7.1f), 0f) * (maxShakeOffset * s);
    _shakeRoll = N(13.7f) * maxShakeRoll * s;
    tr.position += _shakeOffset; tr.rotation *= Quaternion.Euler(0f, 0f, _shakeRoll);
    _trauma = Mathf.Max(0f, _trauma - traumaDecay * Time.unscaledDeltaTime);
  }

  /// <summary>Takes last frame's shake back out before FollowCam / the shots smooth from the camera's position, so the
  /// offsets never feed into the camera path.</summary>
  void UndoShake() {
    if (_cam == null || (_shakeOffset == Vector3.zero && _shakeRoll == 0f)) return;
    var tr = _cam.transform; tr.rotation *= Quaternion.Euler(0f, 0f, -_shakeRoll); tr.position -= _shakeOffset;
    _shakeOffset = Vector3.zero; _shakeRoll = 0f;
  }
}

}
