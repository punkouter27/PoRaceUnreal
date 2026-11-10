using System;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace PoRace {

/// <summary>Pre-race broadcast hub & 16-player tournament bracket (PRD 4.1):
/// Displays the symmetric 16-player tournament bracket (8 Left, 8 Right, WINNER in Middle) directly on the Main Menu
/// alongside track selection, active agent ELO chips, and one-click Quick Race / Auto-Tournament controls.</summary>
public class MenuController : MonoBehaviour {
  public Text mapText, infoText, rosterText, lapsText, weatherText;
  [Tooltip("Roster chips: RaceConfig.Dogs in order, then Matt. Each has a Text child. Grandma's chip is cloned from Matt's at runtime.")]
  public Image[] rosterChips;
  public InputField chatInput;
  MapDefinition[] _maps; int _i, _dogMask = 0b1, _laps = 1, _weather; bool _matt, _grandma;
  Text _cbLabel, _tourneyLabel, _massRaceLabel, _autoLabel; string _hint = "";
  CreatureDefinition _grandmaCard;
  BracketScreen _bracket; AudioSource _uiVoice;
  int MattChip => RaceConfig.Dogs.Length;
  int GrandmaChip => RaceConfig.Dogs.Length + 1;
  bool GrandmaReady => _grandmaCard != null && _grandmaCard.raceable;

  void Start() {
    _maps = MapRegistry.All();
    if (_maps.Length == 0) { if (mapText) mapText.text = "No maps in Resources/Maps"; return; }
    if (RaceConfig.autoplay && !CliArgs.Has("-menuMap") && !CliArgs.RaceTest) { RaceConfig.LaunchNextAutoplay(); return; }

    var scaler = GetComponentInParent<CanvasScaler>();
    if (scaler != null) {
      scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
      scaler.referenceResolution = new Vector2(720f, 1280f);
      scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.Expand;
    }

    _dogMask = PlayerPrefs.GetInt("PoRace.dogMask", 0b1) & ((1 << RaceConfig.Dogs.Length) - 1);
    _weather = PlayerPrefs.GetInt("PoRace.weatherCity", -1);
    _matt = PlayerPrefs.GetInt("PoRace.matt", 1) == 1;
    _grandmaCard = Array.Find(CreatureRegistry.All(), c => c.displayName == "Grandma");
    _grandma = GrandmaReady && PlayerPrefs.GetInt("PoRace.grandma", 0) == 1;
    AddGrandmaChip();
    if (!BroadcastUi.Headless) { _uiVoice = gameObject.AddComponent<AudioSource>(); _uiVoice.spatialBlend = 0f; _uiVoice.playOnAwake = false; }
    if (chatInput) chatInput.text = PlayerPrefs.GetString("PoRace.twitch", "");

    Tournament.ClearLaunch();
    bool cliAuto = CliArgs.Has("-tournamentAuto");
    if (!Tournament.Active) {
      Tournament.Begin(Tournament.Entrants(), autoPlay: cliAuto);
    } else if (cliAuto) {
      Tournament.AutoPlay = true;
    }

    LayoutProfessionalMenu();
    SelectMap(0);

    if (cliAuto && !Tournament.Done) Invoke(nameof(RaceNextMatch), 2.2f);
    if (CliArgs.TryInt("-menuMap", out int mm)) {
      Tournament.AutoPlay = false;
      if (_bracket != null) _bracket.CancelAutoCountdown();
      SelectMap(mm);
      Invoke(nameof(OnLaunch), 0.5f);
    }
  }

  static void Place(Transform parent, string childName, Vector2 pos, Vector2 size, int fontSize = 0, Color? textCol = null, TextAnchor? align = null) {
    var tr = parent.Find(childName) as RectTransform;
    if (tr == null) return;
    tr.anchorMin = tr.anchorMax = new Vector2(0.5f, 1f);
    tr.pivot = new Vector2(0.5f, 0.5f);
    tr.anchoredPosition = pos;
    tr.sizeDelta = size;
    var txt = tr.GetComponent<Text>() ?? tr.GetComponentInChildren<Text>();
    if (txt != null) {
      if (fontSize > 0) txt.fontSize = fontSize;
      if (textCol.HasValue) txt.color = textCol.Value;
      if (align.HasValue) txt.alignment = align.Value;
    }
  }

  void LayoutProfessionalMenu() {
    float canvasW = 1280f * Mathf.Max(720f / 1280f, (float)Screen.width / Mathf.Max(1f, Screen.height));
    float W = Mathf.Clamp(canvasW - 48f, 708f, 2180f);
    bool wide = W >= 1360f;
    var topCenter = new Vector2(0.5f, 1f);
    var mid = new Vector2(0.5f, 0.5f);

    // Hide optional Twitch chat fields to keep the primary viewport clean while preserving UiSelfTest bindings
    var chatLbl = transform.Find("ChatLabel"); if (chatLbl != null) chatLbl.gameObject.SetActive(false);
    if (chatInput != null) chatInput.gameObject.SetActive(false);

    // 1. Background cards (sent to back of canvas so existing labels/buttons render on top)
    var headerBg = BroadcastUi.Panel(transform, "HeaderBg", topCenter, mid, new Vector2(0f, -42f), new Vector2(W, 72f), new Color(0.06f, 0.08f, 0.12f, 0.98f));
    var headerLine = BroadcastUi.Panel(transform, "HeaderLine", topCenter, mid, new Vector2(0f, -78f), new Vector2(W, 3f), BroadcastUi.Accent);

    Image deckLeftBg = null, deckRightBg = null;
    if (wide) {
      float halfW = (W - 20f) * 0.5f;
      deckLeftBg = BroadcastUi.Panel(transform, "DeckLeftBg", topCenter, mid, new Vector2(-halfW * 0.5f - 5f, -168f), new Vector2(halfW, 160f), new Color(0.08f, 0.11f, 0.17f, 0.96f));
      deckRightBg = BroadcastUi.Panel(transform, "DeckRightBg", topCenter, mid, new Vector2(halfW * 0.5f + 5f, -168f), new Vector2(halfW, 160f), new Color(0.08f, 0.11f, 0.17f, 0.96f));
    } else {
      deckLeftBg = BroadcastUi.Panel(transform, "DeckLeftBg", topCenter, mid, new Vector2(0f, -168f), new Vector2(W, 160f), new Color(0.08f, 0.11f, 0.17f, 0.96f));
    }

    headerBg.transform.SetAsFirstSibling();
    headerLine.transform.SetSiblingIndex(1);
    if (deckLeftBg != null) deckLeftBg.transform.SetSiblingIndex(2);
    if (deckRightBg != null) deckRightBg.transform.SetSiblingIndex(3);

    // 2. Top Header Bar (y = -42)
    if (wide) {
      Place(transform, "Title", new Vector2(-W * 0.5f + 420f, -42f), new Vector2(800f, 58f), 38, BroadcastUi.Accent, TextAnchor.MiddleLeft);
      var titleTxt = transform.Find("Title")?.GetComponent<Text>();
      if (titleTxt != null) { titleTxt.text = "PORACE  ·  16-AGENT CHAMPIONSHIP"; titleTxt.fontStyle = FontStyle.Bold; }
    } else {
      Place(transform, "Title", new Vector2(-190f, -42f), new Vector2(310f, 58f), 34, BroadcastUi.Accent, TextAnchor.MiddleLeft);
    }

    float cbX = wide ? (W * 0.5f - 170f) : 185f;
    float cbW = wide ? 310f : 310f;
    _cbLabel = BroadcastUi.Button(transform, "BtnColorBlind", "", topCenter, mid, new Vector2(cbX, -42f), new Vector2(cbW, 50f),
        new Color(0.14f, 0.18f, 0.26f, 0.98f), 22, () => { RacerPalette.ColorBlind = !RacerPalette.ColorBlind; Refresh(); }).GetComponentInChildren<Text>();

    if (wide) {
      var reseedBtn = BroadcastUi.Button(transform, "BtnReseedTop", "RESEED 16P BRACKET", topCenter, mid, new Vector2(W * 0.5f - 480f, -42f), new Vector2(270f, 50f),
          new Color(0.22f, 0.27f, 0.38f, 0.98f), 22, () => {
            Tournament.Begin(Tournament.Entrants(), autoPlay: Tournament.AutoPlay);
            if (_bracket != null) _bracket.Refresh();
            Refresh();
          });
      var autoTopBtn = BroadcastUi.Button(transform, "BtnAutoTop", "", topCenter, mid, new Vector2(W * 0.5f - 780f, -42f), new Vector2(290f, 50f),
          new Color(0.15f, 0.34f, 0.48f, 0.98f), 22, ToggleAutoTournament);
      _autoLabel = autoTopBtn.GetComponentInChildren<Text>();
    }

    // 3. Control Deck (y = -96 to -244)
    Color subHdrCol = new Color(0.62f, 0.74f, 0.88f, 0.95f);
    if (wide) {
      float lx = -W * 0.25f - 5f;
      float trackX = lx - 235f;
      Place(transform, "TrackLabel", new Vector2(trackX, -112f), new Vector2(380f, 30f), 22, subHdrCol);
      Place(transform, "BtnPrevMap", new Vector2(trackX - 215f, -158f), new Vector2(58f, 54f), 26);
      Place(transform, "MapName", new Vector2(trackX, -158f), new Vector2(350f, 54f), 30, Color.white);
      Place(transform, "BtnNextMap", new Vector2(trackX + 215f, -158f), new Vector2(58f, 54f), 26);
      Place(transform, "MapInfo", new Vector2(trackX, -214f), new Vector2(490f, 54f), 22, new Color(0.82f, 0.88f, 0.96f));

      float lapsX = lx + 170f;
      Place(transform, "LapsLabel", new Vector2(lapsX, -112f), new Vector2(180f, 30f), 22, subHdrCol);
      Place(transform, "BtnLapsDown", new Vector2(lapsX - 74f, -166f), new Vector2(54f, 54f), 26);
      Place(transform, "Laps", new Vector2(lapsX, -166f), new Vector2(80f, 54f), 30, Color.white);
      Place(transform, "BtnLapsUp", new Vector2(lapsX + 74f, -166f), new Vector2(54f, 54f), 26);

      float wxX = lx + 390f;
      Place(transform, "WeatherLabel", new Vector2(wxX, -112f), new Vector2(210f, 30f), 22, subHdrCol);
      Place(transform, "BtnWeatherPrev", new Vector2(wxX - 88f, -166f), new Vector2(50f, 54f), 24);
      Place(transform, "Weather", new Vector2(wxX, -166f), new Vector2(116f, 54f), 22, Color.white);
      Place(transform, "BtnWeatherNext", new Vector2(wxX + 88f, -166f), new Vector2(50f, 54f), 24);

      // Right Deck: Active Roster & ELO Chips
      float rx = W * 0.25f + 5f;
      Place(transform, "RosterLabel", new Vector2(rx, -112f), new Vector2(980f, 32f), 22, subHdrCol);
      int nChips = rosterChips != null ? rosterChips.Length : 0;
      float chipW = 240f, chipGap = 24f;
      float totalChipsW = nChips * chipW + Mathf.Max(0, nChips - 1) * chipGap;
      float startChipX = rx - totalChipsW * 0.5f + chipW * 0.5f;
      for (int i = 0; i < nChips; i++) {
        var crt = rosterChips[i].rectTransform;
        crt.anchorMin = crt.anchorMax = topCenter;
        crt.pivot = mid;
        crt.anchoredPosition = new Vector2(startChipX + i * (chipW + chipGap), -184f);
        crt.sizeDelta = new Vector2(chipW, 82f);
        var lbl = crt.GetComponentInChildren<Text>();
        if (lbl != null) lbl.fontSize = 22;
      }
    } else {
      // Compact portrait layout (720 x 1280) with zero overlap
      Place(transform, "TrackLabel", new Vector2(-180f, -106f), new Vector2(300f, 28f), 22, subHdrCol);
      Place(transform, "BtnPrevMap", new Vector2(-318f, -148f), new Vector2(50f, 48f), 24);
      Place(transform, "MapName", new Vector2(-180f, -148f), new Vector2(216f, 48f), 24, Color.white);
      Place(transform, "BtnNextMap", new Vector2(-42f, -148f), new Vector2(50f, 48f), 24);
      Place(transform, "MapInfo", new Vector2(-180f, -204f), new Vector2(320f, 60f), 22, new Color(0.82f, 0.88f, 0.96f));

      Place(transform, "LapsLabel", new Vector2(82f, -106f), new Vector2(120f, 28f), 22, subHdrCol);
      Place(transform, "BtnLapsDown", new Vector2(34f, -148f), new Vector2(44f, 48f), 24);
      Place(transform, "Laps", new Vector2(82f, -148f), new Vector2(48f, 48f), 24, Color.white);
      Place(transform, "BtnLapsUp", new Vector2(130f, -148f), new Vector2(44f, 48f), 24);

      Place(transform, "WeatherLabel", new Vector2(252f, -106f), new Vector2(180f, 28f), 22, subHdrCol);
      Place(transform, "BtnWeatherPrev", new Vector2(186f, -148f), new Vector2(42f, 48f), 22);
      Place(transform, "Weather", new Vector2(252f, -148f), new Vector2(86f, 48f), 22, Color.white);
      Place(transform, "BtnWeatherNext", new Vector2(318f, -148f), new Vector2(42f, 48f), 22);

      Place(transform, "RosterLabel", new Vector2(170f, -190f), new Vector2(340f, 28f), 22, subHdrCol);
      int nChips = rosterChips != null ? rosterChips.Length : 0;
      for (int i = 0; i < nChips; i++) {
        var crt = rosterChips[i].rectTransform;
        crt.anchorMin = crt.anchorMax = topCenter;
        crt.pivot = mid;
        crt.anchoredPosition = new Vector2(56f + i * 114f, -224f);
        crt.sizeDelta = new Vector2(108f, 44f);
        var lbl = crt.GetComponentInChildren<Text>();
        if (lbl != null) lbl.fontSize = 22;
      }
    }

    // 4. Center Stage: 16-Player Symmetric Tournament Bracket (always shown on the Main Menu)
    if (_bracket == null) {
      _bracket = BracketScreen.Create(transform);
      _bracket.onStateChanged = UpdateTournamentButtons;
    }
    _bracket.gameObject.SetActive(true);

    // 5. Bottom Broadcast Action Bar (y = -1198):
    //   - Left:   1v1 16-Player Bracket Match (Dog vs Matt)
    //   - Middle: 16-At-A-Time Race (All Existing Trained Players)
    //   - Right:  Quick Race (Selected Track)
    Button start = null;
    foreach (var b in GetComponentsInChildren<Button>(true)) if (b.name == "BtnStart") start = b;
    if (start != null) {
      var srt = (RectTransform)start.transform;
      srt.anchorMin = srt.anchorMax = topCenter;
      srt.pivot = mid;
      float btnW = wide ? 460f : 224f;
      float gap = wide ? 24f : 10f;
      int btnFont = wide ? 22 : 18;

      var t = BroadcastUi.Button(srt.parent, "BtnTournament", "", topCenter, mid,
          new Vector2(-(btnW + gap), -1198f), new Vector2(btnW, 84f),
          new Color(0.15f, 0.55f, 0.25f, 1f), btnFont, OnTournamentAction);
      _tourneyLabel = t.GetComponentInChildren<Text>();

      var massBtn = BroadcastUi.Button(srt.parent, "BtnMassRace", "", topCenter, mid,
          new Vector2(0f, -1198f), new Vector2(btnW, 84f),
          new Color(0.42f, 0.22f, 0.68f, 1f), btnFont, OnMassRaceAction);
      _massRaceLabel = massBtn.GetComponentInChildren<Text>();

      srt.sizeDelta = new Vector2(btnW, 84f);
      srt.anchoredPosition = new Vector2(btnW + gap, -1198f);
      start.GetComponent<Image>().color = new Color(0.16f, 0.38f, 0.68f, 1f);
      var sLbl = start.GetComponentInChildren<Text>();
      if (sLbl != null) { sLbl.fontSize = btnFont; sLbl.text = wide ? "QUICK RACE (SELECTED TRACK)" : "QUICK RACE"; }
    }

    // Version watermark in bottom-right corner
    var verTr = transform.Find("Version") as RectTransform;
    if (verTr != null) {
      verTr.anchorMin = verTr.anchorMax = new Vector2(1f, 0f);
      verTr.pivot = new Vector2(1f, 0f);
      verTr.anchoredPosition = new Vector2(-18f, 14f);
      verTr.sizeDelta = new Vector2(240f, 34f);
    }

    UpdateTournamentButtons();
  }

  void ToggleAutoTournament() {
    if (Tournament.Done) Tournament.Begin(Tournament.Entrants(), autoPlay: true);
    else Tournament.AutoPlay = !Tournament.AutoPlay;
    if (_bracket != null) {
      if (Tournament.AutoPlay) _bracket.TriggerAutoCountdown(2.2f);
      else _bracket.CancelAutoCountdown();
      _bracket.Refresh();
    }
    UpdateTournamentButtons();
  }

  public void OnTournamentAction() {
    if (!Tournament.Active || Tournament.Done) {
      Tournament.Begin(Tournament.Entrants(), autoPlay: true);
      if (_bracket != null) _bracket.Refresh();
      UpdateTournamentButtons();
      return;
    }
    Tournament.AutoPlay = true;
    Tournament.LaunchNext();
  }

  public void OnMassRaceAction() {
    if (_bracket != null) _bracket.CancelAutoCountdown();
    string ch = chatInput ? chatInput.text.Trim() : "";
    Tournament.LaunchAllTrained(_maps[_i], _laps, _weather, ch);
  }

  public void OnTournament() => OnTournamentAction();

  void UpdateTournamentButtons() {
    if (_autoLabel != null) {
      _autoLabel.text = Tournament.AutoPlay ? "AUTO-TOURNEY: ON" : "AUTO-TOURNEY: OFF";
    }
    if (_tourneyLabel != null) {
      if (Tournament.Done) {
        _tourneyLabel.text = "NEW 1v1 16P BRACKET";
      } else if (Tournament.Next(out int r, out int m, out string a, out string b)) {
        _tourneyLabel.text = $"1v1 BRACKET ({Tournament.RoundNames[r]}: {a} vs {b})";
      } else {
        _tourneyLabel.text = "START 1v1 16P BRACKET";
      }
    }
    if (_massRaceLabel != null) {
      var entrants = Tournament.Entrants();
      _massRaceLabel.text = $"16-AT-A-TIME RACE\n(ALL {entrants.Count} TRAINED: {string.Join(" + ", entrants)})";
    }
  }

  void SelectMap(int i) {
    _i = ((i % _maps.Length) + _maps.Length) % _maps.Length;
    _laps = _maps[_i].closed ? _maps[_i].defaultLaps : 1;
    if (Count() == 0) _dogMask = 1;
    Refresh();
  }

  void AddGrandmaChip() {
    if (rosterChips == null || rosterChips.Length != MattChip + 1) return;
    var matt = rosterChips[MattChip]; var mrt = matt.rectTransform;
    var chip = Instantiate(matt, mrt.parent); chip.name = "ChipGrandma";
    var step = MattChip > 0 ? mrt.anchoredPosition - rosterChips[MattChip - 1].rectTransform.anchoredPosition : new Vector2(mrt.rect.width + 12f, 0f);
    if (mrt.parent.GetComponent<LayoutGroup>() == null) chip.rectTransform.anchoredPosition = mrt.anchoredPosition + step;
    var b = chip.GetComponent<Button>();
    if (b != null) { b.onClick = new Button.ButtonClickedEvent(); int k = GrandmaChip; b.onClick.AddListener(() => OnRosterToggle(k)); }
    var chips = new Image[rosterChips.Length + 1]; rosterChips.CopyTo(chips, 0); chips[GrandmaChip] = chip; rosterChips = chips;
  }

  void RaceNextMatch() => Tournament.LaunchNext();

  int Eligible(MapDefinition m) => Mathf.Min(m.gridSlots, RaceConfig.Dogs.Length + (m.terrain == "flat" ? 1 + (GrandmaReady ? 1 : 0) : 0));

  void Refresh() {
    var m = _maps[_i]; int most = Eligible(m);
    if (mapText) mapText.text = m.displayName;
    if (infoText) {
      infoText.text = $"{m.Length * (m.closed ? _laps : 1):F0} m · {m.terrain} · {(m.closed ? "circuit" : "sprint")} · up to {most} racer{(most == 1 ? "" : "s")} ({_i + 1}/{_maps.Length})";
    }
    if (lapsText) lapsText.text = m.closed ? _laps.ToString() : "-";
    bool flat = m.terrain == "flat";
    for (int i = 0; rosterChips != null && i < rosterChips.Length; i++) {
      bool isMatt = i == MattChip, isGm = i == GrandmaChip, human = isMatt || isGm;
      bool locked = isGm && !GrandmaReady, on = isMatt ? _matt && flat : isGm ? _grandma && flat && !locked : (_dogMask >> i & 1) != 0;
      var col = RacerPalette.Get(i, isMatt ? RaceConfig.MattColor : isGm ? RaceConfig.GrandmaColor : RaceConfig.Dogs[i].color);
      rosterChips[i].color = on ? col : new Color(col.r * 0.25f, col.g * 0.25f, col.b * 0.25f, 0.95f);
      var label = rosterChips[i].GetComponentInChildren<Text>();
      string who = isMatt ? "Matt" : isGm ? "Grandma" : RaceConfig.Dogs[i].name;
      int elo = AgentElo.Rating(who);
      string stateTag = locked ? "TRAINING" : human && !flat ? "FLAT ONLY" : on ? "ACTIVE" : "BENCH";
      label.text = $"{RacerPalette.Glyph(i)}{(RacerPalette.ColorBlind ? " " : "")}<b>{who}</b> · {elo}\n{stateTag}";
      label.color = on ? new Color(0.06f, 0.08f, 0.12f) : new Color(1f, 1f, 1f, locked || (human && !flat) ? 0.45f : 0.80f);
    }
    int activeEntrants = Tournament.Entrants().Count;
    if (rosterText) {
      rosterText.text = _hint != "" ? _hint : $"ACTIVE ROSTER ({Count()} ON GRID)  ·  16-SLOT BRACKET ({activeEntrants} READY + {16 - activeEntrants} BYE)";
    }
    if (_cbLabel) _cbLabel.text = RacerPalette.ColorBlind ? "Colour-blind: ON" : "Colour-blind: off";
    if (weatherText) weatherText.text = _weather >= 0 && _weather < TrackWeather.Cities.Length ? TrackWeather.Cities[_weather].name : "off";
    if (_bracket != null) _bracket.Refresh();
    UpdateTournamentButtons();
  }

  public void OnWeatherNext() { _weather = _weather + 1 >= TrackWeather.Cities.Length ? -1 : _weather + 1; Refresh(); }
  public void OnWeatherPrev() { _weather = _weather - 1 < -1 ? TrackWeather.Cities.Length - 1 : _weather - 1; Refresh(); }

  public void OnRosterToggle(int i) {
    _hint = "";
    string who = i == GrandmaChip ? "Grandma" : i == MattChip ? "Matt" : RaceConfig.Dogs[Mathf.Clamp(i, 0, RaceConfig.Dogs.Length - 1)].name;
    if (i == GrandmaChip) {
      if (!GrandmaReady) {
        _hint = "Grandma: RL policy in training (procedural voice active)";
        if (_uiVoice != null) _uiVoice.PlayOneShot(AgentSounds.Clip("Grandma", AgentEmotion.Insult, 1, 3), 0.8f);
        Refresh(); return;
      }
      if (_maps[_i].terrain != "flat" || (_grandma && Count() == 1)) return; _grandma = !_grandma;
    }
    else if (i == MattChip) { if (_maps[_i].terrain != "flat" || (_matt && Count() == 1)) return; _matt = !_matt; }
    else { int bit = 1 << i; if ((_dogMask & bit) != 0 && Count() == 1) return; _dogMask ^= bit; }
    bool nowIn = i == GrandmaChip ? _grandma : i == MattChip ? _matt : (_dogMask >> i & 1) != 0;
    if (_uiVoice != null) _uiVoice.PlayOneShot(AgentSounds.Clip(who, nowIn ? AgentEmotion.Happy : AgentEmotion.Angry, 1, nowIn ? 4 : 2), 0.8f);
    Refresh();
  }

  int Count() {
    bool flat = _maps[_i].terrain == "flat";
    int n = (_matt && flat ? 1 : 0) + (_grandma && GrandmaReady && flat ? 1 : 0);
    for (int m = _dogMask; m != 0; m &= m - 1) n++;
    return n;
  }

  public void OnNextMap() => SelectMap(_i + 1);
  public void OnPrevMap() => SelectMap(_i - 1);
  public void OnLapsUp() { if (_maps[_i].closed) _laps = Mathf.Min(_laps + 1, 5); Refresh(); }
  public void OnLapsDown() { if (_maps[_i].closed) _laps = Mathf.Max(_laps - 1, 1); Refresh(); }

  public void OnLaunch() {
    Tournament.AutoPlay = false;
    if (_bracket != null) _bracket.CancelAutoCountdown();
    RaceConfig.dogMask = _dogMask; RaceConfig.laps = _laps; RaceConfig.seed = -1; RaceConfig.fromMenu = true;
    RaceConfig.weatherCity = _weather; RaceConfig.twitchChannel = chatInput ? chatInput.text.Trim() : "";
    RaceConfig.matt = _matt && _maps[_i].terrain == "flat";
    RaceConfig.grandma = _grandma && GrandmaReady && _maps[_i].terrain == "flat";
    try {
      PlayerPrefs.SetInt("PoRace.matt", _matt ? 1 : 0);
      PlayerPrefs.SetInt("PoRace.grandma", _grandma ? 1 : 0);
      PlayerPrefs.SetInt("PoRace.dogMask", _dogMask);
      PlayerPrefs.SetInt("PoRace.weatherCity", _weather);
      PlayerPrefs.SetString("PoRace.twitch", RaceConfig.twitchChannel);
      PlayerPrefs.Save();
    } catch { }
    SceneManager.LoadScene(_maps[_i].sceneName);
  }
}

}
