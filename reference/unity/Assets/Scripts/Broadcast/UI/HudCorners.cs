using System.Text;
using UnityEngine;
using UnityEngine.UI;

namespace PoRace {

/// <summary>Proposals r3 C1-C5: the race HUD's five corners, nothing else in them.
///   TL scene title (map + lap) over the standings chips | TC fps / sim Hz (TAB: Hud's full debug line)
///   TR one settings button (opens PauseSheet: Resume, Replay, Restart, Menu, Flip leader, Graphics)
///   BL agent telemetry for the racer on camera (A2): state, speed, cadence, step length, effort, fall risk
///   BR version + YYMMDD build watermark (Hud.version, unchanged).
/// The scene-authored Behaviour text, Restart / Menu / Flip buttons and the separate II button are hidden: everything
/// they did is in the sheet. The ticker and the camera label move next to the BL block. Also shows the A3 yellow flag.</summary>
public class HudCorners : MonoBehaviour {
  public MultiRaceOrchestrator race;
  public RaceSensors sensors;
  public RaceDirector director;
  public PauseSheet sheet;
  [Tooltip("BL telemetry refresh rate (Hz); text is rebuilt only at this rate.")]
  public float refreshHz = 5f;

  Hud _hud; Text _tele, _yellowText; Image _effort, _riskBar, _yellowBar; RectTransform _bl;
  readonly StringBuilder _sb = new StringBuilder(160);
  float _next; int _lap = -1; bool _moved;

  static readonly Color Amber = new Color(1f, 0.7f, 0.1f), Calm = new Color(0.35f, 0.85f, 0.45f), Red = new Color(0.95f, 0.25f, 0.2f);

  void Start() {
    if (!BroadcastUi.Wired(this, race, nameof(race)) || !BroadcastUi.Wired(this, sensors, nameof(sensors))) return;
    if (BroadcastUi.Headless) { enabled = false; return; }
    _hud = FindAnyObjectByType<Hud>();
    if (_hud != null) {
      _hud.telemetryVisible = false;   // TC shows fps / Hz; TAB brings back the full debug line
      if (_hud.behaviour != null) _hud.behaviour.gameObject.SetActive(false);
      foreach (var n in new[] { "BtnReset", "BtnMenu" }) { var b = _hud.transform.Find(n); if (b != null) b.gameObject.SetActive(false); }
      foreach (var b in _hud.GetComponentsInChildren<Button>(true)) {   // the hand-authored Flip button (D.1) has no stable name
        var t = b.GetComponentInChildren<Text>(true); if (t != null && t.text == "Flip") b.gameObject.SetActive(false);
      }
    }
    var root = BroadcastUi.Root;
    // TR: settings button, three bars (no icon font needed)
    var gear = BroadcastUi.Button(root, "BtnSettings", "", Vector2.one, Vector2.one, new Vector2(-16f, -16f), new Vector2(72f, 64f), BroadcastUi.Dark, 22, OpenSheet);
    for (int i = 0; i < 3; i++) BroadcastUi.Panel(gear.transform, "Bar" + i, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(0f, 14f - 14f * i), new Vector2(36f, 5f), Color.white);
    if (sheet != null) {
      sheet.AddButton("BtnFlip", "Flip leader", () => { if (_hud != null) _hud.OnKnockOver(); });
      Text g = null;
      g = sheet.AddButton("BtnGfx", QualityGovernor.Label, () => { QualityGovernor.Cycle(); if (g != null) g.text = QualityGovernor.Label; });
    }

    // BL: agent telemetry block
    // 22-unit text everywhere: 11 pt on a 720 x 1280 @ 320 dpi phone (ShotProbe's text-scale floor)
    _bl = BroadcastUi.Panel(root, "AgentTelemetry", Vector2.zero, Vector2.zero, new Vector2(16f, 16f), new Vector2(360f, 172f), BroadcastUi.Dark).rectTransform;
    _tele = BroadcastUi.Label(_bl, "Text", new Vector2(0f, 1f), new Vector2(0f, 1f), new Vector2(12f, -4f), new Vector2(340f, 84f), 22, TextAnchor.UpperLeft);
    _tele.verticalOverflow = VerticalWrapMode.Truncate;
    Bar(_bl, "Effort", 44f, out _effort); Bar(_bl, "Risk", 12f, out _riskBar);
    BroadcastUi.Label(_bl, "EffortLabel", Vector2.zero, Vector2.zero, new Vector2(12f, 38f), new Vector2(110f, 30f), 22, TextAnchor.MiddleLeft, "effort");
    BroadcastUi.Label(_bl, "RiskLabel", Vector2.zero, Vector2.zero, new Vector2(12f, 6f), new Vector2(110f, 30f), 22, TextAnchor.MiddleLeft, "fall risk");

    // A3 yellow flag: a strip across the top and a label under the clock
    _yellowBar = BroadcastUi.Panel(root, "YellowBar", new Vector2(0.5f, 1f), new Vector2(0.5f, 1f), Vector2.zero, new Vector2(2000f, 10f), new Color(1f, 0.85f, 0f, 0.95f));
    _yellowText = BroadcastUi.Label(root, "YellowText", new Vector2(0.5f, 1f), new Vector2(0.5f, 1f), new Vector2(0f, -196f), new Vector2(400f, 36f), 24, TextAnchor.MiddleCenter, BroadcastUi.Paint("YELLOW FLAG", new Color(1f, 0.85f, 0f)));
    Yellow(false);
    race.YellowChanged += Yellow;
  }

