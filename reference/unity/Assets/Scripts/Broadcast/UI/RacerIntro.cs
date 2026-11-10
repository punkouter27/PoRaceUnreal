using System.Globalization;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace PoRace {

/// <summary>Racer introduction before the countdown: a title card (map, length, field), then each racer on the grid in
/// turn, the camera in front of it and a lower-third card (name in its colour, creature, height, pace, the creature
/// card's traits). The orchestrator holds the grid on the start line meanwhile (MultiRaceOrchestrator.introSeconds),
/// exactly as in the countdown, so no policy sees anything new. SKIP ends it. Added to every race scene at load
/// (no scene rebuild); never in -raceTest or headless runs, and a Restart goes straight to the countdown.
/// Visual only.</summary>
[DefaultExecutionOrder(300)]   // after FollowCam and RaceDirector: the intro owns the camera while it runs
public class RacerIntro : MonoBehaviour {
  public MultiRaceOrchestrator race;
  public float titleSeconds = 2f, racerSeconds = 2.6f;

  Camera _cam; Vector3 _vel;
  Image _title, _card, _bar; Text _titleText, _name, _info; GameObject _skip;
  int _shown = -2; bool _done;

  [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
  static void Boot() {
    SceneManager.sceneLoaded += (s, m) => {
      if (CliArgs.RaceTest || BroadcastUi.Headless || CliArgs.Has("-noIntro")) return;
      var race = FindAnyObjectByType<MultiRaceOrchestrator>();   // its Awake has drawn the grid; no physics step yet
      if (race == null || race.Live.Count == 0) return;
      var intro = race.gameObject.AddComponent<RacerIntro>(); intro.race = race;
      race.introSeconds = intro.titleSeconds + intro.racerSeconds * race.Live.Count;
    };
  }

  void Start() {
    _cam = race.ViewCamera;
    var root = BroadcastUi.Root; var top = new Vector2(0.5f, 1f); var bottom = new Vector2(0.5f, 0f);
    _title = BroadcastUi.Panel(root, "IntroTitle", top, top, new Vector2(0, -150), new Vector2(640, Tournament.Label != null ? 180 : 150), new Color(0.08f, 0.09f, 0.12f, 0.88f));
    _titleText = BroadcastUi.Label(_title.transform, "Text", new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(620, 170), 26, TextAnchor.MiddleCenter);
    var m = race.map; int n = race.Live.Count;
    string round = Tournament.Label != null ? $"<size=24><color=#{ColorUtility.ToHtmlStringRGB(BroadcastUi.Accent)}>TOURNAMENT · {Tournament.Label}</color></size>\n" : "";
    _titleText.text = round + $"<size=46><b>{m.displayName.ToUpperInvariant()}</b></size>\n{race.TotalLength:F0} m · {m.terrain}{(m.closed ? $" · {race.Laps} lap{(race.Laps > 1 ? "s" : "")}" : "")}\n"
                    + (n == 1 ? "time trial · 1 racer" : $"{n} racers on the grid");

    _card = BroadcastUi.Panel(root, "IntroCard", bottom, bottom, new Vector2(0, 250), new Vector2(680, 210), new Color(0.08f, 0.09f, 0.12f, 0.9f));
    _bar = BroadcastUi.Panel(_card.transform, "Livery", new Vector2(0f, 0.5f), new Vector2(0f, 0.5f), Vector2.zero, new Vector2(14, 210), Color.white);
    _name = BroadcastUi.Label(_card.transform, "Name", new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(34, -14), new Vector2(460, 60), 48, TextAnchor.UpperLeft);
    _name.fontStyle = FontStyle.Bold;
    _info = BroadcastUi.Label(_card.transform, "Info", new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(34, -76), new Vector2(620, 130), 22, TextAnchor.UpperLeft);
    _skip = BroadcastUi.Button(_card.transform, "BtnSkipIntro", "SKIP >>", Vector2.one, Vector2.one, new Vector2(-12, -12), new Vector2(150, 50), new Color(0.2f, 0.22f, 0.28f, 1f), 22,
        () => race.SkipIntro()).gameObject;
    _card.gameObject.SetActive(false);
  }

  void LateUpdate() {
    if (_done) return;
    float left = race.IntroLeft;
    if (left <= 0f) { Finish(); return; }
    float into = race.introSeconds - left;
    int k = into < titleSeconds ? -1 : Mathf.Min(race.Live.Count - 1, (int)((into - titleSeconds) / racerSeconds));
    bool cut = k != _shown;
    if (cut) Show(k);
    if (k < 0 || _cam == null) return;   // the title card rides on the follow cam's grid shot
    var r = race.Live[k]; if (r.Body.BaseTransform == null) return;
    bool human = r.matt != null;
    race.map.PointAt(r.distance, out var t);
    var fwd = new Vector3(t.x, 0f, t.y).normalized; var side = Vector3.Cross(Vector3.up, fwd);
    var p = r.Body.BaseTransform.position;
    float d = human ? 2.7f : 1.3f, ground = race.followCam != null && race.followCam.groundHeight != null ? race.followCam.groundHeight(p) : 0f;
    var want = p + fwd * d + side * (0.45f * d); want.y = ground + (human ? 1.45f : 0.5f);
    var look = p + Vector3.up * (human ? 0.25f : 0.02f);
    var tr = _cam.transform;
    // A hard cut to each racer (a glide between side-by-side racers passed through the next one's body), then a slow
    // push-in: the shot starts 15 % wider and eases in.
    if (cut) { tr.position = want + (want - look) * 0.15f; _vel = Vector3.zero; }
    else tr.position = Vector3.SmoothDamp(tr.position, want, ref _vel, 0.6f, Mathf.Infinity, Time.unscaledDeltaTime);
    tr.rotation = Quaternion.LookRotation((look - tr.position).normalized, Vector3.up);
  }

  void Show(int k) {
    _shown = k;
    // The follow cam eases toward the pack every frame; left on, it drags each close-up back to a high rear view.
    if (race.followCam != null) race.followCam.enabled = k < 0;
    _title.gameObject.SetActive(k < 0);
    _card.gameObject.SetActive(k >= 0);
    if (k < 0) return;
    var r = race.Live[k]; var c = Creature(r);
    _bar.color = r.color;
    _name.text = BroadcastUi.Paint(r.name, r.color) + $"<size=24>   {AgentElo.Rating(r.name)} ELO  ·  {k + 1} of {race.Live.Count}</size>";
    var ra = FindAnyObjectByType<RaceAudio>();
    if (ra != null) ra.Speak(r, AgentEmotion.Happy, 3, force: true);
    string what = r.matt != null ? (c != null && c.displayName != r.name ? c.displayName : "Human") + " runner" : "Unitree Go2 robot dog";
    string traits = c != null && !string.IsNullOrEmpty(c.traits) ? "\n<size=18>" + c.traits + "</size>" : "";
    _info.text = string.Format(CultureInfo.InvariantCulture, "{0} · {1:F2} m tall\nPace about {2:F2} m/s · own learned policy{3}",
        what, c != null ? c.height : r.Body.HomeHeight, r.speed, traits);
  }

  /// <summary>The creature card behind a racer: the Go2 for a dog, otherwise the human's own card by name.</summary>
  static CreatureDefinition Creature(Racer r) {
    string want = r.matt != null ? (r.matt.human == Human.Grandma ? "Grandma" : "Matt") : "Go2";
    foreach (var c in CreatureRegistry.All()) if (c.displayName == want) return c;
    return null;
  }

  void Finish() {
    _done = true;
    if (race.followCam != null) race.followCam.enabled = true;
    if (_title != null) _title.gameObject.SetActive(false);
    if (_card != null) _card.gameObject.SetActive(false);
    enabled = false;   // FollowCam eases from the last intro shot to the pack
  }
}

}
