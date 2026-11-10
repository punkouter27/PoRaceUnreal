using System.Linq;
using PoRace;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>Editor-time authoring of the racer roster (tasks E.2), also headless:
///   Unity.exe -batchmode -quit -projectPath . -executeMethod CreatureBuilder.BuildCli
/// Go2: the raceable quadruped (its visual is the MuJoCo model). Matt: the photoscanned human, game asset from
/// tools/blender/matt_look.py (Assets/Art/Exports/GLB/Matt): matt.fbx imports as a Unity Humanoid with the "Breathe"
/// blend shape and a looping "Walk" clip, and gets
///   - body: URP Lit with albedo, normal, metallic/smoothness, occlusion, and a tiling knit detail normal masked to
///     the sweatshirt; a second material slot draws the transparent wear grime (opacity driven by MattLook), a third
///     a soft cool rim (PoRace/StrainRim, additive) that keeps his silhouette off dark tracks
///   - bib (roster colour, number) and the modelled phone
/// The prefab is visual only (no PhysX, no MuJoCo body): in a race MattSkin poses it from his MuJoCo bodies.
/// Matt is raceable once matt_loco.onnx exists (graduated and parity-gated, rl_optimization_log.md).</summary>
public static class CreatureBuilder {
  const string Exp = "Assets/Art/Exports/GLB/Matt/", Tex = Exp + "Textures/";
  const string Dir = "Assets/Resources/Creatures/";
  const string Prefab = "Assets/Art/Prefabs/Matt.prefab", PolicyPath = "Assets/Policies/matt_loco.onnx";
  // Grandma (tools/blender/grandma_rig.py): AccuRig character on the same 22-bone Mecanim rig as Matt.
  const string GExp = "Assets/Art/Exports/GLB/Grandma/", GTex = GExp + "Textures/", GPrefab = "Assets/Art/Prefabs/Grandma.prefab";
  const string GPolicyPath = "Assets/Policies/grandma_loco.onnx";

