using System;
using System.Collections.Generic;
using UnityEngine;

namespace PoRace {

public enum AgentEmotion { Happy = 0, Angry = 1, Hurt = 2, Insult = 3 }

/// <summary>One slot in a character's 100-sound bank (4 emotions x 5 sounds x 5 expressiveness levels, 1=weakest..5=strongest).
/// If wavClip is null and no WAV exists at Resources/&lt;wavPlaceholderPath&gt;, AgentSounds synthesises a procedurally
/// advanced vocal clip for that character, emotion, variant and expressiveness level.</summary>
[Serializable]
public struct AgentSoundSlot {
  public string label;
  public AgentEmotion category;
  [Range(1, 5)] public int soundIndex;
  [Range(1, 5)] public int expressiveness;
  public string wavPlaceholderPath;
  [OptionalRef] public AudioClip wavClip;
}

/// <summary>Per-character vocal sound bank and procedural voice synthesiser.
/// Every character in the 16-agent roster has:
///   - 4 emotion categories: HAPPY, ANGRY, HURT, INSULT
///   - 5 distinct sounds per category (soundIndex 1..5)
///   - 5 levels of expressiveness per sound (1 = weakest .. 5 = strongest)
/// Total = 100 sounds per character (1,600 across the 16 character slots).
/// Resolution order:
///   1. Assigned AudioClip on the character's CreatureDefinition.soundBank
///   2. WAV asset at Resources/AgentSounds/&lt;Agent&gt;/&lt;CATEGORY&gt;/&lt;Agent&gt;_&lt;CATEGORY&gt;_s&lt;1..5&gt;_e&lt;1..5&gt;
///   3. Procedurally advanced synthesis: Rosenberg glottal pulse + subharmonic growl + consonant aspiration burst
///      passed through 3 time-varying state-variable vowel formant resonators (F1, F2, F3), optional robotic ring/FM
///      modulation for robot bodies, and nonlinear vocal-effort waveshaping scaled by expressiveness 1..5.</summary>
public static class AgentSounds {
  public const int Categories = 4, SoundsPerCategory = 5, ExpressivenessLevels = 5;
  public const int SoundsPerAgent = Categories * SoundsPerCategory * ExpressivenessLevels;
  public const int MaxAgents = 16;
  public static readonly string[] CategoryNames = { "HAPPY", "ANGRY", "HURT", "INSULT" };
  const int Rate = 44100;

  public struct VoiceProfile {
    public string id;
    public float f0, f1, f2, f3;
    public float robotic, ringHz, vibratoHz;
    public int seed;
  }

  static readonly Dictionary<string, AudioClip> _cache = new Dictionary<string, AudioClip>();
  static readonly Dictionary<string, CreatureDefinition> _defs = new Dictionary<string, CreatureDefinition>();

  public static int SlotIndex(AgentEmotion cat, int soundIndex, int expressiveness) {
    int c = Mathf.Clamp((int)cat, 0, Categories - 1);
    int s = Mathf.Clamp(soundIndex, 1, SoundsPerCategory) - 1;
    int e = Mathf.Clamp(expressiveness, 1, ExpressivenessLevels) - 1;
    return (c * SoundsPerCategory + s) * ExpressivenessLevels + e;
  }

  public static string PlaceholderPath(string agent, AgentEmotion cat, int soundIndex, int expressiveness) {
    string clean = string.IsNullOrEmpty(agent) ? "Agent" : agent.Replace(" ", "");
    string c = CategoryNames[Mathf.Clamp((int)cat, 0, Categories - 1)];
    int s = Mathf.Clamp(soundIndex, 1, SoundsPerCategory);
    int e = Mathf.Clamp(expressiveness, 1, ExpressivenessLevels);
    return $"AgentSounds/{clean}/{c}/{clean}_{c}_s{s}_e{e}";
  }

  public static AgentSoundSlot[] CreatePlaceholderBank(string agent) {
    var bank = new AgentSoundSlot[SoundsPerAgent];
    int k = 0;
    for (int c = 0; c < Categories; c++) {
      var cat = (AgentEmotion)c;
      for (int s = 1; s <= SoundsPerCategory; s++)
        for (int e = 1; e <= ExpressivenessLevels; e++) {
          string tag = e == 1 ? "weakest" : e == 5 ? "strongest" : "lv" + e;
          bank[k++] = new AgentSoundSlot {
            label = $"{CategoryNames[c]}_s{s}_e{e} ({tag})",
            category = cat,
            soundIndex = s,
            expressiveness = e,
            wavPlaceholderPath = PlaceholderPath(agent, cat, s, e),
            wavClip = null
          };
        }
    }
    return bank;
  }

