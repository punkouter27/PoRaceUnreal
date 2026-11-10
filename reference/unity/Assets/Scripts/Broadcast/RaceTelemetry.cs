using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Mujoco;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace PoRace {

/// <summary>Feature 9, telemetry and post-race analytics. Every racer is logged at 10 Hz to JSONL (position, heading,
/// speed, command, joint effort, power, state, place) and summarised at the finish:
///   time, mean / top speed, cost of transport = energy / (m g d) with energy = integral of sum |tau * qdot|,
///   cadence (foot strikes per second), peak joint effort, falls, overtakes, un-sticks, respawns.
/// Files: &lt;persistentDataPath&gt;/telemetry/&lt;yyMMdd-HHmmss&gt;_&lt;map&gt;_s&lt;seed&gt;.jsonl + _summary.json, or -telemetryDir &lt;dir&gt;.
/// The summary rows also go to Azure Table Storage when a table SAS URL is given (-azureTableSas, env
/// PORACE_AZURE_TABLE_SAS, or PlayerPrefs PoRace.azureSas): https://&lt;acct&gt;.table.core.windows.net/&lt;table&gt;?&lt;sas&gt;.
/// A results card shows the winner and the summary when the race ends; its OK button returns to the main menu
/// (-autoOk &lt;s&gt; presses it s real seconds after it appears: full-loop captures).</summary>
public unsafe class RaceTelemetry : MonoBehaviour {
  public MultiRaceOrchestrator race;
  public RaceSensors sensors;
  public StrainMonitor strain;
  public ContactImpulse contacts;
  public float hz = 10f;

  [Serializable] public class Summary {
    public string racer, map, stamp; public int seed, place, falls, overtakes, unsticks, resets, steps, redlines;
    public float time, distance, meanSpeed, topSpeed, energy, costOfTransport, cadence, peakEffort, mass, wear;   // wear: N·s of body / cube / robot hits (ContactImpulse)
  }
  [Serializable] class SummaryFile { public List<Summary> racers = new List<Summary>(); }

  StreamWriter _w; string _dir, _base, _sas; float _next; int _step;
  readonly Dictionary<Racer, (float top, float startEnergy, int startStrikes)> _acc = new Dictionary<Racer, (float, float, int)>();
  readonly StringBuilder _sb = new StringBuilder();
  Image _card; Text _cardTitle; Text[] _cols; bool _written;
  // Results columns: header, width (canvas units), alignment. One Text per column, so the proportional font lines up.
  static readonly (string head, float w, TextAnchor align)[] Cols = {
    ("#", 30, TextAnchor.UpperLeft), ("racer", 110, TextAnchor.UpperLeft), ("time", 100, TextAnchor.UpperRight), ("avg", 58, TextAnchor.UpperRight),
    ("top", 58, TextAnchor.UpperRight), ("CoT", 58, TextAnchor.UpperRight), ("steps/s", 80, TextAnchor.UpperRight), ("peak", 62, TextAnchor.UpperRight),
    ("falls", 52, TextAnchor.UpperRight), ("passes", 64, TextAnchor.UpperRight) };
  const float CardW = 700f, RowH = 26f;
  public string LastSummaryPath { get; private set; }

  void Start() {
    if (!BroadcastUi.Wired(this, race, nameof(race))) return;
    if (sensors == null) sensors = FindAnyObjectByType<RaceSensors>();
    if (strain == null) strain = FindAnyObjectByType<StrainMonitor>();
    if (contacts == null) contacts = FindAnyObjectByType<ContactImpulse>();
    _dir = Path.Combine(Application.persistentDataPath, "telemetry");
    if (CliArgs.TryString("-telemetryDir", out var td)) _dir = td;
    if (CliArgs.TryString("-azureTableSas", out var sas)) _sas = sas;
    if (string.IsNullOrEmpty(_sas)) _sas = Environment.GetEnvironmentVariable("PORACE_AZURE_TABLE_SAS");
    if (string.IsNullOrEmpty(_sas)) _sas = PlayerPrefs.GetString("PoRace.azureSas", "");
    // The SAS URL is a write token: never send it anywhere but an Azure table endpoint over https.
    if (!string.IsNullOrEmpty(_sas) && !(Uri.TryCreate(_sas, UriKind.Absolute, out var u) && u.Scheme == Uri.UriSchemeHttps
                                         && u.Host.EndsWith(".table.core.windows.net", StringComparison.OrdinalIgnoreCase))) {
      Debug.LogWarning("[Telemetry] Azure upload off: the SAS URL must be https://<account>.table.core.windows.net/...");
      _sas = null;
    }
    race.PhaseChanged += p => { if (p == RacePhase.Racing) Open(); if (p == RacePhase.Finished) Close(true); };
    race.Restarted += () => { Close(false); if (_card != null) _card.gameObject.SetActive(false); };
    if (!BroadcastUi.Headless) BuildCard();
  }

  void OnDestroy() => Close(false);

  void Open() {
    Close(false);
    Directory.CreateDirectory(_dir);
    _base = Path.Combine(_dir, $"{DateTime.Now:yyMMdd-HHmmss}_{race.map.name}_s{race.Seed}");
    _w = new StreamWriter(_base + ".jsonl", false, new UTF8Encoding(false));
    _acc.Clear(); _written = false; _next = 0f;
    foreach (var r in race.Live) { var s = sensors?.Of(r); _acc[r] = (0f, s?.energy ?? 0f, s?.strikes ?? 0); }
  }

  void Close(bool summarize) {
    if (summarize && _w != null && !_written) WriteSummary();
    _w?.Dispose(); _w = null;
  }

  void FixedUpdate() {
    if (_w == null || race.Phase != RacePhase.Racing || sensors == null) return;
    foreach (var r in race.Live) { var s = sensors.Of(r); if (s != null && r.finishTime < 0) { var a = _acc[r]; a.top = Mathf.Max(a.top, s.speed); _acc[r] = a; } }
    if ((float)race.RaceTime < _next) return;
    _next = (float)race.RaceTime + 1f / hz;
    var d = MjScene.Instance.Data; var ci = CultureInfo.InvariantCulture;
    foreach (var r in race.Live) {
      var s = sensors.Of(r); if (s == null) continue; var B = r.Body; var c = B.Command;
      double yaw = RacerMath.Yaw(d->qpos, B.BaseQpos);
      _sb.Clear();
      _sb.AppendFormat(ci, "{{\"t\":{0:F2},\"racer\":\"{1}\",\"x\":{2:F3},\"y\":{3:F3},\"z\":{4:F3},\"yaw\":{5:F3},\"v\":{6:F3},\"cmd\":[{7:F2},{8:F2},{9:F2}],",
          race.RaceTime, r.name, d->qpos[B.BaseQpos], d->qpos[B.BaseQpos + 1], d->qpos[B.BaseQpos + 2], yaw, s.speed, c.x, c.y, c.z);
      _sb.AppendFormat(ci, "\"effort\":[{0}],\"power\":{1:F1},\"state\":\"{2}\",\"dist\":{3:F2},\"lat\":{4:F2},\"intent\":\"{5}\",\"mode\":\"{6}\"}}",
          string.Join(",", s.effort.Select(e => e.ToString("F2", ci))), s.power, r.state, r.distance, r.lateral, r.intent, B.ModeName);
      _w.WriteLine(_sb.ToString());
    }
  }

  public List<Summary> Summaries() {
    string stamp = Path.GetFileName(_base ?? DateTime.Now.ToString("yyMMdd-HHmmss"));
    return race.Live.Select(r => {
      var s = sensors?.Of(r); var a = _acc.TryGetValue(r, out var v) ? v : (0f, 0f, 0);
      float time = r.finishTime >= 0 ? (float)r.finishTime : (float)race.RaceTime, e = (s?.energy ?? 0f) - a.Item2, m = s?.mass ?? 15.2f;
      int strikes = (s?.strikes ?? 0) - a.Item3;
      return new Summary {
        racer = r.name, map = race.map.name, stamp = stamp, seed = race.Seed, place = r.place, falls = r.falls, overtakes = r.overtakes, unsticks = r.unsticks,
        resets = r.autoReset != null ? r.autoReset.Resets : 0, steps = strikes, redlines = strain != null ? strain.RedlineCount(r) : 0,
        time = time, distance = r.distance, meanSpeed = time > 0 ? r.distance / time : 0f, topSpeed = a.Item1, energy = e, mass = m,
        costOfTransport = r.distance > 1f ? e / (m * 9.81f * r.distance) : 0f, cadence = time > 0 ? strikes / time : 0f,
        peakEffort = strain != null ? strain.Peak(r) : 0f, wear = contacts != null ? contacts.Wear(r) : 0f };
    }).OrderBy(x => x.place > 0 ? x.place : 99).ToList();
  }

  void WriteSummary() {
    _written = true;
    var rows = Summaries();
    if (!Tournament.Active && race.Live.Count >= 2) {
      var ordered = rows.Select(x => race.Live.First(r => r.name == x.racer)).ToList();
      AgentElo.RecordRace(ordered);
    }
    LastSummaryPath = _base + "_summary.json";
    File.WriteAllText(LastSummaryPath, JsonUtility.ToJson(new SummaryFile { racers = rows }, true));
    foreach (var x in rows)
      Debug.Log(string.Format(CultureInfo.InvariantCulture, "[Telemetry] {0} P{1} {2:F2}s mean {3:F2} top {4:F2} m/s CoT {5:F2} cadence {6:F1}/s peak effort {7:F0}% falls {8} passes {9} redlines {10} wear {11:F1} N·s",
          x.racer, x.place, x.time, x.meanSpeed, x.topSpeed, x.costOfTransport, x.cadence, x.peakEffort * 100, x.falls, x.overtakes, x.redlines, x.wear));
    Debug.Log("[Telemetry] " + LastSummaryPath);
    if (!string.IsNullOrEmpty(_sas)) StartCoroutine(Upload(rows));
    if (_card != null) ShowCard(rows);
  }

  /// <summary>Results card (centre, sized to the grid when shown): title + winner, one Text per column, legend, OK.</summary>
  void BuildCard() {
    var mid = new Vector2(0.5f, 0.5f); var top = new Vector2(0.5f, 1f); var bottom = new Vector2(0.5f, 0f);
    _card = BroadcastUi.Panel(BroadcastUi.Root, "StatsCard", mid, mid, new Vector2(0, 20), new Vector2(CardW, 400), new Color(0.08f, 0.09f, 0.12f, 0.93f));
    _card.raycastTarget = true;   // taps on the card do not reach the HUD behind it
    _cardTitle = BroadcastUi.Label(_card.transform, "Title", top, top, new Vector2(0, -16), new Vector2(CardW - 30, 96), 22, TextAnchor.UpperCenter);
    _cols = new Text[Cols.Length]; float x = -0.5f * Cols.Sum(c => c.w);
    for (int i = 0; i < Cols.Length; i++) {
      _cols[i] = BroadcastUi.Label(_card.transform, "Col_" + Cols[i].head, top, new Vector2(0f, 1f), new Vector2(x, -122), new Vector2(Cols[i].w, 200), 19, Cols[i].align);
      x += Cols[i].w;
    }
    var legend = BroadcastUi.Label(_card.transform, "Legend", bottom, bottom, new Vector2(0, 92), new Vector2(CardW - 30, 44), 16, TextAnchor.LowerCenter,
        "speeds m/s · CoT = energy / (m g d) · peak = highest joint effort vs 24 N·m");
    legend.color = new Color(1f, 1f, 1f, 0.7f);
    BroadcastUi.Button(_card.transform, "BtnOk", "OK", bottom, bottom, new Vector2(0, 18), new Vector2(260, 64), new Color(0.15f, 0.55f, 0.25f, 1f), 30, Ok);
    _card.gameObject.SetActive(false);
  }

  /// <summary>Back to the main menu (ends the self-running app too).</summary>
  public void Ok() {
    RaceConfig.autoplay = false; Time.timeScale = 1f;
    var hud = FindAnyObjectByType<Hud>();
    if (hud != null) hud.OnMenu(); else if (Application.CanStreamedLevelBeLoaded("Menu")) UnityEngine.SceneManagement.SceneManager.LoadScene("Menu");
  }

  void ShowCard(List<Summary> rows) {
    var ci = CultureInfo.InvariantCulture;
    var win = rows.FirstOrDefault(q => q.place == 1); var winR = win != null ? race.Live.First(q => q.name == win.racer) : null;
    bool solo = race.Live.Count == 1;
    string champ = winR == null ? "no finishers" : solo ? $"{BroadcastUi.Paint(win.racer, winR.color)} finishes in {win.time.ToString("F2", ci)} s"
                                                    : $"WINNER  {BroadcastUi.Paint(win.racer, winR.color)}  {win.time.ToString("F2", ci)} s";
    if (Tournament.Label != null && winR != null)   // a tournament match: the round, and who goes through
      champ = Tournament.IsFinal ? $"CHAMPION  {BroadcastUi.Paint(win.racer, winR.color)} ({AgentElo.Rating(win.racer)} ELO)"
                                 : $"{BroadcastUi.Paint(win.racer, winR.color)} advances ({AgentElo.Rating(win.racer)} ELO)";
    _cardTitle.text = $"<size=34><b>{(Tournament.Label ?? (solo ? "TIME TRIAL" : "RESULTS"))}</b></size>   <size=18>{race.map.displayName} · seed {race.Seed}</size>\n<size=30><b>{champ}</b></size>";
    var col = new StringBuilder[Cols.Length];
    for (int i = 0; i < Cols.Length; i++) col[i] = new StringBuilder($"<size=16>{Cols[i].head}</size>\n");
    foreach (var x in rows) {
      var r = race.Live.First(q => q.name == x.racer); bool dnf = r.finishTime < 0;
      string[] cells = { x.place > 0 ? x.place.ToString() : "-", BroadcastUi.Paint(x.racer, r.color),
        dnf ? BroadcastUi.Paint($"DNF {x.distance:F0} m", new Color(1f, 0.55f, 0.45f)) : x.time.ToString("F2", ci) + "s",
        x.meanSpeed.ToString("F2", ci), x.topSpeed.ToString("F2", ci), x.costOfTransport.ToString("F2", ci), x.cadence.ToString("F1", ci),
        (x.peakEffort * 100).ToString("F0", ci) + "%", x.falls.ToString(), x.overtakes.ToString() };
      for (int i = 0; i < Cols.Length; i++) col[i].Append(cells[i]).Append('\n');
    }
    for (int i = 0; i < Cols.Length; i++) _cols[i].text = col[i].ToString();
    _card.rectTransform.sizeDelta = new Vector2(CardW, 122 + RowH * (rows.Count + 1) + 150);   // title, header + rows, legend + OK
    _card.gameObject.SetActive(true);
    if (CliArgs.TryFloat("-autoOk", out float okAfter)) StartCoroutine(PressOk(okAfter));
    else if (Tournament.Active && Tournament.AutoPlay) StartCoroutine(PressOk(3.5f));
  }

  IEnumerator PressOk(float s) { yield return new WaitForSecondsRealtime(s); Debug.Log("[Results] OK pressed (-autoOk)"); Ok(); }

  IEnumerator Upload(List<Summary> rows) {
    var ci = CultureInfo.InvariantCulture; int ok = 0;
    foreach (var x in rows) {
      string body = "{" + string.Join(",", new[] {
        $"\"PartitionKey\":\"{x.map}\"", $"\"RowKey\":\"{x.stamp}_{x.racer}\"", $"\"Seed\":{x.seed}", $"\"Place\":{x.place}",
        string.Format(ci, "\"Time\":{0:F3}", x.time), string.Format(ci, "\"MeanSpeed\":{0:F3}", x.meanSpeed), string.Format(ci, "\"TopSpeed\":{0:F3}", x.topSpeed),
        string.Format(ci, "\"CostOfTransport\":{0:F3}", x.costOfTransport), string.Format(ci, "\"Cadence\":{0:F2}", x.cadence),
        string.Format(ci, "\"PeakEffort\":{0:F3}", x.peakEffort), string.Format(ci, "\"Wear\":{0:F2}", x.wear), $"\"Falls\":{x.falls}", $"\"Overtakes\":{x.overtakes}", $"\"Racer\":\"{x.racer}\"" }) + "}";
      using (var req = new UnityWebRequest(_sas, "POST")) {
        req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(body)); req.downloadHandler = new DownloadHandlerBuffer();
        req.SetRequestHeader("Content-Type", "application/json"); req.SetRequestHeader("Accept", "application/json;odata=nometadata");
        req.SetRequestHeader("Prefer", "return-no-content"); req.SetRequestHeader("x-ms-version", "2019-02-02");
        req.timeout = 10;
        yield return req.SendWebRequest();
        if (req.result == UnityWebRequest.Result.Success) ok++; else Debug.LogWarning($"[Telemetry] Azure insert {x.racer}: {req.responseCode} {req.error}");
      }
    }
    Debug.Log($"[Telemetry] Azure Table: {ok}/{rows.Count} rows inserted");
  }
}

}
