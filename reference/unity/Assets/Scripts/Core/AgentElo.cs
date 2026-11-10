using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace PoRace {

/// <summary>Persistent ELO rating tracker for every agent in the 16-player roster.
/// Starts at 1500 ELO (K = 32), updates on head-to-head tournament matches and multi-racer finishes,
/// and persists to &lt;persistentDataPath&gt;/elo.json. Skipped during -raceTest so headless regression stays stateless.</summary>
public static class AgentElo {
  public const int DefaultElo = 1500;
  public const float KFactor = 32f;

  [Serializable]
  public class Entry {
    public string agent;
    public int elo = DefaultElo;
    public int peakElo = DefaultElo;
    public int lastDelta;
    public int wins, losses, matches, tournamentsWon;
  }

  [Serializable]
  class State {
    public List<Entry> entries = new List<Entry>();
  }

  static State _state;
  static string FilePath => Path.Combine(Application.persistentDataPath, "elo.json");

  static State Current {
    get {
      if (_state != null) return _state;
      try {
        if (File.Exists(FilePath)) _state = JsonUtility.FromJson<State>(File.ReadAllText(FilePath));
      } catch (Exception e) { Debug.LogWarning("[AgentElo] load failed: " + e.Message); }
      if (_state == null || _state.entries == null) _state = new State();
      return _state;
    }
  }

  public static Entry Of(string agent) {
    if (string.IsNullOrEmpty(agent) || agent == Tournament.Bye) return new Entry { agent = "BYE", elo = 0 };
    var s = Current;
    var e = s.entries.Find(x => x.agent == agent);
    if (e == null) {
      e = new Entry { agent = agent, elo = DefaultElo, peakElo = DefaultElo };
      s.entries.Add(e);
    }
    return e;
  }

  public static int Rating(string agent) => string.IsNullOrEmpty(agent) || agent == Tournament.Bye ? 0 : Of(agent).elo;

  public static int LastDelta(string agent) => string.IsNullOrEmpty(agent) || agent == Tournament.Bye ? 0 : Of(agent).lastDelta;

  public static string FormatDelta(int delta) => delta > 0 ? $"+{delta}" : delta < 0 ? delta.ToString() : "±0";

  /// <summary>Updates ELO for a 1v1 match (winner vs loser). Returns (winnerDelta, loserDelta).</summary>
  public static (int dWin, int dLose) RecordMatch(string winner, string loser, bool tournamentFinal = false) {
    if (string.IsNullOrEmpty(winner) || string.IsNullOrEmpty(loser) || winner == Tournament.Bye || loser == Tournament.Bye || winner == loser)
      return (0, 0);
    var w = Of(winner);
    var l = Of(loser);
    float expectedW = 1f / (1f + Mathf.Pow(10f, (l.elo - w.elo) / 400f));
    int delta = Mathf.Max(1, Mathf.RoundToInt(KFactor * (1f - expectedW)));
    w.elo += delta;
    w.peakElo = Mathf.Max(w.peakElo, w.elo);
    w.lastDelta = delta;
    w.wins++;
    w.matches++;
    if (tournamentFinal) w.tournamentsWon++;

    l.elo = Mathf.Max(100, l.elo - delta);
    l.lastDelta = -delta;
    l.losses++;
    l.matches++;

    if (!CliArgs.RaceTest) Save();
    Debug.Log($"[ELO] {winner} {w.elo} ({FormatDelta(delta)}) def. {loser} {l.elo} ({FormatDelta(-delta)}){(tournamentFinal ? " [TOURNAMENT CHAMPION]" : "")}");
    return (delta, -delta);
  }

  /// <summary>Records pairwise ELO changes for a non-tournament race with 2+ racers.</summary>
  public static void RecordRace(IList<Racer> standings) {
    if (CliArgs.RaceTest || standings == null || standings.Count < 2) return;
    var deltas = new Dictionary<string, int>();
    for (int i = 0; i < standings.Count; i++) deltas[standings[i].name] = 0;
    float scale = 1f / Mathf.Max(1, standings.Count - 1);
    for (int i = 0; i < standings.Count; i++)
      for (int j = i + 1; j < standings.Count; j++) {
        var wi = Of(standings[i].name);
        var lj = Of(standings[j].name);
        float exp = 1f / (1f + Mathf.Pow(10f, (lj.elo - wi.elo) / 400f));
        int d = Mathf.Max(1, Mathf.RoundToInt(KFactor * scale * (1f - exp)));
        deltas[wi.agent] += d;
        deltas[lj.agent] -= d;
      }
    for (int i = 0; i < standings.Count; i++) {
      var e = Of(standings[i].name);
      int d = deltas[e.agent];
      e.elo = Mathf.Max(100, e.elo + d);
      e.peakElo = Mathf.Max(e.peakElo, e.elo);
      e.lastDelta = d;
      e.matches++;
      if (i == 0) e.wins++; else e.losses++;
    }
    Save();
  }

  public static void Save() {
    if (_state == null) return;
    try { File.WriteAllText(FilePath, JsonUtility.ToJson(_state, true)); }
    catch (Exception e) { Debug.LogWarning("[AgentElo] save failed: " + e.Message); }
  }
}

}
