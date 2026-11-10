using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace PoRace {

/// <summary>16-player symmetric tournament bracket embedded directly on the Main Menu canvas:
///   - 8 starting players on the LEFT side (Slots 0..7) advancing inward (R16 -> QF -> SF -> Left Finalist)
///   - 8 starting players on the RIGHT side (Slots 8..15) advancing inward (R16 -> QF -> SF -> Right Finalist)
///   - Single WINNER / CHAMPION box in the MIDDLE (x = 0) between the Left and Right Finalists.
/// Untrained slots are filled with BYE placeholders (mapped to Grandma & Agent04..Agent16).
/// Displays live ELO ratings and plays each character's procedural vocal sounds (HAPPY, ANGRY, HURT, INSULT) when clicked.</summary>
public class BracketScreen : MonoBehaviour {
  static readonly Color BgPanel = new Color(0.06f, 0.08f, 0.12f, 0.98f),
                        BorderCol = new Color(0.18f, 0.24f, 0.34f, 1f),
                        LineCol = new Color(0.32f, 0.42f, 0.58f, 0.65f),
                        HotLineCol = new Color(0.95f, 0.78f, 0.10f, 0.90f),
                        EntryBg = new Color(0.12f, 0.15f, 0.22f, 1f),
                        ByeBg = new Color(0.09f, 0.11f, 0.16f, 0.92f),
                        NextUpBg = new Color(0.32f, 0.25f, 0.06f, 1f),
                        ChampBg = new Color(0.28f, 0.22f, 0.05f, 1f),
                        ByeTextCol = new Color(0.68f, 0.75f, 0.86f, 0.55f);

  public Action onLeave;
  public Action onStateChanged;
  RectTransform _root, _grid;
  Text _sub;
  AudioSource _voice;
  float _autoCountdown = -1f;
  int _voiceCycle;
  readonly List<GameObject> _cells = new List<GameObject>();

  public float AutoCountdown => _autoCountdown;

  public static BracketScreen Create(Transform canvas, Action onLeave = null) {
    var go = new GameObject("Bracket");
    go.transform.SetParent(canvas, false);
    var rt = go.AddComponent<RectTransform>();
    rt.anchorMin = rt.anchorMax = new Vector2(0.5f, 1f);
    rt.pivot = new Vector2(0.5f, 0.5f);
    var img = go.AddComponent<Image>();
    img.color = BgPanel;
    img.raycastTarget = false;
    var s = go.AddComponent<BracketScreen>();
    s._root = rt;
    s.onLeave = onLeave;
    if (!BroadcastUi.Headless) {
      s._voice = go.AddComponent<AudioSource>();
      s._voice.spatialBlend = 0f;
      s._voice.playOnAwake = false;
    }
    s.Build();
    return s;
  }

  void Build() {
    _grid = BroadcastUi.Rect(_root, "Grid", new Vector2(0.5f, 1f), new Vector2(0.5f, 1f), Vector2.zero, Vector2.zero);
    _sub = BroadcastUi.Label(_root, "Sub", new Vector2(0.5f, 1f), new Vector2(0.5f, 0.5f), new Vector2(0f, -24f), new Vector2(680f, 36f), 22, TextAnchor.MiddleCenter, "");
    Refresh();
  }

  /// <summary>Placeholder character name for the i-th BYE slot so all 16 characters are uniquely represented on the bracket.</summary>
  static string PlaceholderAgentForSlot(int slotIdx, int byeOrdinal) {
    var active = Tournament.Entrants();
    var placeholders = new List<string>();
    if (!active.Contains("Grandma")) placeholders.Add("Grandma");
    for (int a = 4; a <= 16; a++) {
      string name = $"Agent{a:00}";
      if (!active.Contains(name)) placeholders.Add(name);
    }
    if (byeOrdinal >= 0 && byeOrdinal < placeholders.Count) return placeholders[byeOrdinal];
    return $"Agent{Mathf.Clamp(slotIdx + 1, 4, 16):00}";
  }

  public void TriggerAutoCountdown(float sec = 2.5f) {
    _autoCountdown = sec;
  }

  public void CancelAutoCountdown() {
    _autoCountdown = -1f;
  }

  public void Refresh() {
    foreach (var c in _cells) if (c != null) Destroy(c);
    _cells.Clear();
    if (!Tournament.Active) Tournament.Begin(Tournament.Entrants(), autoPlay: false);

    float canvasW = 1280f * Mathf.Max(720f / 1280f, (float)Screen.width / Mathf.Max(1f, Screen.height));
    float W = Mathf.Clamp(canvasW - 48f, 708f, 2180f);
    bool wide = W >= 1360f;
    float H = 856f;
    _root.anchoredPosition = new Vector2(0f, -688f);
    _root.sizeDelta = new Vector2(W, H);

    // Top accent border on bracket frame
    var topLine = BroadcastUi.Panel(_grid, "TopBorder", new Vector2(0.5f, 1f), new Vector2(0.5f, 0.5f), new Vector2(0f, -1f), new Vector2(W, 2f), BorderCol);
    _cells.Add(topLine.gameObject);

    bool next = Tournament.Next(out int nr, out int nm, out string na, out string nb);
    int racers = 0; foreach (var s in Tournament.Seeds) if (s > 0) racers++;

    _sub.rectTransform.sizeDelta = new Vector2(W - 24f, 36f);
    _sub.rectTransform.anchoredPosition = new Vector2(0f, -22f);
    if (Tournament.Done && !string.IsNullOrEmpty(Tournament.Champion)) {
      string ch = Tournament.Champion;
      _sub.text = $"CHAMPION CROWNED IN MIDDLE: {BroadcastUi.Paint(ch, ColorOf(ch))} ({AgentElo.Rating(ch)} ELO)  ·  Click any slot to hear agent voice";
      _autoCountdown = -1f;
      PlayAgentVoice(ch, AgentEmotion.Happy, 5);
    } else if (next) {
      string modeTxt = Tournament.AutoPlay ? $"AUTO-PLAYING NEXT 1v1 ({Mathf.Max(0.1f, _autoCountdown):0.0}s)" : "1v1 BRACKET + 16-AT-A-TIME READY";
      _sub.text = $"1v1 16-PLAYER BRACKET ({racers} Trained + {Tournament.Slots - racers} BYE)  ·  Next 1v1: {Tournament.RoundNames[nr]} ({na} vs {nb})  ·  {modeTxt}";
      if (Tournament.AutoPlay && _autoCountdown < 0f) _autoCountdown = 2.6f;
    } else {
      _sub.text = $"1v1 16-PLAYER BRACKET ({racers} Trained + {Tournament.Slots - racers} BYE)  ·  16-At-A-Time Race Available Below";
    }

    // Symmetrical column X centers relative to x = 0 (center of screen)
    float finalistW = wide ? 248f : 144f;
    float champW = wide ? 276f : 156f;
    float r16W = wide ? 268f : 92f;
    float qfW = wide ? 224f : 84f;
    float sfW = wide ? 224f : 84f;

    float xSF = wide ? 290f : 126f;
    float xQF = wide ? 560f : 216f;
    float xR16 = wide ? 855f : 308f;

    float[] sideX = { xR16, xQF, xSF };
    float[] sideW = { r16W, qfW, sfW };

    // Column headers at y = -54
    AddHeader(-xR16, r16W, wide ? "LEFT 8 (R16)" : "LEFT 8");
    AddHeader(-xQF, qfW, wide ? "QUARTERFINAL" : "QF");
    AddHeader(-xSF, sfW, wide ? "SEMIFINAL" : "SF");
    AddHeader(0f, champW, wide ? "FINAL & WINNER" : "MIDDLE", true);
    AddHeader(xSF, sfW, wide ? "SEMIFINAL" : "SF");
    AddHeader(xQF, qfW, wide ? "QUARTERFINAL" : "QF");
    AddHeader(xR16, r16W, wide ? "RIGHT 8 (R16)" : "RIGHT 8");

    float topY = 76f;
    float gridH = 768f;
    float entryH = 74f;
    float RowY(int r, int sideIdx) => topY + (sideIdx + 0.5f) * gridH / (8 >> r);

    // Bracket connector lines for Left wing and Right wing (R16 -> QF -> SF)
    for (int r = 0; r < 2; r++) {
      int matchesPerSide = 4 >> r;
      for (int m = 0; m < matchesPerSide; m++) {
        float y0 = RowY(r, 2 * m), y1 = RowY(r, 2 * m + 1), ym = RowY(r + 1, m);
        // Left side: from inner edge of -sideX[r] to outer edge of -sideX[r+1]
        float lx0 = -sideX[r] + sideW[r] * 0.5f;
        float lx1 = -sideX[r + 1] - sideW[r + 1] * 0.5f;
        float lMid = (lx0 + lx1) * 0.5f;
        DrawHLine(lx0, lMid, y0, LineCol);
        DrawHLine(lx0, lMid, y1, LineCol);
        DrawVLine(lMid, y0, y1, LineCol);
        DrawHLine(lMid, lx1, ym, LineCol);

        // Right side: mirror image
        float rx0 = sideX[r] - sideW[r] * 0.5f;
        float rx1 = sideX[r + 1] + sideW[r + 1] * 0.5f;
        float rMid = (rx0 + rx1) * 0.5f;
        DrawHLine(rMid, rx0, y0, LineCol);
        DrawHLine(rMid, rx0, y1, LineCol);
        DrawVLine(rMid, y0, y1, LineCol);
        DrawHLine(rx1, rMid, ym, LineCol);
      }
    }

    // Center Finalists and Winner positions
    float leftFinalY = 230f;
    float champY = 460f;
    float rightFinalY = 690f;
    float finalistH = 92f;
    float champH = 142f;

    // Connect Left SF (r=2, i=0..1) -> Left Finalist, and Right SF (r=2, i=0..1) -> Right Finalist
    float sfY0 = RowY(2, 0), sfY1 = RowY(2, 1);
    float lSfInner = -xSF + sfW * 0.5f;
    float rSfInner = xSF - sfW * 0.5f;
    float cLeftEdge = -finalistW * 0.5f;
    float cRightEdge = finalistW * 0.5f;
    float lBridgeX = (lSfInner + cLeftEdge) * 0.5f;
    float rBridgeX = (rSfInner + cRightEdge) * 0.5f;

    DrawHLine(lSfInner, lBridgeX, sfY0, LineCol);
    DrawHLine(lSfInner, lBridgeX, sfY1, LineCol);
    DrawVLine(lBridgeX, leftFinalY, sfY1, LineCol);
    DrawHLine(lBridgeX, cLeftEdge, leftFinalY, HotLineCol);

    DrawHLine(rBridgeX, rSfInner, sfY0, LineCol);
    DrawHLine(rBridgeX, rSfInner, sfY1, LineCol);
    DrawVLine(rBridgeX, sfY0, rightFinalY, LineCol);
    DrawHLine(cRightEdge, rBridgeX, rightFinalY, HotLineCol);

    // Center spine connecting Left Finalist -> WINNER <- Right Finalist
    DrawVLine(0f, leftFinalY + finalistH * 0.5f, champY - champH * 0.5f, HotLineCol, 4f);
    DrawVLine(0f, champY + champH * 0.5f, rightFinalY - finalistH * 0.5f, HotLineCol, 4f);

    // Map BYE slots in R16 to placeholder agents so all 16 characters are visible
    int byeCounter = 0;
    string[] r16Placeholder = new string[16];
    for (int s = 0; s < 16; s++) {
      if (Tournament.Rounds[0][s] == Tournament.Bye)
        r16Placeholder[s] = PlaceholderAgentForSlot(s, byeCounter++);
    }

    // Draw Left & Right wing cells for r = 0 (8 per side), r = 1 (4 per side), r = 2 (2 per side)
    for (int r = 0; r < 3; r++) {
      int half = 8 >> r;
      for (int i = 0; i < half; i++) {
        int leftIdx = i;
        bool hotL = next && r == nr && (leftIdx == 2 * nm || leftIdx == 2 * nm + 1);
        DrawSideCell(r, i, -sideX[r], sideW[r], RowY(r, i), entryH, leftIdx + 1,
            Tournament.Rounds[r][leftIdx], r == 0 ? r16Placeholder[leftIdx] : null, hotL, wide);

        int rightIdx = half + i;
        bool hotR = next && r == nr && (rightIdx == 2 * nm || rightIdx == 2 * nm + 1);
        DrawSideCell(r, i, sideX[r], sideW[r], RowY(r, i), entryH, rightIdx + 1,
            Tournament.Rounds[r][rightIdx], r == 0 ? r16Placeholder[rightIdx] : null, hotR, wide);
      }
    }

    // Draw Center Column: Left Finalist, WINNER in Middle, Right Finalist
    bool hotFinal = next && nr == 3 && nm == 0;
    DrawCenterFinalist("FinalistL", leftFinalY, finalistW, finalistH, "LEFT CHAMPION", Tournament.Rounds[3][0], Tournament.Notes[3][0], hotFinal);
    DrawCenterChampion(champY, champW, champH, Tournament.Rounds[4][0]);
    DrawCenterFinalist("FinalistR", rightFinalY, finalistW, finalistH, "RIGHT CHAMPION", Tournament.Rounds[3][1], Tournament.Notes[3][1], hotFinal);

    onStateChanged?.Invoke();
  }

  void Update() {
    if (!Tournament.Active || Tournament.Done || !Tournament.AutoPlay) return;
    if (_autoCountdown < 0f) return;
    _autoCountdown -= Time.unscaledDeltaTime;
    if (_autoCountdown <= 0f) {
      _autoCountdown = -1f;
      Tournament.LaunchNext();
    }
  }

  void AddHeader(float x, float w, string text, bool highlight = false) {
    var lbl = BroadcastUi.Label(_grid, "Hdr_" + text, new Vector2(0.5f, 1f), new Vector2(0.5f, 0.5f),
        new Vector2(x, -54f), new Vector2(w + 16f, 34f), 22, TextAnchor.MiddleCenter, text);
    lbl.fontStyle = FontStyle.Bold;
    lbl.color = highlight ? BroadcastUi.Accent : new Color(0.65f, 0.75f, 0.88f, 0.9f);
    _cells.Add(lbl.gameObject);
  }

  void DrawHLine(float x0, float x1, float y, Color col, float thick = 2.5f) {
    float cx = (x0 + x1) * 0.5f, w = Mathf.Max(thick, Mathf.Abs(x1 - x0));
    var b = BroadcastUi.Panel(_grid, "HLine", new Vector2(0.5f, 1f), new Vector2(0.5f, 0.5f), new Vector2(cx, -y), new Vector2(w, thick), col);
    _cells.Add(b.gameObject);
  }

  void DrawVLine(float x, float y0, float y1, Color col, float thick = 2.5f) {
    float cy = (y0 + y1) * 0.5f, h = Mathf.Max(thick, Mathf.Abs(y1 - y0));
    var b = BroadcastUi.Panel(_grid, "VLine", new Vector2(0.5f, 1f), new Vector2(0.5f, 0.5f), new Vector2(x, -cy), new Vector2(thick, h), col);
    _cells.Add(b.gameObject);
  }

  void DrawSideCell(int r, int sideIdx, float x, float w, float y, float h, int slotNum, string who, string placeholderWho, bool hot, bool wide) {
    bool isBye = who == Tournament.Bye;
    bool isReal = !string.IsNullOrEmpty(who) && !isBye;
    var bg = hot ? NextUpBg : isReal ? EntryBg : ByeBg;

    // Subtle colored border for active agents
    if (isReal || hot) {
      var rimCol = hot ? BroadcastUi.Accent : ColorOf(who);
      rimCol.a = hot ? 0.95f : 0.55f;
      var border = BroadcastUi.Panel(_grid, $"Bdr_{r}_{x}_{sideIdx}", new Vector2(0.5f, 1f), new Vector2(0.5f, 0.5f),
          new Vector2(x, -y), new Vector2(w + 4f, h + 4f), rimCol);
      _cells.Add(border.gameObject);
    }

    var cell = BroadcastUi.Panel(_grid, $"Cell_{r}_{x}_{sideIdx}", new Vector2(0.5f, 1f), new Vector2(0.5f, 0.5f),
        new Vector2(x, -y), new Vector2(w, h), bg);
    _cells.Add(cell.gameObject);

    string voiceTarget = isReal ? who : placeholderWho;
    AttachVoiceButton(cell.gameObject, voiceTarget);

    string text;
    if (who == null) {
      text = "<color=#64748b>TBD</color>";
    } else if (isBye) {
      if (r == 0 && !string.IsNullOrEmpty(placeholderWho)) {
        int pElo = AgentElo.Rating(placeholderWho);
        text = wide
            ? $"<b>#{slotNum} BYE</b> · {ShortName(placeholderWho)}\n{pElo} ELO"
            : $"#{slotNum} BYE\n{ShortName(placeholderWho)}";
      } else {
        text = "<color=#64748b>BYE</color>";
      }
    } else {
      int elo = AgentElo.Rating(who);
      string prefix = r == 0 && wide ? $"#{slotNum} " : "";
      text = $"<b>{prefix}{BroadcastUi.Paint(ShortName(who), ColorOf(who))}</b>\n{elo} ELO";
    }

    var t = BroadcastUi.Label(cell.transform, "Name", new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), Vector2.zero,
        new Vector2(w - 8f, h - 4f), 22, TextAnchor.MiddleCenter, text);
    if (isBye) t.color = ByeTextCol;
  }

  void DrawCenterFinalist(string name, float y, float w, float h, string tag, string who, string note, bool hot) {
    var rimCol = hot ? BroadcastUi.Accent : BorderCol;
    var border = BroadcastUi.Panel(_grid, name + "_Bdr", new Vector2(0.5f, 1f), new Vector2(0.5f, 0.5f),
        new Vector2(0f, -y), new Vector2(w + 4f, h + 4f), rimCol);
    _cells.Add(border.gameObject);

    var cell = BroadcastUi.Panel(border.transform, name, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f),
        Vector2.zero, new Vector2(w, h), hot ? NextUpBg : EntryBg);
    AttachVoiceButton(cell.gameObject, who);

    bool isBye = who == Tournament.Bye;
    string body = who == null ? $"<color=#94a3b8>{tag}</color>\nTBD"
                : isBye ? $"<color=#94a3b8>{tag}</color>\nBYE"
                : $"<color=#94a3b8>{tag}</color>\n<b>{BroadcastUi.Paint(ShortName(who), ColorOf(who))}</b> · {AgentElo.Rating(who)}";
    BroadcastUi.Label(cell.transform, "Name", new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), Vector2.zero,
        new Vector2(w - 10f, h - 6f), 22, TextAnchor.MiddleCenter, body);
  }

  void DrawCenterChampion(float y, float w, float h, string who) {
    var border = BroadcastUi.Panel(_grid, "ChampionBorder", new Vector2(0.5f, 1f), new Vector2(0.5f, 0.5f),
        new Vector2(0f, -y), new Vector2(w + 8f, h + 8f), BroadcastUi.Accent);
    _cells.Add(border.gameObject);

    var cell = BroadcastUi.Panel(border.transform, "ChampionCell", new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f),
        Vector2.zero, new Vector2(w, h), !string.IsNullOrEmpty(who) ? ChampBg : new Color(0.10f, 0.12f, 0.18f, 1f));
    AttachVoiceButton(cell.gameObject, who);

    string body = string.IsNullOrEmpty(who)
        ? "<color=#f2c71a><b>★ TOURNAMENT WINNER ★</b></color>\n<color=#94a3b8>CROWNED IN MIDDLE</color>"
        : $"<color=#f2c71a><b>★ CHAMPION ★</b></color>\n<b>{BroadcastUi.Paint(ShortName(who), ColorOf(who))}</b>\n{AgentElo.Rating(who)} ELO";
    BroadcastUi.Label(cell.transform, "Name", new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), Vector2.zero,
        new Vector2(w - 12f, h - 8f), 24, TextAnchor.MiddleCenter, body);
  }

  static string ShortName(string who) => who == "Grandma" ? "G.ma" : who;

  void AttachVoiceButton(GameObject cellGo, string who) {
    if (string.IsNullOrEmpty(who) || who == Tournament.Bye) return;
    var img = cellGo.GetComponent<Image>(); if (img != null) img.raycastTarget = true;
    var btn = cellGo.AddComponent<Button>();
    btn.onClick.AddListener(() => {
      var emo = (AgentEmotion)(_voiceCycle % AgentSounds.Categories);
      int snd = (_voiceCycle % AgentSounds.SoundsPerCategory) + 1;
      int exp = ((_voiceCycle / 2) % AgentSounds.ExpressivenessLevels) + 1;
      _voiceCycle++;
      PlayAgentVoice(who, emo, exp, snd);
    });
  }

  void PlayAgentVoice(string who, AgentEmotion emo, int exp, int snd = 1) {
    if (_voice == null || BroadcastUi.Headless) return;
    var clip = AgentSounds.Clip(who, emo, snd, exp);
    if (clip != null) _voice.PlayOneShot(clip, 0.85f);
  }

  static Color ColorOf(string who) {
    if (who == "Matt") return RacerPalette.Get(RaceConfig.Dogs.Length, RaceConfig.MattColor);
    if (who == "Grandma") return RacerPalette.Get(RaceConfig.Dogs.Length + 1, RaceConfig.GrandmaColor);
    int k = Array.FindIndex(RaceConfig.Dogs, d => d.name == who);
    return k >= 0 ? RacerPalette.Get(k, RaceConfig.Dogs[k].color) : new Color(0.55f, 0.75f, 0.95f);
  }
}

}
