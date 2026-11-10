using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UI;

namespace PoRace {

/// <summary>C5, pause sheet: one place for Resume / Replay last 8 s / Restart / Menu, plus the colour-blind (C8) and
/// haptics (C4, Android) toggles. Opened by the II button (TR, left of Menu), Esc / P or Android back; a bottom sheet
/// in portrait, a right-hand panel in landscape. Pausing is Time.timeScale = 0: MjScene steps in FixedUpdate, so
/// MuJoCo simply stops (the same mechanism as the instant replay) and resumes bit-for-bit. Not offered during a replay.</summary>
public class PauseSheet : MonoBehaviour {
  public MultiRaceOrchestrator race;
  public RaceReplay replay;
  public RaceDirector director;
  public float sheetHeight = 400f, sheetWidth = 580f;

  public static bool Paused { get; private set; }
  /// <summary>The II button (coach marks point at it).</summary>
  public RectTransform PauseButton { get; private set; }

  Image _dim; RectTransform _sheet; Text _cbLabel, _hapticLabel; Hud _hud;
  float _savedScale = 1f, _replayWait = -1f, _savedReplaySeconds = -1f; bool _landscape, _wasPlaying;

  void Start() {
    if (!BroadcastUi.Wired(this, race, nameof(race))) return;
    if (replay == null) replay = FindAnyObjectByType<RaceReplay>();
    if (director == null) director = FindAnyObjectByType<RaceDirector>();
    if (BroadcastUi.Headless) { enabled = false; return; }
    _hud = FindAnyObjectByType<Hud>();
    var root = BroadcastUi.Root;
    PauseButton = (RectTransform)BroadcastUi.Button(root, "BtnPause", "II", Vector2.one, Vector2.one, new Vector2(-156f, -160f), new Vector2(64f, 56f), BroadcastUi.Dark, 26, Open).transform;

    _dim = BroadcastUi.Panel(root, "PauseDim", Vector2.zero, Vector2.zero, Vector2.zero, Vector2.zero, new Color(0f, 0f, 0f, 0.5f));
    BroadcastUi.Fill(_dim.rectTransform); _dim.raycastTarget = true;
    _dim.gameObject.AddComponent<Button>().onClick.AddListener(Resume);   // tap outside the sheet resumes
    _sheet = BroadcastUi.Panel(_dim.transform, "PauseSheet", Vector2.zero, Vector2.zero, Vector2.zero, Vector2.zero, new Color(0.08f, 0.09f, 0.12f, 0.96f)).rectTransform;
    _sheet.GetComponent<Image>().raycastTarget = true;   // taps on the sheet do not fall through to the dim
    var top = new Vector2(0.5f, 1f);
    BroadcastUi.Label(_sheet, "Title", top, top, new Vector2(0f, -18f), new Vector2(400f, 50f), 34, TextAnchor.MiddleCenter, "PAUSED");
    Btn("BtnResume", "Resume", -138f, -88f, new Color(0.15f, 0.55f, 0.25f, 1f), Resume);
    Btn("BtnReplay", "Replay last 8 s", 138f, -88f, BroadcastUi.Dark, ReplayLast);
    Btn("BtnRestart", "Restart", -138f, -188f, BroadcastUi.Dark, () => { Resume(); if (_hud != null) _hud.OnReset(); else race.Restart(); });
    Btn("BtnMenuSheet", "Menu", 138f, -188f, BroadcastUi.Dark, () => { Resume(); if (_hud != null) _hud.OnMenu(); });
    _cbLabel = Btn("BtnColorBlind", "", -138f, -288f, BroadcastUi.Dark, () => { RacerPalette.ColorBlind = !RacerPalette.ColorBlind; Labels(); });
    _hapticLabel = Btn("BtnHaptics", "", 138f, -288f, BroadcastUi.Dark, () => { RaceHaptics.Enabled = !RaceHaptics.Enabled; Labels(); if (RaceHaptics.Enabled) RaceHaptics.Buzz(40); });
#if !UNITY_ANDROID
    _hapticLabel.transform.parent.gameObject.SetActive(false);   // no vibration motor to drive
#endif
    Labels();
    _built = true;
    foreach (var (n, l, act, label) in _pending) MakeExtra(n, l, act, label);
    _pending.Clear();
    UiLayout.Changed += Relayout; Relayout(BroadcastUi.Landscape);
    _dim.gameObject.SetActive(false);
  }

  // r3 C3: other components add rows (Flip leader, Graphics) below the built-in ones, two per row; the sheet grows.
  readonly System.Collections.Generic.List<(string, string, System.Action, Text)> _pending = new System.Collections.Generic.List<(string, string, System.Action, Text)>();
  bool _built; int _extra;

  /// <summary>Adds a button to the sheet and returns its label (callers may change its text). Safe before Start: the
  /// returned label is a placeholder whose text is copied when the button is built.</summary>
  public Text AddButton(string name, string label, System.Action act) {
    if (_built) return MakeExtra(name, label, act, null);
    var holder = new GameObject(name + "Pending").AddComponent<Text>(); holder.text = label; holder.gameObject.hideFlags = HideFlags.HideAndDontSave;
    _pending.Add((name, label, act, holder));
    return holder;
  }

