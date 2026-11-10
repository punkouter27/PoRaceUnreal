using System.Linq;
using Mujoco;
using PoRace;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>Editor-time authoring of the human racers (tasks E.4: Matt; proposals r3: Grandma), also headless:
///   Unity.exe -batchmode -quit -projectPath . -executeMethod MattBuilder.BuildCli
/// For each human whose Unity model exists (training/matt/model_info.py [--creature grandma]):
/// - Assets/Scenes/&lt;Name&gt;Testbed.unity: the human alone on the trainer floor (&lt;name&gt;_testbed.xml through the MuJoCo
///   importer) with MattController, ParityRecorder and ReplayHarness: zero-brain, replay and closed-loop parity gates.
/// - Flat race scenes (Track01x4, Track02): the body (&lt;name&gt;_unity.xml, robot only; Grandma's names carry gm_) imported
///   into the race's single MuJoCo model next to the dogs, its MattController (human = which) + AutoReset, the skinned
///   visual driven by MattSkin, and a Racer entry. The orchestrator puts a human on the grid only when picked
///   (RaceConfig.matt / -matt, RaceConfig.grandma / -grandma). Rerunnable: that human's previous racer is removed first.
/// The MuJoCo primitives stay invisible; the skinned character is what the camera sees. Each human has its own policy.</summary>
public static class MattBuilder {
  static readonly string[] RaceScenes = { "Assets/Scenes/Track01x4.unity", "Assets/Scenes/Track02.unity" };

  sealed class H {
    public Human human; public string name, lower, policy, prefab; public Color color; public float cruise;
    public string UnityXml => $"Assets/MuJoCo/{lower}/{lower}_unity.xml";
    public string TestbedXml => $"Assets/MuJoCo/{lower}/{lower}_testbed.xml";
    public Unity.InferenceEngine.ModelAsset Policy => AssetDatabase.LoadAssetAtPath<Unity.InferenceEngine.ModelAsset>(policy);
    public bool Present => System.IO.File.Exists(UnityXml) && System.IO.File.Exists(TestbedXml);
  }

  static readonly H[] Humans = {
    new H { human = Human.Matt, name = "Matt", lower = "matt", policy = "Assets/Policies/matt_loco.onnx", prefab = "Assets/Art/Prefabs/Matt.prefab",
            color = new Color(1f, 0.62f, 0.18f), cruise = 1.5f },   // readable on the dark standings panel
    // Grandma cruises inside her graduated race range (0.6-1.2 m/s, grandma/sim.py); -handicap evens the finish
    new H { human = Human.Grandma, name = "Grandma", lower = "grandma", policy = "Assets/Policies/grandma_loco.onnx", prefab = "Assets/Art/Prefabs/Grandma.prefab",
            color = RaceConfig.GrandmaColor, cruise = 1.1f },
  };

  [MenuItem("PoRace/Build Human Testbeds")]
  public static void BuildTestbeds() { foreach (var h in Humans) if (h.Present) BuildTestbed(h); }

  static void BuildTestbed(H h) {
    var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
    var root = new MjImporterWithAssets().ImportFile(System.IO.Path.GetFullPath(h.TestbedXml));
    root.name = h.lower + "_scene";
    var gs = Object.FindFirstObjectByType<MjGlobalSettings>();
    gs.UseRawGameObjectNames = true; EditorUtility.SetDirty(gs);

    var rig = new GameObject(h.name + "Rig");
    var ctrl = rig.AddComponent<MattController>(); ctrl.human = h.human; ctrl.alone = true; ctrl.mode = MattController.Mode.HoldPose; ctrl.locomotionModel = h.Policy;
    ctrl.spawnMj = new Vector3(0f, 0f, ctrl.Spec.HomeHeight);
    var rec = rig.AddComponent<ParityRecorder>(); rec.controller = ctrl; rec.seconds = 1f; rec.fileName = $"unity_{h.lower}_zero_brain.json"; rec.quitWhenDone = true;
    var rep = rig.AddComponent<ReplayHarness>(); rep.model = h.Policy; rep.obsDim = ctrl.Spec.ObsDim; rep.actDim = ctrl.Spec.Nu;
    AddSkin(h, rig, ctrl);

    var cam = new GameObject("Main Camera"); cam.tag = "MainCamera"; cam.AddComponent<Camera>();
    cam.transform.position = new Vector3(3.2f, 1.6f, -3.2f); cam.transform.LookAt(new Vector3(0f, 0.8f, 0f));
    var light = new GameObject("Directional Light"); var l = light.AddComponent<Light>(); l.type = LightType.Directional;
    light.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
    EditorSceneManager.SaveScene(scene, $"Assets/Scenes/{h.name}Testbed.unity");
    Debug.Log($"[MattBuilder] {h.name}Testbed.unity: {Census(root)}; policy {(h.Policy != null ? "set" : "none yet")}");
  }

