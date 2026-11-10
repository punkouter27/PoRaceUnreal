using UnityEngine;

namespace PoRace {

/// <summary>
/// A racer body as data (PRD FR-01, tasks E.2). Assets live in Assets/Resources/Creatures so CreatureRegistry can
/// discover them at runtime. Only raceable entries may be put on a grid: a creature becomes raceable once its
/// locomotion policy has passed the graduation and Unity parity gates. Others are roster stubs (art + rig only)
/// or 16-player tournament placeholders (isPlaceholder = true, filled as BYE until trained).
/// Every character also carries a 100-slot soundBank (HAPPY, ANGRY, HURT, INSULT x 5 sounds x 5 expressiveness levels 1..5).
/// </summary>
[CreateAssetMenu(menuName = "PoRace/Creature Definition", fileName = "Creature")]
public class CreatureDefinition : ScriptableObject {
  public enum Body { Quadruped, Biped }

  public string displayName = "Racer";
  public Body body = Body.Quadruped;
  [Tooltip("Standing height (m).")] public float height = 0.4f;
  [Tooltip("True once the creature's policies have graduated and passed the Unity parity gate.")]
  public bool raceable = false;
  [Tooltip("True for untrained 16-player roster slots (filled as BYE in the tournament bracket until ready).")]
  public bool isPlaceholder = false;
  [Tooltip("What stands between this creature and the grid (shown while raceable is false).")]
  [TextArea] public string blockedBy = "";
  [Tooltip("Skinned visual (Humanoid avatar for bipeds). Null when the visual comes from the MuJoCo model itself.")]
  [OptionalRef] public GameObject visualPrefab;
  public Color color = Color.white;
  [Tooltip("Height (m) broadcast cameras aim at above the racer's base: a 1.89 m human needs a different frame than a 0.4 m dog.")]
  public float cameraHeight = 0.3f;
  [Tooltip("Character card: personality traits. They are learned, not scripted: each comes from the creature's own " +
           "command range, gait clock and style reward weights in its training env (training/<creature>/env.py).")]
  [TextArea] public string traits = "";
  [Tooltip("Fundamental voice pitch (Hz) for procedural vocal synthesis when WAV files are not yet present.")]
  public float voicePitch = 180f;
  [Tooltip("True for robotic/mecha characters (adds ring/FM servo-vocal modulation to procedural voices).")]
  public bool voiceRobotic = false;
  [Tooltip("100 vocal sound slots: HAPPY, ANGRY, HURT, INSULT x 5 sounds x 5 expressiveness levels (1=weakest..5=strongest).")]
  public AgentSoundSlot[] soundBank;

  public void EnsureSoundBank(string voiceKey = null) {
    string key = !string.IsNullOrEmpty(voiceKey) ? voiceKey : displayName == "Go2" ? "Blue" : displayName;
    if (Mathf.Approximately(voicePitch, 180f)) {
      if (displayName == "Go2" || displayName == "Dog" || displayName == "Blue") { voicePitch = 240f; voiceRobotic = true; }
      else if (displayName == "Matt") { voicePitch = 132f; voiceRobotic = false; }
      else if (displayName == "Grandma") { voicePitch = 212f; voiceRobotic = false; }
    }
    if (soundBank == null || soundBank.Length != AgentSounds.SoundsPerAgent)
      soundBank = AgentSounds.CreatePlaceholderBank(key);
  }
}

/// <summary>Runtime discovery of every creature asset under Resources/Creatures (PRD FR-03).</summary>
public static class CreatureRegistry {
  static CreatureDefinition[] _cached;

  public static CreatureDefinition[] All() {
    if (_cached != null && _cached.Length >= AgentSounds.MaxAgents && _cached[0] != null) return _cached;
    var loaded = Resources.LoadAll<CreatureDefinition>("Creatures");
    System.Array.Sort(loaded, (a, b) => string.CompareOrdinal(a.name, b.name));
    var list = new System.Collections.Generic.List<CreatureDefinition>(loaded);
    for (int i = list.Count + 1; i <= AgentSounds.MaxAgents; i++) {
      string id = $"Agent{i:00}";
      var p = ScriptableObject.CreateInstance<CreatureDefinition>();
      p.name = $"Creature{i:00}_{id}";
      p.displayName = id;
      p.body = (i % 3 == 0) ? CreatureDefinition.Body.Quadruped : CreatureDefinition.Body.Biped;
      p.height = p.body == CreatureDefinition.Body.Quadruped ? 0.42f : 1.75f;
      p.cameraHeight = p.body == CreatureDefinition.Body.Quadruped ? 0.30f : 1.10f;
      p.raceable = false;
      p.isPlaceholder = true;
      p.blockedBy = $"Placeholder slot #{i:00} — awaiting character rig & RL graduation (filled as BYE in 16-player tournament).";
      p.color = Color.HSVToRGB(((i * 0.61803398875f) % 1f), 0.65f, 0.90f);
      p.traits = $"Placeholder agent #{i:00} · procedural voice bank ready (HAPPY/ANGRY/HURT/INSULT × 5 × 5).";
      p.voicePitch = 115f + ((i * 23) % 150);
      p.voiceRobotic = (i % 3 == 0);
      list.Add(p);
    }
    foreach (var c in list) if (c != null) c.EnsureSoundBank();
    _cached = list.ToArray();
    return _cached;
  }

  public static CreatureDefinition[] ActiveRoster() => System.Array.FindAll(All(), c => !c.isPlaceholder);

  public static CreatureDefinition[] Raceable() => System.Array.FindAll(All(), c => c.raceable && !c.isPlaceholder);
}

}