  /// <summary>Distinct vocal tract &amp; pitch profile for each of the 16 character slots.</summary>
  public static VoiceProfile ProfileOf(string agent) {
    if (string.IsNullOrEmpty(agent)) agent = "Blue";
    switch (agent) {
      case "Blue":
      case "Go2":
        return new VoiceProfile { id = "Blue", f0 = 285f, f1 = 720f, f2 = 1860f, f3 = 2920f, robotic = 0.72f, ringHz = 56f, vibratoHz = 8.5f, seed = 101 };
      case "Matt":
        return new VoiceProfile { id = "Matt", f0 = 126f, f1 = 510f, f2 = 1360f, f3 = 2420f, robotic = 0f, ringHz = 0f, vibratoHz = 5.2f, seed = 202 };
      case "Grandma":
        return new VoiceProfile { id = "Grandma", f0 = 218f, f1 = 650f, f2 = 1740f, f3 = 2780f, robotic = 0f, ringHz = 0f, vibratoHz = 6.9f, seed = 303 };
      default:
        int idx = 4;
        if (agent.Length >= 2 && int.TryParse(agent.Substring(agent.Length - 2), out int n)) idx = Mathf.Clamp(n, 1, MaxAgents);
        else idx = (Mathf.Abs(agent.GetHashCode()) % 13) + 4;
        bool robo = idx % 2 == 0;
        float f0 = robo ? 210f + 18f * (idx % 7) : 115f + 16f * (idx % 8);
        return new VoiceProfile {
          id = agent, f0 = f0,
          f1 = 480f + 25f * (idx % 6), f2 = 1320f + 75f * (idx % 7), f3 = 2380f + 65f * (idx % 6),
          robotic = robo ? 0.65f : 0f, ringHz = robo ? 42f + 5f * idx : 0f,
          vibratoHz = 5f + 0.35f * (idx % 6), seed = idx * 107
        };
    }
  }

  /// <summary>Returns the WAV AudioClip if one exists, otherwise synthesises and caches the procedural clip.</summary>
  public static AudioClip Clip(string agent, AgentEmotion emotion, int soundIndex, int expressiveness) {
    if (string.IsNullOrEmpty(agent) || agent == Tournament.Bye) agent = "Blue";
    int s = Mathf.Clamp(soundIndex, 1, SoundsPerCategory);
    int e = Mathf.Clamp(expressiveness, 1, ExpressivenessLevels);
    string resPath = PlaceholderPath(agent, emotion, s, e);
    if (_cache.TryGetValue(resPath, out var cached) && cached != null) return cached;

    // 1. Check CreatureDefinition's serialized soundBank slot
    var def = FindCreature(agent);
    int slot = SlotIndex(emotion, s, e);
    if (def != null && def.soundBank != null && slot < def.soundBank.Length && def.soundBank[slot].wavClip != null) {
      return _cache[resPath] = def.soundBank[slot].wavClip;
    }

    // 2. Check Resources/AgentSounds/... for a drop-in WAV file
    var wav = Resources.Load<AudioClip>(resPath);
    if (wav != null) return _cache[resPath] = wav;

    // 3. Synthesise procedurally advanced vocal sound
    var clip = Synthesize(ProfileOf(agent), emotion, s, e, resPath);
    _cache[resPath] = clip;
    return clip;
  }

  static CreatureDefinition FindCreature(string agent) {
    if (_defs.TryGetValue(agent, out var d) && d != null) return d;
    string want = agent == "Blue" ? "Go2" : agent;
    foreach (var c in CreatureRegistry.All())
      if (c.displayName == want || c.displayName == agent || c.name.EndsWith(want, StringComparison.OrdinalIgnoreCase))
        return _defs[agent] = c;
    return null;
  }