  void OnDestroy() { if (race != null) race.YellowChanged -= Yellow; }

  void Yellow(bool on) {
    if (_yellowBar != null) _yellowBar.gameObject.SetActive(on);
    if (_yellowText != null) _yellowText.gameObject.SetActive(on);
    if (on) BroadcastTicker.Post(BroadcastUi.Paint("YELLOW FLAG", new Color(1f, 0.85f, 0f)) + ": pile-up, the field eases off", 4f);
  }

  void Bar(RectTransform parent, string name, float y, out Image fill) {
    BroadcastUi.Panel(parent, name + "Back", Vector2.zero, Vector2.zero, new Vector2(120f, y + 4f), new Vector2(224f, 14f), new Color(1f, 1f, 1f, 0.15f));
    fill = BroadcastUi.Panel(parent, name + "Fill", Vector2.zero, Vector2.zero, new Vector2(120f, y + 4f), new Vector2(224f, 14f), Calm);
    fill.sprite = White; fill.type = Image.Type.Filled; fill.fillMethod = Image.FillMethod.Horizontal;   // Filled needs a sprite
  }

  static Sprite _white;
  static Sprite White {
    get {
      if (_white != null) return _white;
      var t = new Texture2D(4, 4, TextureFormat.RGBA32, false); var px = new Color32[16];
      for (int i = 0; i < 16; i++) px[i] = new Color32(255, 255, 255, 255);
      t.SetPixels32(px); t.Apply(false, true);
      return _white = Sprite.Create(t, new Rect(0, 0, 4, 4), new Vector2(0.5f, 0.5f), 100f);
    }
  }

  void OpenSheet() { if (sheet != null) sheet.Open(); }

  // The ticker and the camera label are built by other components' Start: move them once, on the first frame here.
  void MoveNeighbours() {
    _moved = true;
    var root = BroadcastUi.Root;
    if (root.Find("Ticker") is RectTransform tk) { tk.anchoredPosition = new Vector2(388f, 56f); tk.sizeDelta = new Vector2(316f, 132f); var t = tk.GetComponentInChildren<Text>(); if (t != null) { t.rectTransform.sizeDelta = new Vector2(300f, 128f); t.fontSize = 22; } }
    if (root.Find("ShotLabel") is RectTransform sl) { sl.anchoredPosition = new Vector2(16f, 196f); sl.sizeDelta = new Vector2(360f, 40f); }
    if (sheet != null && sheet.PauseButton != null) sheet.PauseButton.gameObject.SetActive(false);   // the settings button opens it
  }

  void Update() {
    if (!_moved) MoveNeighbours();
    // TL title: map and lap
    var lead = race.Leader();
    int lap = lead != null && race.map.closed ? Mathf.Clamp(Mathf.FloorToInt(lead.distance / race.map.Length) + 1, 1, race.Laps) : 0;
    if (_hud != null && _hud.title != null && lap != _lap) {
      _lap = lap;
      _hud.title.text = race.map.closed && race.Laps > 1 ? $"{race.map.displayName}  Lap {lap}/{race.Laps}" : race.map.displayName;
    }
    if (Time.unscaledTime < _next) return;
    _next = Time.unscaledTime + 1f / refreshHz;
    var r = director != null && director.Subject != null ? director.Subject : lead;
    var s = sensors.Of(r);
    if (r == null || s == null) { _tele.text = ""; _effort.fillAmount = _riskBar.fillAmount = 0f; return; }
    string state = r.finishTime >= 0 ? BroadcastUi.Paint($"FINISHED P{r.place}", Calm)
                 : r.state == RaceState.FALLEN_RECOVERING ? BroadcastUi.Paint("DOWN", Red)
                 : s.wobbling ? BroadcastUi.Paint("WOBBLE", Amber)
                 : r.state == RaceState.STUMBLE ? BroadcastUi.Paint("STUMBLE", Amber) : "racing";
    _sb.Clear();
    _sb.Append(BroadcastUi.Paint(r.name, r.color)).Append("  ").Append(state).Append('\n');
    _sb.Append(s.speed.ToString("0.00")).Append(" m/s   ").Append(s.cadence.ToString("0.0")).Append(" strides/s\n");
    _sb.Append(s.stepLength.ToString("0.00")).Append(" m stride   ").Append(s.power.ToString("0")).Append(" W");
    _tele.text = _sb.ToString();
    float effort = 0f; for (int i = 0; i < s.effort.Length; i++) effort += s.effort[i]; effort /= Mathf.Max(1, s.effort.Length);
    _effort.fillAmount = Mathf.Clamp01(effort * 2f);   // mean effort sits 0.1-0.4; x2 spreads it over the bar
    _effort.color = effort > 0.4f ? Amber : Calm;
    _riskBar.fillAmount = s.risk; _riskBar.color = s.risk > sensors.wobbleRisk ? Red : s.risk > 0.3f ? Amber : Calm;
  }
}

}