  Text MakeExtra(string name, string label, System.Action act, Text placeholder) {
    float x = _extra % 2 == 0 ? -138f : 138f, y = -388f - 100f * (_extra / 2);
    _extra++;
    sheetHeight = Mathf.Max(sheetHeight, 400f + 100f * ((_extra + 1) / 2));
    var t = Btn(name, placeholder != null ? placeholder.text : label, x, y, BroadcastUi.Dark, act ?? (() => { }));
    if (placeholder != null) { _late.Add((placeholder, t)); }
    if (_dim != null) Relayout(_landscape);
    return t;
  }
  readonly System.Collections.Generic.List<(Text from, Text to)> _late = new System.Collections.Generic.List<(Text, Text)>();

  void OnDestroy() { UiLayout.Changed -= Relayout; if (Paused) { Paused = false; Time.timeScale = 1f; } }

  Text Btn(string name, string label, float x, float y, Color col, System.Action act) {
    var top = new Vector2(0.5f, 1f);
    var b = BroadcastUi.Button(_sheet, name, label, top, top, new Vector2(x, y), new Vector2(260f, 84f), col, 24, act);
    return b.GetComponentInChildren<Text>();
  }

  void Labels() {
    _cbLabel.text = RacerPalette.ColorBlind ? "Colour-blind: ON" : "Colour-blind: off";
    _hapticLabel.text = RaceHaptics.Enabled ? "Haptics: ON" : "Haptics: off";
  }

  void Relayout(bool landscape) {
    _landscape = landscape;
    if (landscape) { _sheet.anchorMin = new Vector2(1f, 0f); _sheet.anchorMax = Vector2.one; _sheet.pivot = new Vector2(1f, 0.5f); _sheet.sizeDelta = new Vector2(sheetWidth, 0f); }
    else { _sheet.anchorMin = Vector2.zero; _sheet.anchorMax = new Vector2(1f, 0f); _sheet.pivot = new Vector2(0.5f, 0f); _sheet.sizeDelta = new Vector2(0f, sheetHeight); }
    _sheet.anchoredPosition = Vector2.zero;
  }

  public void Open() {
    if (Paused || (replay != null && replay.Playing)) return;
    _savedScale = Time.timeScale > 0f ? Time.timeScale : 1f; Time.timeScale = 0f; Paused = true;
    _dim.gameObject.SetActive(true); _dim.transform.SetAsLastSibling();   // above UI built after the sheet
    _sheet.anchoredPosition = _landscape ? new Vector2(sheetWidth, 0f) : new Vector2(0f, -sheetHeight);   // slides in
  }

  public void Resume() {
    if (!Paused) return;
    Paused = false; Time.timeScale = _savedScale; _dim.gameObject.SetActive(false);
  }

  /// <summary>Resume, then ask RaceReplay for its whole 8 s buffer (it plays 5 s normally; restored afterwards). The
  /// replay keeps its own rules (20 s between replays, 2+ racers): if it does not start the ticker says so.</summary>
  void ReplayLast() {
    Resume();
    if (replay == null || !replay.enabled) return;
    if (_savedReplaySeconds < 0f) _savedReplaySeconds = replay.replaySeconds;
    replay.replaySeconds = replay.keepSeconds;
    var who = director != null && director.Subject != null ? director.Subject : StandingsChips.Backed ?? race.Leader();
    replay.Request(who, "REWIND", 0.05f);
    _replayWait = Time.unscaledTime + 0.5f;
  }

  void Update() {
    foreach (var (from, to) in _late) if (from != null && to != null && to.text != from.text) to.text = from.text;   // placeholders handed out before Start
    var k = Keyboard.current;
    if (k != null && (k.escapeKey.wasPressedThisFrame || k.pKey.wasPressedThisFrame)) { if (Paused) Resume(); else Open(); }
    if (Paused) _sheet.anchoredPosition = Vector2.Lerp(_sheet.anchoredPosition, Vector2.zero, 1f - Mathf.Exp(-18f * Time.unscaledDeltaTime));
    if (replay != null && _savedReplaySeconds >= 0f) {   // put the replay length back once ours played (or never started)
      bool playing = replay.Playing;
      if ((_wasPlaying && !playing) || (!playing && _replayWait > 0f && Time.unscaledTime > _replayWait)) {
        if (!_wasPlaying) BroadcastTicker.Post("Replay not ready yet", 2.5f);
        replay.replaySeconds = _savedReplaySeconds; _savedReplaySeconds = -1f; _replayWait = -1f;
      }
      if (playing) _replayWait = -1f;
      _wasPlaying = playing;
    }
  }

  // The director ends its INCIDENT slow motion by writing timeScale = 1 from Update; while paused, hold 0 (the next
  // FixedUpdate sees 0) and resume at full speed.
  void LateUpdate() { if (Paused && Time.timeScale != 0f) { _savedScale = Time.timeScale; Time.timeScale = 0f; } }
}

}