  [MenuItem("PoRace/Add Humans To Flat Tracks")]
  public static void AddToRaces() {
    foreach (var path in RaceScenes) {
      var scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
      var race = Object.FindFirstObjectByType<MultiRaceOrchestrator>(FindObjectsInactive.Include);
      foreach (var h in Humans) {
        if (!h.Present) continue;
        foreach (var old in new[] { h.lower + "_racer", h.name + "Racer", h.name + "Visual" }) { var g = GameObject.Find(old); if (g != null) Object.DestroyImmediate(g); }
        race.racers.RemoveAll(r => (r.matt != null && r.matt.human == h.human) || (r.controller == null && r.matt == null && r.name == h.name));

        var root = new MjImporterWithAssets().ImportFile(System.IO.Path.GetFullPath(h.UnityXml));
        root.name = h.lower + "_racer";
        foreach (var mr in root.GetComponentsInChildren<MeshRenderer>(true)) mr.enabled = false;   // collision primitives: physics only

        var go = new GameObject(h.name + "Racer");
        var ctrl = go.AddComponent<MattController>(); ctrl.human = h.human; ctrl.locomotionModel = h.Policy;
        ctrl.spawnMj = new Vector3(0f, 0f, ctrl.Spec.HomeHeight);
        ctrl.mode = h.Policy != null ? MattController.Mode.Locomotion : MattController.Mode.HoldPose;
        var dogReset = race.racers.Select(r => r.autoReset).FirstOrDefault(a => a != null && a.matt == null);
        var ar = go.AddComponent<AutoReset>(); ar.matt = ctrl;
        ar.fallenSeconds = 1.5f;   // no getup policy: a fall goes straight back to the last checkpoint
        if (dogReset != null) { ar.stallSeconds = dogReset.stallSeconds; ar.stallSpeed = dogReset.stallSpeed; ar.arenaRadius = dogReset.arenaRadius; }
        AddSkin(h, go, ctrl);
        race.racers.Add(new Racer { name = h.name, matt = ctrl, autoReset = ar, mjRoot = root, cruiseSpeed = h.cruise, color = h.color });
        Debug.Log($"[MattBuilder] {path}: {h.name} {Census(root)}; policy {(h.Policy != null ? "set" : "none yet (HoldPose)")}");
      }
      EditorUtility.SetDirty(race);
      int phys = Object.FindObjectsByType<Rigidbody>(FindObjectsInactive.Include, FindObjectsSortMode.None).Length +
                 Object.FindObjectsByType<Collider>(FindObjectsInactive.Include, FindObjectsSortMode.None).Length;
      EditorSceneManager.SaveScene(scene);
      Debug.Log($"[MattBuilder] {path}: racers {race.racers.Count} ({string.Join(", ", race.racers.Select(r => r.name))}); PhysX components={phys}");
    }
  }

  public static void BuildCli() {
    BuildTestbeds();
    AddToRaces();
    EditorApplication.Exit(0);
  }

  /// <summary>The skinned character as a separate visual root, posed every frame by MattSkin from the MuJoCo bodies.</summary>
  static void AddSkin(H h, GameObject owner, MattController ctrl) {
    var asset = AssetDatabase.LoadAssetAtPath<GameObject>(h.prefab);
    if (asset == null) { Debug.LogWarning($"[MattBuilder] no {h.prefab} (run CreatureBuilder.BuildCli): {h.name} races as invisible primitives"); return; }
    var vis = (GameObject)PrefabUtility.InstantiatePrefab(asset);
    vis.name = h.name + "Visual";
    var skin = owner.AddComponent<MattSkin>(); skin.visual = vis.transform; skin.controller = ctrl;
    var look = vis.GetComponent<MattLook>(); if (look != null) look.controller = ctrl;   // wear and effort of this racer
  }

  static string Census(GameObject root) =>
    $"MjBody={root.GetComponentsInChildren<MjBody>(true).Length} MjActuator={Object.FindObjectsByType<MjActuator>(FindObjectsInactive.Include, FindObjectsSortMode.None).Length} " +
    $"MjExclude={root.GetComponentsInChildren<MjExclude>(true).Length} MjGeom={root.GetComponentsInChildren<MjGeom>(true).Length}";
}