  [MenuItem("PoRace/Build Roster")]
  public static void Build() {
    ImportTextures();
    var avatar = ImportMatt(out var bones, out var clip);
    var prefab = MattPrefab();
    // Graduation (100-episode gate, >= 90 %) and the Unity parity gates decide "raceable"; m6 walks and never falls but
    // tracks commands at about half speed (MATT-GRADUATE 0/100, rl_optimization_log.md), so Matt races as a preview.
    const bool Graduated = false;
    bool raceable = Graduated && AssetDatabase.LoadAssetAtPath<Object>(PolicyPath) != null;

    Define("Creature01_Go2", d => {
      d.displayName = "Go2"; d.body = CreatureDefinition.Body.Quadruped; d.height = 0.4f; d.raceable = true; d.isPlaceholder = false;
      d.blockedBy = ""; d.visualPrefab = null; d.color = new Color(0.85f, 0.88f, 0.9f); d.cameraHeight = 0.3f;
      d.voicePitch = 285f; d.voiceRobotic = true; d.EnsureSoundBank("Blue");
    });
    Define("Creature02_Matt", d => {
      d.displayName = "Matt"; d.body = CreatureDefinition.Body.Biped; d.height = 1.89f; d.raceable = raceable; d.isPlaceholder = false;
      d.blockedBy = raceable ? "Flat tracks only (Planar Sprint, Flat Oval): the policy has not trained on banks or obstacles."
                             : "Preview: his policy (m6) walks and never falls but only reaches about half the commanded speed; graduation 0/100.";
      d.visualPrefab = prefab; d.color = new Color(1f, 0.62f, 0.18f); d.cameraHeight = 1.2f;
      d.voicePitch = 126f; d.voiceRobotic = false; d.EnsureSoundBank("Matt");
    });
    var gAvatar = ImportGrandma(out int gBones);
    var gPrefab = GrandmaPrefab();
    // Raceable once her own policy graduates (grandma/sim.py graduate + ladder) and passes the Unity parity gate.
    bool gRaceable = AssetDatabase.LoadAssetAtPath<Object>(GPolicyPath) != null;
    Define("Creature03_Grandma", d => {
      d.displayName = "Grandma"; d.body = CreatureDefinition.Body.Biped; d.height = 1.58f; d.raceable = gRaceable; d.isPlaceholder = false;
      d.blockedBy = gRaceable ? "Flat tracks only: her policy has not trained on banks or obstacles."
                              : "In training: her own policy (from scratch) has not graduated yet.";
      d.visualPrefab = gPrefab; d.color = RaceConfig.GrandmaColor; d.cameraHeight = 1.0f;
      d.traits = "Unhurried (to 1.3 m/s), short quick steps (1.05 Hz stride clock), careful low foot clearance, steady " +
                 "torso, saves her strength (low motor-heat budget). Learned from her card in training/grandma/env.py.";
      d.voicePitch = 218f; d.voiceRobotic = false; d.EnsureSoundBank("Grandma");
    });
    // 16-player roster placeholders (Creature04..Creature16): each has its own character stub and 100-slot sound bank;
    // filled as BYE in the 16-player tournament bracket until its body and policy are trained.
    for (int idx = 4; idx <= AgentSounds.MaxAgents; idx++) {
      string id = $"Agent{idx:D2}";
      var vp = AgentSounds.ProfileOf(id);
      bool robo = vp.robotic > 0.1f;
      Define($"Creature{idx:D2}_{id}", d => {
        d.displayName = id;
        d.body = robo && idx % 4 == 0 ? CreatureDefinition.Body.Quadruped : CreatureDefinition.Body.Biped;
        d.height = d.body == CreatureDefinition.Body.Quadruped ? 0.45f : 1.65f + 0.02f * (idx % 6);
        d.raceable = false;
        d.isPlaceholder = true;
        d.blockedBy = $"16-player tournament slot #{idx}: placeholder (assigned BYE until trained).";
        d.visualPrefab = null;
        d.color = Color.HSVToRGB(((idx * 0.13f) % 1f), 0.55f, 0.85f);
        d.cameraHeight = d.body == CreatureDefinition.Body.Quadruped ? 0.35f : 1.05f;
        d.traits = $"Placeholder character slot #{idx} ({(robo ? "robotic" : "humanoid")} voice f0={vp.f0:F0} Hz).";
        d.voicePitch = vp.f0;
        d.voiceRobotic = robo;
        d.EnsureSoundBank(id);
      });
    }
    WriteSoundPlaceholdersReadme();
    Debug.Log($"[CreatureBuilder] Grandma avatar valid={gAvatar && gAvatar.isValid} human={gAvatar && gAvatar.isHuman} mapped bones={gBones}, policy {(gRaceable ? "present" : "not yet")}");
    AssetDatabase.SaveAssets();

    var r = prefab.GetComponentsInChildren<SkinnedMeshRenderer>().OrderByDescending(s => s.sharedMesh.vertexCount).First();   // the body, not the bib
    int phys = prefab.GetComponentsInChildren<Collider>(true).Length + prefab.GetComponentsInChildren<Rigidbody>(true).Length;
    Debug.Log($"[CreatureBuilder] roster: {string.Join(", ", CreatureRegistry.All().Select(c => $"{c.displayName}{(c.raceable ? "" : " (stub)")}"))} | " +
              $"Matt avatar valid={avatar && avatar.isValid} human={avatar && avatar.isHuman} mapped bones={bones}, clip {(clip ? $"{clip.name} {clip.length:F2}s loop={clip.isLooping}" : "none")}, " +
              $"{r.sharedMesh.vertexCount} verts, {r.sharedMesh.blendShapeCount} blend shapes, {r.bones.Length} skin bones, {r.sharedMaterials.Length} materials, PhysX components={phys}");
  }

