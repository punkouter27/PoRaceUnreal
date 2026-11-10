using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

namespace PoRace {

/// <summary>Proposals r3 B1 / B2, PC tier: the most the GPU can afford, with a 30 fps floor.
/// Steps, best first: Ultra (render scale 1.0, MSAA 4x, 4 shadow cascades to 60 m), High (1.0, 2x, 2 cascades, 50 m),
/// Medium (0.85, no MSAA, 1 cascade, 40 m), Low (0.7, no MSAA, 25 m). In Auto the governor watches the 95th-percentile
/// frame time over 2 s: above 30 ms it steps down (3 s apart), under 20 ms for 5 s it steps up. The settings sheet
/// cycles Auto / Ultra / High. It works on a runtime copy of the URP asset (the project asset is never written), and
/// stays off on the Mobile tier (the phone asset is tuned by hand) and in headless runs. -quality ultra|high|medium|low
/// pins a step.</summary>
public class QualityGovernor : MonoBehaviour {
  public enum Mode { Auto, Ultra, High }
  static readonly string[] StepNames = { "Ultra", "High", "Medium", "Low" };
  public static Mode Current { get; private set; } = Mode.Auto;
  public static int Step { get; private set; } = 1;
  public static string Label => GfxTier.Mobile ? "Graphics: Mobile" : Current == Mode.Auto ? $"Graphics: Auto ({StepNames[Step]})" : $"Graphics: {Current}";
  static QualityGovernor _i;

  [Tooltip("Frame-time ceiling (ms) for the p95 before stepping down: 30 ms keeps a 33.3 ms (30 fps) floor with margin.")]
  public float downMs = 30f, upMs = 20f, upHold = 5f, cooldown = 3f;

  UniversalRenderPipelineAsset _asset;
  readonly float[] _ring = new float[256]; int _n, _head; float _since, _under, _cool;

  public static void Cycle() {
    if (_i == null || GfxTier.Mobile) return;
    Current = (Mode)(((int)Current + 1) % 3);
    if (Current == Mode.Ultra) _i.Apply(0); else if (Current == Mode.High) _i.Apply(1);
  }

  void Start() {
    if (BroadcastUi.Headless || GfxTier.Mobile) { enabled = false; return; }
    _i = this;
    var src = GraphicsSettings.currentRenderPipeline as UniversalRenderPipelineAsset;
    if (src == null) { enabled = false; return; }
    _asset = Instantiate(src); _asset.name = src.name + " (runtime)";
    QualitySettings.renderPipeline = _asset;
    if (CliArgs.TryString("-quality", out var q)) {
      int k = System.Array.FindIndex(StepNames, n => n.ToLowerInvariant() == q.ToLowerInvariant());
      if (k >= 0) { Current = k == 0 ? Mode.Ultra : Mode.High; Apply(k); enabled = k <= 1; return; }
    }
    Apply(1);
  }

  void OnDestroy() { if (_i == this) _i = null; }

  void Apply(int step) {
    Step = Mathf.Clamp(step, 0, StepNames.Length - 1);
    float[] scale = { 1f, 1f, 0.85f, 0.7f }, dist = { 60f, 50f, 40f, 25f };
    int[] msaa = { 4, 2, 1, 1 }, cascades = { 4, 2, 1, 1 };
    _asset.renderScale = scale[Step];
    _asset.msaaSampleCount = msaa[Step];
    _asset.shadowDistance = dist[Step];
    _asset.shadowCascadeCount = cascades[Step];
    _cool = cooldown; _under = 0f;
    Debug.Log($"[Quality] {StepNames[Step]}: render scale {scale[Step]}, MSAA {msaa[Step]}x, {cascades[Step]} cascade(s) to {dist[Step]} m");
  }

  void Update() {
    float dt = Time.unscaledDeltaTime * 1000f;
    _ring[_head] = dt; _head = (_head + 1) % _ring.Length; _n = Mathf.Min(_n + 1, _ring.Length);
    _since += Time.unscaledDeltaTime; _cool -= Time.unscaledDeltaTime;
    if (Current != Mode.Auto || _since < 2f || _cool > 0f) return;
    float p95 = P95();
    if (p95 > downMs && Step < StepNames.Length - 1) { Apply(Step + 1); _n = 0; return; }
    _under = p95 < upMs ? _under + Time.unscaledDeltaTime : 0f;
    if (_under > upHold && Step > 0) { Apply(Step - 1); _n = 0; }
  }

  readonly float[] _sort = new float[256];
  float P95() {
    int n = Mathf.Min(_n, _ring.Length); if (n < 30) return 0f;
    System.Array.Copy(_ring, _sort, n); System.Array.Sort(_sort, 0, n);
    return _sort[Mathf.Min(n - 1, (int)(0.95f * n))];
  }
}

}
