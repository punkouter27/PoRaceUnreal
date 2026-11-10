using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace PoRace {

/// <summary>Knockout tournament over a 16-slot bilateral bracket (8 players on the left side, 8 players on the right
/// side, single winner in the middle). Filled with the current players + BYE placeholders when fewer than 16 are
/// trained, randomly seeded into the Left 8 and Right 8 slots each tournament, and racing on a randomly chosen track
/// each match. In Tournament Mode (AutoPlay = true by default), the bracket plays on its own match-by-match until a
/// single champion is crowned in the middle, recording ELO for each agent via AgentElo. No policy changes.</summary>
public static class Tournament {
  public const int Slots = 16;
  public const string Bye = "";
  public static readonly string[] RoundNames = { "ROUND OF 16", "QUARTER-FINAL", "SEMI-FINAL", "FINAL" };
  static readonly System.Random _rng = new System.Random();

  /// <summary>Rounds[0] = the 16 slots (0..7 Left, 8..15 Right), Rounds[r] = the 16 >> r who reached round r,
  /// Rounds[3][0] = Left Finalist, Rounds[3][1] = Right Finalist, Rounds[4][0] = Champion in the middle.
  /// null = not decided yet, "" = BYE.</summary>
  public static string[][] Rounds { get; private set; }
  /// <summary>Result note beside each advanced entry ("1516 (+16)", "bye"), same shape as Rounds.</summary>
  public static string[][] Notes { get; private set; }
  public static int[] Seeds { get; private set; }   // seed of each slot (0 = BYE)
  public static bool Active => Rounds != null;
  public static bool Done => Active && Rounds[4][0] != null;
  public static string Champion => Done ? Rounds[4][0] : null;
  /// <summary>When true (default in tournament mode), the tournament plays on its own until there is a single winner.</summary>
  public static bool AutoPlay { get; set; } = true;

  /// <summary>Round name of the match being raced in the loaded scene (null when it is not a tournament match). Kept
  /// after the result is in so the results card can say it; cleared when the menu loads.</summary>
  public static string Label { get; private set; }
  public static bool IsFinal { get; private set; }
  /// <summary>True from a 1v1 bracket match's launch until its result is reported.</summary>
  public static bool InMatch { get; private set; }
  /// <summary>True during a 16-at-a-time mass race (all existing trained players on the grid at once).</summary>
  public static bool InMassRace { get; private set; }
  static int _round, _match;

  /// <summary>All existing trained characters in the app (Dog, Matt, Grandma once raceable, plus any future trained
  /// CreatureDefinition up to 16 players).</summary>
  public static List<string> Entrants() {
    var list = new List<string>();
    foreach (var d in RaceConfig.Dogs) if (!list.Contains(d.name)) list.Add(d.name);
    if (!list.Contains("Matt")) list.Add("Matt");
    var gm = Array.Find(CreatureRegistry.All(), c => c.displayName == "Grandma");
    if (gm != null && gm.raceable && !list.Contains("Grandma")) list.Add("Grandma");
    foreach (var c in CreatureRegistry.All()) {
      if (c == null || c.isPlaceholder || !c.raceable) continue;
      string n = c.displayName == "Go2" ? (RaceConfig.Dogs.Length > 0 ? RaceConfig.Dogs[0].name : "Dog") : c.displayName;
      if (!list.Contains(n)) list.Add(n);
    }
    return list;
  }

  /// <summary>Starts a new 16-player tournament: randomly shuffles entrants and places them across the 8 Left slots
  /// (0..7) and 8 Right slots (8..15), filling all remaining slots with BYE placeholders.</summary>
  public static void Begin(IList<string> entrants, bool autoPlay = true) {
    AutoPlay = autoPlay;
    Rounds = new string[5][]; Notes = new string[5][]; Seeds = new int[Slots];
    for (int r = 0; r < 5; r++) { Rounds[r] = new string[Slots >> r]; Notes[r] = new string[Slots >> r]; }
    for (int i = 0; i < Slots; i++) { Rounds[0][i] = Bye; Notes[0][i] = ""; Seeds[i] = 0; }

    // Randomly shuffle the entrants
    var pool = new List<string>(entrants);
    for (int i = pool.Count - 1; i > 0; i--) { int j = _rng.Next(i + 1); (pool[i], pool[j]) = (pool[j], pool[i]); }

    // Randomly shuffle the 8 Left slot indices (0..7) and 8 Right slot indices (8..15)
    int[] leftSlots = { 0, 1, 2, 3, 4, 5, 6, 7 };
    int[] rightSlots = { 8, 9, 10, 11, 12, 13, 14, 15 };
    for (int i = 7; i > 0; i--) {
      int jl = _rng.Next(i + 1); (leftSlots[i], leftSlots[jl]) = (leftSlots[jl], leftSlots[i]);
      int jr = _rng.Next(i + 1); (rightSlots[i], rightSlots[jr]) = (rightSlots[jr], rightSlots[i]);
    }

    // Deal shuffled entrants into random Left and Right slots (alternating sides so both wings have players)
    int li = 0, ri = 0;
    bool startRight = _rng.Next(2) == 1;
    for (int k = 0; k < Mathf.Min(pool.Count, Slots); k++) {
      bool useRight = ((k % 2 == 1) ^ startRight) && ri < 8 || li >= 8;
      int slot = useRight ? rightSlots[ri++] : leftSlots[li++];
      string who = pool[k];
      Rounds[0][slot] = who;
      Seeds[slot] = k + 1;
      Notes[0][slot] = $"{AgentElo.Rating(who)}";
    }

    Label = null; InMatch = false; InMassRace = false;
    Resolve();
    Debug.Log($"[Tournament] Randomly seeded {pool.Count} agents + {Slots - pool.Count} BYEs in {Slots} slots (8 Left, 8 Right, autoPlay={AutoPlay}): "
              + string.Join(", ", pool));
  }

  public static void End() { Rounds = null; Notes = null; Seeds = null; Label = null; InMatch = false; InMassRace = false; }

  /// <summary>The menu loaded (or a demo started): no match is being raced any more.</summary>
  public static void ClearLaunch() { Label = null; InMatch = false; InMassRace = false; }

  /// <summary>Every decided match with a BYE in it advances its racer (or a BYE, when both sides are empty).</summary>
  static void Resolve() {
    for (int r = 0; r < 4; r++)
      for (int m = 0; m < Rounds[r + 1].Length; m++) {
        if (Rounds[r + 1][m] != null) continue;
        string a = Rounds[r][2 * m], b = Rounds[r][2 * m + 1];
        if (a == null || b == null || (a != Bye && b != Bye)) continue;
        string adv = a == Bye ? b : a;
        Rounds[r + 1][m] = adv;
        Notes[r + 1][m] = adv == Bye ? "" : $"{AgentElo.Rating(adv)}";
      }
  }

  /// <summary>The next match to race: the earliest round, top first, with two racers and no winner yet.</summary>
  public static bool Next(out int round, out int match, out string a, out string b) {
    round = match = -1; a = b = null;
    if (!Active) return false;
    for (int r = 0; r < 4; r++)
      for (int m = 0; m < Rounds[r + 1].Length; m++) {
        if (Rounds[r + 1][m] != null) continue;
        string x = Rounds[r][2 * m], y = Rounds[r][2 * m + 1];
        if (x == null || y == null || x == Bye || y == Bye) continue;
        round = r; match = m; a = x; b = y; return true;
      }
    return false;
  }

  /// <summary>Loads the next 1v1 match in the 16-player bracket: places the two racers on the grid and picks a random eligible track.</summary>
  public static void LaunchNext() {
    if (!Next(out int r, out int m, out string a, out string b)) return;
    bool hasHuman = a == "Matt" || a == "Grandma" || b == "Matt" || b == "Grandma";
    var allMaps = MapRegistry.All();
    var eligible = hasHuman ? Array.FindAll(allMaps, x => x.terrain == "flat") : allMaps;
    if (eligible.Length == 0) eligible = allMaps;
    if (eligible.Length == 0) { Debug.LogError("[Tournament] no maps available"); return; }

    _round = r; _match = m; Label = $"1v1 {RoundNames[r]} ({a} vs {b})"; IsFinal = r == 3; InMatch = true; InMassRace = false;
    RaceConfig.dogMask = 0; RaceConfig.matt = false; RaceConfig.grandma = false;
    foreach (var who in new[] { a, b }) {
      if (who == "Matt") RaceConfig.matt = true;
      else if (who == "Grandma") RaceConfig.grandma = true;
      else { int k = Array.FindIndex(RaceConfig.Dogs, d => d.name == who); if (k >= 0) RaceConfig.dogMask |= 1 << k; }
    }
    RaceConfig.laps = 0; RaceConfig.seed = -1; RaceConfig.fromMenu = true; RaceConfig.autoplay = false;
    var map = eligible[_rng.Next(eligible.Length)];
    Debug.Log($"[Tournament] 1v1 {RoundNames[r]}: {a} ({AgentElo.Rating(a)} ELO) vs {b} ({AgentElo.Rating(b)} ELO) on random track {map.displayName}");
    SceneManager.LoadScene(map.sceneName);
  }

  /// <summary>Launches a 16-at-a-time mass race with ALL existing trained players on the starting grid simultaneously.</summary>
  public static void LaunchAllTrained(MapDefinition preferredMap = null, int laps = 0, int weatherCity = -1, string twitchChannel = "") {
    var entrants = Entrants();
    bool hasHuman = entrants.Contains("Matt") || entrants.Contains("Grandma");
    var allMaps = MapRegistry.All();
    var eligible = hasHuman ? Array.FindAll(allMaps, x => x.terrain == "flat") : allMaps;
    if (eligible.Length == 0) eligible = allMaps;
    if (eligible.Length == 0) { Debug.LogError("[Tournament] no maps available"); return; }

    MapDefinition map = preferredMap;
    if (map == null || (hasHuman && map.terrain != "flat")) {
      map = eligible[_rng.Next(eligible.Length)];
    }

    AutoPlay = false;
    InMatch = false;
    InMassRace = true;
    Label = $"16-AT-A-TIME RACE ({entrants.Count} TRAINED: {string.Join(", ", entrants)})";
    IsFinal = false;

    RaceConfig.dogMask = (1 << RaceConfig.Dogs.Length) - 1;
    RaceConfig.matt = entrants.Contains("Matt") && map.terrain == "flat";
    RaceConfig.grandma = entrants.Contains("Grandma") && map.terrain == "flat";
    RaceConfig.laps = map.closed ? Mathf.Max(1, laps) : 1;
    RaceConfig.seed = -1;
    RaceConfig.fromMenu = true;
    RaceConfig.autoplay = false;
    RaceConfig.weatherCity = weatherCity;
    RaceConfig.twitchChannel = twitchChannel ?? "";

    Debug.Log($"[Tournament] Launching 16-at-a-time race with all {entrants.Count} existing trained players ({string.Join(", ", entrants)}) on {map.displayName}");
    SceneManager.LoadScene(map.sceneName);
  }

  /// <summary>Records the 1v1 match being raced: updates ELO for both agents and advances the winner.</summary>
  public static void Report(string winner, string loser, string timeNote) {
    if (!InMatch || !Active) return;
    InMatch = false;
    bool isFinal = _round == 3;
    var (dWin, _) = AgentElo.RecordMatch(winner, loser, isFinal);
    int newElo = AgentElo.Rating(winner);
    string note = $"{newElo} ({AgentElo.FormatDelta(dWin)})";
    Rounds[_round + 1][_match] = winner;
    Notes[_round + 1][_match] = note;
    for (int r = 0; r <= _round; r++)
      for (int i = 0; i < Rounds[r].Length; i++)
        if (Rounds[r][i] == winner || Rounds[r][i] == loser)
          Notes[r][i] = $"{AgentElo.Rating(Rounds[r][i])}";
    Resolve();
    Debug.Log($"[Tournament] {RoundNames[_round]}: {winner} def. {loser} ({timeNote}) -> {note}{(Done ? " | CHAMPION " + Champion : "")}");
  }

  /// <summary>Records a 16-at-a-time all-trained mass race: updates pairwise ELO between the winner and all runners-up.</summary>
  public static void ReportMassRace(IList<string> finishOrder, string timeNote) {
    if (!InMassRace) return;
    InMassRace = false;
    if (finishOrder == null || finishOrder.Count < 2) return;
    string winner = finishOrder[0];
    int totalDelta = 0;
    for (int i = 1; i < finishOrder.Count; i++) {
      var (dWin, _) = AgentElo.RecordMatch(winner, finishOrder[i], false);
      totalDelta += dWin;
    }
    if (Active && Rounds != null) {
      for (int r = 0; r < Rounds.Length; r++)
        for (int i = 0; i < Rounds[r].Length; i++)
          if (!string.IsNullOrEmpty(Rounds[r][i]))
            Notes[r][i] = $"{AgentElo.Rating(Rounds[r][i])}";
    }
    Debug.Log($"[Tournament] 16-at-a-time Mass Race won by {winner} ({timeNote}) -> {AgentElo.Rating(winner)} ELO ({AgentElo.FormatDelta(totalDelta)})");
  }
}

/// <summary>In a tournament 1v1 match or 16-at-a-time mass race scene: reports the winner and runners-up when the race
/// ends, updates ELO, and announces the race mode on the broadcast ticker.</summary>
public class TournamentMatch : MonoBehaviour {
  MultiRaceOrchestrator _race;

  [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
  static void Boot() {
    SceneManager.sceneLoaded += (s, m) => {
      if (!Tournament.InMatch && !Tournament.InMassRace) return;
      var race = UnityEngine.Object.FindAnyObjectByType<MultiRaceOrchestrator>();
      if (race == null) return;
      var t = race.gameObject.AddComponent<TournamentMatch>(); t._race = race;
      race.PhaseChanged += p => { if (p == RacePhase.Finished) t.Report(); };   // before RaceTelemetry's card (it subscribes in Start)
    };
  }

  void Start() {
    string badge = Tournament.InMassRace ? "16P MASS RACE" : "1v1 BRACKET";
    BroadcastTicker.Post($"{BroadcastUi.Paint(badge, BroadcastUi.Accent)} {Tournament.Label}", 6f);
  }

  static string NormName(string n) => n == "Blue" && RaceConfig.Dogs.Length > 0 ? RaceConfig.Dogs[0].name : n;

  void Report() {
    if (Tournament.InMassRace) {
      var ordered = new List<Racer>(_race.Live);
      ordered.Sort((a, b) => {
        int pa = a.place > 0 ? a.place : 999;
        int pb = b.place > 0 ? b.place : 999;
        return pa != pb ? pa.CompareTo(pb) : b.distance.CompareTo(a.distance);
      });
      if (ordered.Count == 0) return;
      var names = new List<string>(ordered.Count);
      foreach (var r in ordered) names.Add(NormName(r.name));
      var w = ordered[0];
      string mNote = w.finishTime >= 0 ? w.finishTime.ToString("F2", CultureInfo.InvariantCulture) + "s" : $"{w.distance:F0}m";
      Tournament.ReportMassRace(names, mNote);
      return;
    }

    Racer win = null, lose = null;
    foreach (var r in _race.Live) if (r.place == 1) win = r;
    if (win == null) foreach (var r in _race.Live) if (win == null || r.distance > win.distance) win = r;
    if (win == null) return;
    foreach (var r in _race.Live) if (r != win) lose = r;
    string note = win.finishTime >= 0 ? win.finishTime.ToString("F2", CultureInfo.InvariantCulture) + "s" : $"{win.distance:F0}m";
    Tournament.Report(NormName(win.name), lose != null ? NormName(lose.name) : "", note);
  }
}

}