  public static void BuildCli() {
    Build();
    EditorApplication.Exit(0);
  }

  /// <summary>Check renders of the Matt prefab in a throwaway scene (-shotDir &lt;dir&gt;): rest pose, the Walk clip
  /// mid-stride (sampled in edit mode), and a stride driven through the Humanoid avatar (HumanPoseHandler muscles),
  /// which only moves the mesh if the bone mapping is right. Logs the world-space size of the skinned mesh.</summary>
  public static void PreviewCli() {
    var args = System.Environment.GetCommandLineArgs();
    int k = System.Array.IndexOf(args, "-shotDir");
    string dir = k >= 0 && k + 1 < args.Length ? args[k + 1] : "Logs";
    UnityEditor.SceneManagement.EditorSceneManager.NewScene(UnityEditor.SceneManagement.NewSceneSetup.EmptyScene);
    var go = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(Prefab));
    // 3:1 key / fill, cool rim from behind (the broadcast subject light, BroadcastLighting)
    var sun = new GameObject("Key").AddComponent<Light>(); sun.type = LightType.Directional; sun.intensity = 1.2f; sun.transform.rotation = Quaternion.Euler(40f, -30f, 0f);
    var fill = new GameObject("Fill").AddComponent<Light>(); fill.type = LightType.Directional; fill.intensity = 0.4f; fill.transform.rotation = Quaternion.Euler(20f, 150f, 0f);
    RenderSettings.ambientLight = new Color(0.35f, 0.36f, 0.4f);
    var cam = new GameObject("Cam").AddComponent<Camera>();
    cam.orthographic = true; cam.orthographicSize = 1.1f; cam.clearFlags = CameraClearFlags.SolidColor; cam.backgroundColor = new Color(0.22f, 0.24f, 0.28f);
    var rt = new RenderTexture(640, 640, 24); cam.targetTexture = rt;
    var r = go.GetComponentInChildren<SkinnedMeshRenderer>();
    var look = go.GetComponent<MattLook>();

    void Shot(string name, Vector3 from, float size = 1.1f, float h = 0.95f) {
      cam.orthographicSize = size;
      cam.transform.position = new Vector3(0f, h, 0f) + from * 4f; cam.transform.LookAt(new Vector3(0f, h, 0f));
      cam.Render();
      RenderTexture.active = rt;
      var t = new Texture2D(640, 640, TextureFormat.RGB24, false); t.ReadPixels(new Rect(0, 0, 640, 640), 0, 0); t.Apply();
      System.IO.File.WriteAllBytes(System.IO.Path.Combine(dir, $"unity_matt_{name}.png"), t.EncodeToPNG());
      RenderTexture.active = null;
    }
    // edit mode does not re-skin before a manual Render: show posed meshes baked into a plain renderer
    GameObject still = null;
    void Freeze(bool on) {
      if (still != null) Object.DestroyImmediate(still);
      r.enabled = !on; if (!on) return;
      var posed = new Mesh(); r.BakeMesh(posed);
      still = new GameObject("Posed"); still.transform.SetPositionAndRotation(r.transform.position, r.transform.rotation);
      still.AddComponent<MeshFilter>().sharedMesh = posed; still.AddComponent<MeshRenderer>().sharedMaterials = r.sharedMaterials;
    }

    var baked = new Mesh(); r.BakeMesh(baked);
    var m = r.transform.localToWorldMatrix; var b = new Bounds(m.MultiplyPoint3x4(baked.vertices[0]), Vector3.zero);
    foreach (var v in baked.vertices) b.Encapsulate(m.MultiplyPoint3x4(v));
    var anim = go.GetComponent<Animator>();
    var head = anim.GetBoneTransform(HumanBodyBones.Head);
    Debug.Log($"[CreatureBuilder] Matt world size {b.size.x:F2} x {b.size.y:F2} x {b.size.z:F2} m, feet y={b.min.y:F3}, head bone at y={head.position.y:F2}, " +
              $"faces {(head.forward.z > 0 ? "+Z" : "-Z")}");
    Shot("rest_front", Vector3.back);
    Shot("rest_side", Vector3.right);
    Shot("chest", Vector3.back, 0.35f, 1.3f);

