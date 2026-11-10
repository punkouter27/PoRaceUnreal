using System.Linq;
using PoRace;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>Roster trim (owner's call, 2026-11-09): one dog only. Every race scene keeps its first dog (Blue: the
/// unprefixed Go2 with the pooled cubes) and loses the in-editor clones (Red / Green / Gold, MuJoCo prefixes r1_..r3_):
/// their controller objects, their MuJoCo subtrees and their Racer entries. The humans (Matt, Grandma) are untouched.
///   Unity.exe -batchmode -nographics -quit -projectPath . -executeMethod RosterBuilder.KeepOneDogCli</summary>
public static class RosterBuilder {
  [MenuItem("PoRace/Keep One Dog")]
  public static void KeepOneDog() {
    foreach (var path in BroadcastBuilder.RaceScenes) {
      if (!System.IO.File.Exists(path)) continue;
      var scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
      var race = Object.FindFirstObjectByType<MultiRaceOrchestrator>(FindObjectsInactive.Include);
      if (race == null) continue;
      var clones = race.racers.Where(r => r.matt == null && r.controller != null && r.controller.prefix != "").ToList();
      foreach (var r in clones) {
        if (r.mjRoot != null) Object.DestroyImmediate(r.mjRoot);
        var go = r.controller.gameObject;
        if (r.autoReset != null && r.autoReset.gameObject != go) Object.DestroyImmediate(r.autoReset.gameObject);
        Object.DestroyImmediate(go);
      }
      race.racers.RemoveAll(r => clones.Contains(r));
      // anything else still carrying a clone's MuJoCo prefix (e.g. a root the Racer entry didn't reference)
      foreach (var t in Object.FindObjectsByType<Transform>(FindObjectsInactive.Include, FindObjectsSortMode.None))
        if (t != null && t.parent == null && (t.name.StartsWith("r1_") || t.name.StartsWith("r2_") || t.name.StartsWith("r3_"))) Object.DestroyImmediate(t.gameObject);
      EditorUtility.SetDirty(race);
      EditorSceneManager.SaveScene(scene);
      int dogs = Object.FindObjectsByType<Go2Controller>(FindObjectsInactive.Include, FindObjectsSortMode.None).Length;
      Debug.Log($"[RosterBuilder] {path}: removed {clones.Count} dog(s) ({string.Join(", ", clones.Select(c => c.name))}); " +
                $"racers now {string.Join(", ", race.racers.Select(r => r.name))}; Go2Controllers {dogs}");
    }
  }

  public static void KeepOneDogCli() { KeepOneDog(); MenuBuilder.Build(); EditorApplication.Exit(0); }
}