  /// <summary>Synthesises a multi-syllable source-filter vocal clip for (profile, emotion, sound 1..5, expressiveness 1..5).</summary>
  static AudioClip Synthesize(VoiceProfile p, AgentEmotion emotion, int soundIndex, int expressiveness, string name) {
    float u = (expressiveness - 1) / 4f;   // 0.0 (1=weakest) .. 1.0 (5=strongest)
    float baseDur = emotion == AgentEmotion.Hurt ? 0.28f : emotion == AgentEmotion.Angry ? 0.36f : emotion == AgentEmotion.Insult ? 0.42f : 0.38f;
    float dur = baseDur * Mathf.Lerp(0.72f, 1.38f, u) * (0.9f + 0.06f * soundIndex);
    int n = Mathf.CeilToInt(dur * Rate);
    var data = new float[n];
    var rng = new System.Random(p.seed + ((int)emotion * 31 + soundIndex * 7) * 13 + expressiveness);

    // Syllable count & prosody parameters vary across the 5 sound variants (1..5)
    int syllables = soundIndex == 1 ? 1 : soundIndex == 2 ? 2 : soundIndex == 3 ? 3 : soundIndex == 4 ? 2 : 4;
    float excursion = Mathf.Lerp(0.35f, 1.75f, u);       // pitch interval width scales strongly with expressiveness
    float drive = Mathf.Lerp(1.05f, 3.1f, u);            // nonlinear vocal effort / harmonic saturation
    float targetPeak = Mathf.Lerp(0.32f, 0.96f, u);      // level 1 weakest -> level 5 strongest
    float subMix = (emotion == AgentEmotion.Angry ? 0.42f : emotion == AgentEmotion.Insult ? 0.22f : 0.08f) * Mathf.Lerp(0.4f, 1.3f, u);
    float breathMix = (emotion == AgentEmotion.Hurt ? 0.38f : 0.14f) * Mathf.Lerp(0.6f, 1.4f, u);

    float phase = 0f, subPhase = 0f, ringPhase = 0f;
    float low1 = 0f, band1 = 0f, low2 = 0f, band2 = 0f, low3 = 0f, band3 = 0f;
    float peak = 1e-4f;

    for (int i = 0; i < n; i++) {
      float t = i / (float)Rate;
      float tau = i / (float)n;   // 0..1 normalized clip time

      // Syllabic amplitude envelope & pitch contour per emotion and soundIndex (1..5)
      float sylPos = tau * syllables;
      int sylIdx = Mathf.Min(syllables - 1, (int)sylPos);
      float sylU = sylPos - sylIdx;   // 0..1 within syllable
      float sylGate = Mathf.Sin(Mathf.PI * sylU);
      sylGate = Mathf.Pow(Mathf.Clamp01(sylGate * 1.35f), emotion == AgentEmotion.Angry ? 0.45f : 0.65f);
      // Fast attack on HURT and ANGRY
      float globalEnv = tau < 0.04f ? tau / 0.04f : Mathf.Pow(1f - tau, emotion == AgentEmotion.Hurt ? 0.85f : 0.55f);
      float env = sylGate * globalEnv;

      // Pitch contour (semitone offset from character's f0)
      float semi = 0f;
      switch (emotion) {
        case AgentEmotion.Happy:
          // Rising major intervals, bouncy arpeggios, joyful inflections
          if (soundIndex == 1) semi = Mathf.Lerp(-2f, 7f, tau) + 2f * Mathf.Sin(2f * Mathf.PI * 3f * tau);
          else if (soundIndex == 2) semi = (sylIdx == 0 ? 0f : 4f) + 3f * sylU;
          else if (soundIndex == 3) semi = (sylIdx * 3f) + 2f * Mathf.Sin(Mathf.PI * sylU);
          else if (soundIndex == 4) semi = sylIdx == 0 ? Mathf.Lerp(0f, 7f, sylU) : Mathf.Lerp(5f, 12f, sylU);
          else semi = 4f * Mathf.Sin(2f * Mathf.PI * 5f * tau) + 5f * tau;
          break;
        case AgentEmotion.Angry:
          // Hard downward snarl, aggressive bark jumps, tense growl modulation
          if (soundIndex == 1) semi = Mathf.Lerp(4f, -6f, tau) + 1.5f * Mathf.Sin(2f * Mathf.PI * 26f * t);
          else if (soundIndex == 2) semi = (sylIdx == 0 ? 3f : 5f) - 7f * sylU;
          else if (soundIndex == 3) semi = (sylIdx % 2 == 0 ? 4f : -3f) - 4f * sylU;
          else if (soundIndex == 4) semi = Mathf.Sin(Mathf.PI * tau) * 6f - 4f * tau + 2f * Mathf.Sin(2f * Mathf.PI * 30f * t);
          else semi = (3f - 2f * sylIdx) - 5f * sylU;
          break;
        case AgentEmotion.Hurt:
          // Sharp initial yelp spike followed by falling groan + pain vibrato
          if (soundIndex == 1) semi = (tau < 0.18f ? Mathf.Lerp(2f, 9f, tau / 0.18f) : Mathf.Lerp(9f, -5f, (tau - 0.18f) / 0.82f));
          else if (soundIndex == 2) semi = (sylIdx == 0 ? 7f : -2f) - 6f * sylU;
          else if (soundIndex == 3) semi = 6f * (1f - tau) - 3f * sylU;
          else if (soundIndex == 4) semi = Mathf.Lerp(5f, -7f, tau) + 2.5f * Mathf.Sin(2f * Mathf.PI * 9f * t);
          else semi = (sylIdx == 0 ? 8f : 2f - 2f * sylIdx) - 4f * sylU;
          break;
        case AgentEmotion.Insult:
          // Sing-song mocking minor-third ("nyah-nyah"), sarcastic upward sneer, taunting cadence
          if (soundIndex == 1) semi = (sylIdx == 0 ? 3f : 0f) + 1.5f * Mathf.Sin(Mathf.PI * sylU);
          else if (soundIndex == 2) semi = (sylIdx == 0 ? -3f : Mathf.Lerp(-1f, 8f, sylU));
          else if (soundIndex == 3) semi = (sylIdx == 0 ? 3f : sylIdx == 1 ? 0f : 5f) - 1.5f * sylU;
          else if (soundIndex == 4) semi = sylIdx == 0 ? -4f : Mathf.Lerp(4f, -2f, sylU);
          else { float[] mock = { 3f, 0f, 5f, 3f }; semi = mock[sylIdx % 4]; }
          break;
      }

      float vib = (0.15f + 0.35f * u) * Mathf.Sin(2f * Mathf.PI * p.vibratoHz * t);
      float f = p.f0 * Mathf.Pow(2f, (semi * excursion + vib) / 12f);
      phase += f / Rate; if (phase >= 1f) phase -= 1f;
      subPhase += (0.5f * f) / Rate; if (subPhase >= 1f) subPhase -= 1f;

      // Rosenberg-inspired glottal waveform (rich harmonics up to 6th partial)
      float w = 2f * Mathf.PI * phase;
      float glottal = Mathf.Sin(w) + 0.58f * Mathf.Sin(2f * w + 0.3f) + 0.36f * Mathf.Sin(3f * w + 0.7f)
                    + 0.22f * Mathf.Sin(4f * w + 1.1f) + 0.14f * Mathf.Sin(5f * w) + 0.08f * Mathf.Sin(6f * w);
      float sub = Mathf.Sin(2f * Mathf.PI * subPhase) + 0.4f * Mathf.Sin(4f * Mathf.PI * subPhase);
      float noise = (float)(rng.NextDouble() * 2.0 - 1.0);
      float plosive = sylU < 0.08f ? (1f - sylU / 0.08f) * 0.7f : 0f;
      float src = glottal * 0.55f + sub * subMix + noise * (breathMix + plosive);

      // Time-varying vowel formants (F1, F2, F3)
      float vowelMorph = emotion == AgentEmotion.Happy ? Mathf.Lerp(0.85f, 1.25f, sylU)
                       : emotion == AgentEmotion.Angry ? Mathf.Lerp(1.15f, 0.8f, sylU)
                       : emotion == AgentEmotion.Hurt  ? Mathf.Lerp(1.2f, 0.7f, tau)
                       : Mathf.Lerp(0.9f, 1.3f, sylU);
      float f1 = Mathf.Clamp(p.f1 * vowelMorph, 250f, 1100f);
      float f2 = Mathf.Clamp(p.f2 * (0.85f + 0.3f * u) * vowelMorph, 800f, 3200f);
      float f3 = Mathf.Clamp(p.f3 * (0.9f + 0.2f * u), 1800f, 4200f);

      float c1 = 2f * Mathf.Sin(Mathf.PI * f1 / Rate);
      float c2 = 2f * Mathf.Sin(Mathf.PI * f2 / Rate);
      float c3 = 2f * Mathf.Sin(Mathf.PI * f3 / Rate);
      low1 += c1 * band1; band1 += c1 * (src - low1 - 0.18f * band1);
      low2 += c2 * band2; band2 += c2 * (src - low2 - 0.14f * band2);
      low3 += c3 * band3; band3 += c3 * (src - low3 - 0.12f * band3);

      float vocal = band1 * 0.55f + band2 * (0.35f + 0.2f * u) + band3 * (0.18f + 0.22f * u);

      // Optional robotic ring-mod + pitch chirp for robot agents (Go2 / Blue, G1, etc.)
      if (p.robotic > 0.01f) {
        ringPhase += (p.ringHz * (1f + 0.4f * u)) / Rate; if (ringPhase >= 1f) ringPhase -= 1f;
        float ring = Mathf.Sin(2f * Mathf.PI * ringPhase);
        float chirp = Mathf.Sin(w * 2f + 1.5f * ring) * 0.6f + vocal * ring * 0.8f;
        vocal = Mathf.Lerp(vocal, chirp, p.robotic);
      }

      // Nonlinear vocal effort saturation
      float shaped = (float)Math.Tanh(vocal * drive) * env;
      data[i] = shaped;
      peak = Mathf.Max(peak, Mathf.Abs(shaped));
    }

    float norm = targetPeak / peak;
    int fade = Mathf.Min(n / 8, 96);
    for (int i = 0; i < n; i++) {
      float fadeEnv = i < fade ? i / (float)fade : i > n - fade ? (n - i) / (float)fade : 1f;
      data[i] = Mathf.Clamp(data[i] * norm * fadeEnv, -1f, 1f);
    }

    var clip = AudioClip.Create(name, n, 1, Rate, false);
    clip.SetData(data, 0);
    return clip;
  }
}

}
