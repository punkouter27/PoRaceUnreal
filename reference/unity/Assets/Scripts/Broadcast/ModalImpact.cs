using System.Collections.Generic;
using UnityEngine;

namespace PoRace {

/// <summary>Proposals r3 B7, modal impact synthesis: an impact rings the struck material's resonant modes (a sum of
/// exponentially damped sines, plus a short contact-noise burst whose length follows the material's stiffness), scaled
/// by the collision's energy E = 1/2 J v (J impulse N.s, v approach m/s from ContactImpulse). Energy sets loudness and
/// brightness: mode k's gain grows as E^(0.18 k), so a hard hit excites the upper modes a tap leaves silent. Clips are
/// built once per (material, energy band, variant) and cached: no per-impact allocation, no sample library.</summary>
public static class ModalImpact {
  public enum Material { RobotShell, Metal, Track, Wood, Cube, Body }

  struct Spec { public float[] f, decay, gain; public float noise, noiseMs; }

  // Frequencies (Hz), decays (s, to 1/e) and base gains: a thin aluminium shell (the Go2 / Matt torso), a steel rail
  // (long ring), the track surface (low dull thud), wooden boards, a hollow plastic cube, a body on the ground.
  static readonly Dictionary<Material, Spec> Specs = new Dictionary<Material, Spec> {
    [Material.RobotShell] = new Spec { f = new[] { 310f, 870f, 1690f, 2950f }, decay = new[] { 0.22f, 0.15f, 0.09f, 0.05f }, gain = new[] { 1f, 0.6f, 0.4f, 0.25f }, noise = 0.35f, noiseMs = 6f },
    [Material.Metal] = new Spec { f = new[] { 523f, 1417f, 2638f, 4110f }, decay = new[] { 1.1f, 0.75f, 0.45f, 0.28f }, gain = new[] { 1f, 0.7f, 0.45f, 0.3f }, noise = 0.25f, noiseMs = 4f },
    [Material.Track] = new Spec { f = new[] { 92f, 187f, 405f }, decay = new[] { 0.09f, 0.06f, 0.035f }, gain = new[] { 1f, 0.5f, 0.25f }, noise = 0.6f, noiseMs = 18f },
    [Material.Wood] = new Spec { f = new[] { 178f, 512f, 1140f }, decay = new[] { 0.13f, 0.08f, 0.045f }, gain = new[] { 1f, 0.55f, 0.3f }, noise = 0.4f, noiseMs = 8f },
    [Material.Cube] = new Spec { f = new[] { 640f, 1530f, 3080f }, decay = new[] { 0.1f, 0.07f, 0.04f }, gain = new[] { 1f, 0.5f, 0.3f }, noise = 0.3f, noiseMs = 5f },
    [Material.Body] = new Spec { f = new[] { 70f, 150f, 330f }, decay = new[] { 0.07f, 0.05f, 0.03f }, gain = new[] { 1f, 0.45f, 0.2f }, noise = 0.7f, noiseMs = 24f },
  };

  public const int Bands = 4, Variants = 3;
  static readonly Dictionary<int, AudioClip> _cache = new Dictionary<int, AudioClip>();

  /// <summary>Material for a hit: robot-on-robot rings both shells; a body on the floor is a dull thud.</summary>
  public static Material Of(ContactImpulse.Hit h) =>
    h.kind == ContactKind.RobotRobot ? Material.RobotShell : h.kind == ContactKind.Cube ? Material.Cube :
    h.surface == Surface.Metal ? Material.Metal : h.surface == Surface.Wood ? Material.Wood :
    h.kind == ContactKind.Body ? Material.Body : Material.Track;

  /// <summary>Collision energy (J) and its band: 0 tap (< 0.3 J) .. 3 slam (> 6 J).</summary>
  public static float Energy(ContactImpulse.Hit h) => 0.5f * h.impulse * Mathf.Max(0.05f, h.approach);
  public static int Band(float e) => e < 0.3f ? 0 : e < 1.5f ? 1 : e < 6f ? 2 : 3;

  public static AudioClip Clip(Material mat, int band, int variant) {
    int key = ((int)mat * Bands + band) * Variants + variant;
    if (_cache.TryGetValue(key, out var c)) return c;
    var sp = Specs[mat];
    const int rate = 44100;
    float e = new[] { 0.15f, 0.8f, 3f, 10f }[band];
    float detune = 1f + 0.025f * (variant - 1);                       // three slightly different strikes
    float longest = 0f; foreach (var d in sp.decay) longest = Mathf.Max(longest, d);
    int n = Mathf.CeilToInt(rate * Mathf.Min(1.6f, longest * 5f));     // ring until ~-43 dB
    var data = new float[n];
    var rng = new System.Random(key * 7919);
    float peak = 1e-6f;
    for (int k = 0; k < sp.f.Length; k++) {
      float g = sp.gain[k] * Mathf.Pow(e, 0.18f * k), w = 2f * Mathf.PI * sp.f[k] * detune / rate, tau = sp.decay[k] * rate;
      float ph = (float)rng.NextDouble() * 6.283f;
      for (int i = 0; i < n; i++) data[i] += g * Mathf.Exp(-i / tau) * Mathf.Sin(w * i + ph);
    }
    int nn = Mathf.Min(n, (int)(rate * sp.noiseMs / 1000f));            // contact noise: short, low-passed
    float lp = 0f, a = Mathf.Clamp01(0.15f + 0.1f * band);
    for (int i = 0; i < nn; i++) { lp += a * ((float)rng.NextDouble() * 2f - 1f - lp); data[i] += sp.noise * lp * (1f - (float)i / nn); }
    for (int i = 0; i < n; i++) peak = Mathf.Max(peak, Mathf.Abs(data[i]));
    for (int i = 0; i < n; i++) data[i] /= peak;
    for (int i = 0; i < Mathf.Min(n, 32); i++) data[i] *= i / 32f;      // 0.7 ms attack: no click
    c = AudioClip.Create($"modal_{mat}_{band}_{variant}", n, 1, rate, false);
    c.SetData(data, 0);
    _cache[key] = c;
    return c;
  }
}

}