    var clip = AssetDatabase.LoadAllAssetsAtPath(Exp + "matt.fbx").OfType<AnimationClip>().FirstOrDefault(c => !c.name.StartsWith("__preview"));
    if (clip != null) {
      AnimationMode.StartAnimationMode(); AnimationMode.BeginSampling();
      AnimationMode.SampleAnimationClip(go, clip, clip.length * 0.3f);
      AnimationMode.EndSampling();
      Freeze(true); Shot("walk_side", Vector3.right); Freeze(false);
      AnimationMode.StopAnimationMode();
    }

    var knee = anim.GetBoneTransform(HumanBodyBones.LeftLowerLeg); var arm = anim.GetBoneTransform(HumanBodyBones.RightUpperArm);
    var knee0 = knee.localRotation; var arm0 = arm.localRotation;
    var hp = new HumanPoseHandler(anim.avatar, go.transform);
    var pose = new HumanPose(); hp.GetHumanPose(ref pose);
    void Muscle(string n, float v) { int i = System.Array.IndexOf(HumanTrait.MuscleName, n); if (i >= 0) pose.muscles[i] = v; }
    Muscle("Left Upper Leg Front-Back", 0.6f); Muscle("Left Lower Leg Stretch", -0.6f);
    Muscle("Right Upper Leg Front-Back", -0.4f);
    Muscle("Left Arm Down-Up", -0.6f); Muscle("Right Arm Down-Up", -0.6f);
    Muscle("Left Arm Front-Back", -0.5f); Muscle("Right Arm Front-Back", 0.5f);
    Muscle("Left Forearm Stretch", 0.2f); Muscle("Right Forearm Stretch", 0.2f);
    hp.SetHumanPose(ref pose);
    Debug.Log($"[CreatureBuilder] muscle pose moved left knee {Quaternion.Angle(knee0, knee.localRotation):F0} deg, right upper arm {Quaternion.Angle(arm0, arm.localRotation):F0} deg");
    Freeze(true); Shot("stride_side", Vector3.right);
    // full wear: the grime overlay at opacity 1
    if (look != null && r.sharedMaterials.Length > 1) {
      var g = new Material(r.sharedMaterials[1]); var c = g.GetColor("_BaseColor"); c.a = 1f; g.SetColor("_BaseColor", c);
      var mats = still.GetComponent<MeshRenderer>().sharedMaterials; mats[1] = g; still.GetComponent<MeshRenderer>().sharedMaterials = mats;
      Shot("grime_front", Vector3.back);
    }
    EditorApplication.Exit(0);
  }

  static void ImportTextures() {
    void Set(string name, TextureImporterType type, bool srgb, int max = 2048, TextureWrapMode wrap = TextureWrapMode.Clamp) {
      var ti = (TextureImporter)AssetImporter.GetAtPath(Tex + name + ".png");
      ti.textureType = type; ti.sRGBTexture = srgb; ti.maxTextureSize = max; ti.wrapMode = wrap;
      if (type == TextureImporterType.Default) ti.alphaSource = TextureImporterAlphaSource.FromInput;
      ti.SaveAndReimport();
    }
    Set("matt_albedo", TextureImporterType.Default, true);
    Set("matt_normal", TextureImporterType.NormalMap, false);
    Set("matt_metal_smooth", TextureImporterType.Default, false);
    Set("matt_occlusion", TextureImporterType.Default, false);
    Set("matt_orm", TextureImporterType.Default, false);
    Set("matt_detail_mask", TextureImporterType.Default, false);
    Set("matt_grime", TextureImporterType.Default, true);
    Set("matt_knit_normal", TextureImporterType.NormalMap, false, 512, TextureWrapMode.Repeat);
    Set("matt_bib", TextureImporterType.Default, true, 512);
  }

  static Avatar ImportMatt(out int bones, out AnimationClip clip) {
    var mi = (ModelImporter)AssetImporter.GetAtPath(Exp + "matt.fbx");
    mi.bakeAxisConversion = true;               // Blender -Z forward / Y up export -> no -90 degree root rotation
    mi.animationType = ModelImporterAnimationType.Human;
    mi.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
    mi.materialImportMode = ModelImporterMaterialImportMode.None;
    mi.importBlendShapes = true;
    mi.importTangents = ModelImporterTangents.Import;
    mi.importAnimation = true;
    mi.SaveAndReimport();
    mi = (ModelImporter)AssetImporter.GetAtPath(Exp + "matt.fbx");
    var clips = mi.defaultClipAnimations;       // the Walk action: loop it, root motion from the Root bone travel
    foreach (var c in clips) { c.name = "Walk"; c.loopTime = true; c.loopPose = true; c.lockRootRotation = true; c.keepOriginalOrientation = true; c.keepOriginalPositionY = true; }
    mi.clipAnimations = clips;
    mi.SaveAndReimport();
    bones = mi.humanDescription.human?.Length ?? 0;   // auto-map: the rig uses Mecanim bone names
    clip = AssetDatabase.LoadAllAssetsAtPath(Exp + "matt.fbx").OfType<AnimationClip>().FirstOrDefault(c => !c.name.StartsWith("__preview"));
    return AssetDatabase.LoadAllAssetsAtPath(Exp + "matt.fbx").OfType<Avatar>().FirstOrDefault();
  }

  static Avatar ImportGrandma(out int bones) {
    bones = 0;
    foreach (var (name, type, srgb) in new[] { ("grandma_albedo", TextureImporterType.Default, true), ("grandma_normal", TextureImporterType.NormalMap, false) }) {
      var ti = (TextureImporter)AssetImporter.GetAtPath(GTex + name + ".png"); if (ti == null) continue;
      ti.textureType = type; ti.sRGBTexture = srgb; ti.maxTextureSize = 2048; ti.wrapMode = TextureWrapMode.Clamp; ti.SaveAndReimport();
    }
    var mi = (ModelImporter)AssetImporter.GetAtPath(GExp + "grandma.fbx");
    if (mi == null) { Debug.LogWarning("[CreatureBuilder] no grandma.fbx (run tools/blender/grandma_rig.py)"); return null; }
    mi.bakeAxisConversion = true; mi.animationType = ModelImporterAnimationType.Human; mi.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
    mi.materialImportMode = ModelImporterMaterialImportMode.None; mi.importBlendShapes = false; mi.importTangents = ModelImporterTangents.Import;
    mi.importAnimation = false;
    mi.SaveAndReimport();
    bones = mi.humanDescription.human?.Length ?? 0;
    return AssetDatabase.LoadAllAssetsAtPath(GExp + "grandma.fbx").OfType<Avatar>().FirstOrDefault();
  }

  static GameObject GrandmaPrefab() {
    var src = AssetDatabase.LoadAssetAtPath<GameObject>(GExp + "grandma.fbx"); if (src == null) return null;
    var go = (GameObject)PrefabUtility.InstantiatePrefab(src);
    go.name = "Grandma";
    var m = Lit("Grandma");
    m.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(GTex + "grandma_albedo.png")); m.SetColor("_BaseColor", Color.white);
    m.SetTexture("_BumpMap", AssetDatabase.LoadAssetAtPath<Texture2D>(GTex + "grandma_normal.png")); m.EnableKeyword("_NORMALMAP");
    m.SetFloat("_Smoothness", 0.25f); EditorUtility.SetDirty(m);
    SkinnedMeshRenderer body = null;
    foreach (var r in go.GetComponentsInChildren<Renderer>()) {
      r.shadowCastingMode = ShadowCastingMode.On;
      if (r is SkinnedMeshRenderer s) { body = s; s.sharedMaterials = new[] { m, Rim() }; s.updateWhenOffscreen = false; }
    }
    var anim = go.GetComponent<Animator>(); if (anim) anim.applyRootMotion = false;
    // effort tint, team rim and breathing as Matt; no grime slot (her UVs have no feet mask)
    var look = go.AddComponent<MattLook>(); look.body = body; look.grimeSlot = 99;
    var prefab = PrefabUtility.SaveAsPrefabAsset(go, GPrefab);
    Object.DestroyImmediate(go);
    return prefab;
  }

  static Material Lit(string name) {
    var path = $"Assets/Materials/{name}.mat";
    var m = AssetDatabase.LoadAssetAtPath<Material>(path);
    if (!m) { m = new Material(Shader.Find("Universal Render Pipeline/Lit")); AssetDatabase.CreateAsset(m, path); }
    return m;
  }

  static Material Body() {
    var m = Lit("Matt");
    m.SetTexture("_BaseMap", T("matt_albedo")); m.SetColor("_BaseColor", new Color(1.03f, 1.0f, 0.97f));   // a touch warmer than the robots
    m.SetTexture("_BumpMap", T("matt_normal")); m.EnableKeyword("_NORMALMAP");
    m.SetTexture("_MetallicGlossMap", T("matt_metal_smooth")); m.EnableKeyword("_METALLICSPECGLOSSMAP");
    m.SetFloat("_Smoothness", 0.45f);           // scale on the map's alpha (1 - roughness): ~5 % of its texels are 1.0, which at
                                                // scale 1 rendered as mirror patches (dark skin, a brown-orange halo from the ground)
    m.SetTexture("_OcclusionMap", T("matt_occlusion")); m.SetFloat("_OcclusionStrength", 1f); m.EnableKeyword("_OCCLUSIONMAP");
    m.SetTexture("_DetailMask", T("matt_detail_mask"));
    m.SetTexture("_DetailNormalMap", T("matt_knit_normal")); m.SetFloat("_DetailNormalMapScale", 0.6f);
    m.SetTextureScale("_DetailAlbedoMap", new Vector2(14f, 14f));   // URP Lit tiles both detail maps with this
    m.EnableKeyword("_DETAIL_MULX2");
    EditorUtility.SetDirty(m);
    return m;
  }

  /// <summary>Transparent wear overlay drawn as a second pass of the body mesh: dirt colour, alpha = feet/shin mask x
  /// _BaseColor.a (MattLook sets it from his accumulated contact wear).</summary>
  static Material Grime() {
    var m = Lit("MattGrime");
    m.SetTexture("_BaseMap", T("matt_grime")); m.SetColor("_BaseColor", new Color(1f, 1f, 1f, 0f));
    m.SetFloat("_Surface", 1f); m.SetFloat("_Blend", 0f); m.SetFloat("_Smoothness", 0.1f);
    m.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha); m.SetFloat("_DstBlend", (float)BlendMode.OneMinusSrcAlpha); m.SetFloat("_ZWrite", 0f);
    m.SetOverrideTag("RenderType", "Transparent"); m.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
    m.renderQueue = (int)RenderQueue.Transparent;
    EditorUtility.SetDirty(m);
    return m;
  }

  static Material Rim() {
    const string path = "Assets/Materials/MattRim.mat";
    var m = AssetDatabase.LoadAssetAtPath<Material>(path);
    if (!m) { m = new Material(Shader.Find("PoRace/StrainRim")); AssetDatabase.CreateAsset(m, path); }
    m.SetColor("_RimColor", new Color(0.35f, 0.42f, 0.55f)); m.SetFloat("_RimPower", 3.5f); m.SetFloat("_Fill", 0f);
    EditorUtility.SetDirty(m);
    return m;
  }

  static Material Flat(string name, Texture2D tex, Color color, float smooth) {
    var m = Lit(name);
    m.SetTexture("_BaseMap", tex); m.SetColor("_BaseColor", color); m.SetFloat("_Smoothness", smooth);
    EditorUtility.SetDirty(m);
    return m;
  }

  static GameObject MattPrefab() {
    if (!AssetDatabase.IsValidFolder("Assets/Art/Prefabs")) AssetDatabase.CreateFolder("Assets/Art", "Prefabs");
    var go = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(Exp + "matt.fbx"));
    go.name = "Matt";
    SkinnedMeshRenderer body = null;
    foreach (var r in go.GetComponentsInChildren<Renderer>()) {
      r.shadowCastingMode = ShadowCastingMode.On;
      if (r.name.Contains("Bib")) r.sharedMaterial = Flat("MattBib", T("matt_bib"), Color.white, 0.2f);
      else if (r.name.Contains("Phone")) r.sharedMaterial = Flat("MattPhone", null, new Color(0.03f, 0.03f, 0.035f), 0.75f);
      else if (r is SkinnedMeshRenderer s) { body = s; s.sharedMaterials = new[] { Body(), Grime(), Rim() }; }
      if (r is SkinnedMeshRenderer sk) sk.updateWhenOffscreen = false;
    }
    var anim = go.GetComponent<Animator>();
    if (anim) anim.applyRootMotion = false;
    var look = go.AddComponent<MattLook>(); look.body = body; look.grimeSlot = 1;
    var prefab = PrefabUtility.SaveAsPrefabAsset(go, Prefab);
    Object.DestroyImmediate(go);
    return prefab;
  }

  static void Define(string asset, System.Action<CreatureDefinition> fill) {
    if (!AssetDatabase.IsValidFolder("Assets/Resources/Creatures")) AssetDatabase.CreateFolder("Assets/Resources", "Creatures");
    var path = Dir + asset + ".asset";
    var d = AssetDatabase.LoadAssetAtPath<CreatureDefinition>(path);
    if (!d) { d = ScriptableObject.CreateInstance<CreatureDefinition>(); AssetDatabase.CreateAsset(d, path); }
    fill(d);
    EditorUtility.SetDirty(d);
  }

  static void WriteSoundPlaceholdersReadme() {
    if (!AssetDatabase.IsValidFolder("Assets/Resources/AgentSounds"))
      AssetDatabase.CreateFolder("Assets/Resources", "AgentSounds");
    const string path = "Assets/Resources/AgentSounds/README_PLACEHOLDERS.txt";
    var sb = new System.Text.StringBuilder();
    sb.AppendLine("# Agent Vocal Sound Placeholders (16 Characters x 4 Categories x 5 Sounds x 5 Expressiveness Levels)");
    sb.AppendLine("# Drop WAV files under Assets/Resources/AgentSounds/<Agent>/<CATEGORY>/<Agent>_<CATEGORY>_s<1..5>_e<1..5>.wav");
    sb.AppendLine("# Expressiveness: 1 = weakest .. 5 = strongest.");
    sb.AppendLine("# When a WAV does not exist yet, AgentSounds.Clip(...) synthesises procedurally advanced vocal audio.");
    sb.AppendLine();
    string[] agents = { "Blue", "Matt", "Grandma", "Agent04", "Agent05", "Agent06", "Agent07", "Agent08",
                        "Agent09", "Agent10", "Agent11", "Agent12", "Agent13", "Agent14", "Agent15", "Agent16" };
    foreach (var a in agents)
      foreach (var c in AgentSounds.CategoryNames)
        sb.AppendLine($"Assets/Resources/AgentSounds/{a}/{c}/{a}_{c}_s[1..5]_e[1..5].wav");
    System.IO.File.WriteAllText(path, sb.ToString());
  }

  static Texture2D T(string name) => AssetDatabase.LoadAssetAtPath<Texture2D>(Tex + name + ".png");
}
