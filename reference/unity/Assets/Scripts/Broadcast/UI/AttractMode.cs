using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace PoRace {

/// <summary>Arcade attract mode. Nobody touches the menu for attractSeconds (-attractAfter &lt;s&gt;, default 30): demo races
/// start, race after race (RaceConfig.autoplay, the self-running app), under a blinking "DEMO · TAP TO PLAY" banner.
/// Any key, click, touch or gamepad press during a demo goes back to the main menu. A menu idle while a tournament
/// is open demos too and comes back to the bracket. Off in -raceTest, headless and capture-probe runs (-menuMap,
/// -tournamentAuto) and with -noAttract. Also shows the banner on -autoplay runs. Never touches MuJoCo.</summary>
public class AttractMode : MonoBehaviour {
  public float attractSeconds = 30f;
  static AttractMode _i;
  float _idle, _sceneAge; Text _banner; bool _demoScene;
  Vector2 _lastMouse;

  [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
  static void Boot() {
    if (CliArgs.RaceTest || Application.isBatchMode || CliArgs.Has("-noAttract")) return;
    var go = new GameObject("AttractMode"); DontDestroyOnLoad(go); _i = go.AddComponent<AttractMode>();
    if (CliArgs.TryFloat("-attractAfter", out float s)) _i.attractSeconds = s;
    SceneManager.sceneLoaded += (sc, m) => { if (_i != null) _i.OnScene(sc); };
  }

  /// <summary>Demo races may start from this menu: not when a probe drives the menu itself.</summary>
  static bool ProbeDriven => CliArgs.Has("-menuMap") || CliArgs.Has("-tournament") || CliArgs.Has("-tournamentAuto");

  void OnScene(Scene s) {
    _idle = 0f; _sceneAge = 0f; _banner = null;
    _demoScene = RaceConfig.autoplay && FindAnyObjectByType<MultiRaceOrchestrator>() != null;
    if (!_demoScene || BroadcastUi.Headless) return;
    var top = new Vector2(0.5f, 1f);
    var bg = BroadcastUi.Panel(BroadcastUi.Root, "AttractBanner", top, top, new Vector2(0, -318), new Vector2(480, 62), new Color(0f, 0f, 0f, 0.55f));
    bool touch = Touchscreen.current != null || Application.isMobilePlatform;
    _banner = BroadcastUi.Label(bg.transform, "Text", new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(470, 60), 30, TextAnchor.MiddleCenter,
        $"DEMO  ·  {(touch ? "TAP TO PLAY" : "PRESS ANY KEY")}");
    _banner.fontStyle = FontStyle.Bold; _banner.color = BroadcastUi.Accent;
  }

  /// <summary>A press of anything: keys, mouse buttons, a touch, the gamepad's face / start buttons.</summary>
  static bool Pressed() {
    var k = Keyboard.current; if (k != null && k.anyKey.wasPressedThisFrame) return true;
    var m = Mouse.current; if (m != null && (m.leftButton.wasPressedThisFrame || m.rightButton.wasPressedThisFrame)) return true;
    var t = Touchscreen.current; if (t != null && t.primaryTouch.press.wasPressedThisFrame) return true;
    var g = Gamepad.current; if (g != null && (g.buttonSouth.wasPressedThisFrame || g.startButton.wasPressedThisFrame)) return true;
    return false;
  }

  void Update() {
    _sceneAge += Time.unscaledDeltaTime;
    bool pressed = Pressed();
    if (_demoScene) {
      if (_banner != null) _banner.enabled = Mathf.Repeat(Time.unscaledTime, 1f) < 0.62f;   // arcade blink
      if (pressed && _sceneAge > 0.5f && RaceConfig.autoplay) {   // the grace stops a press that started the load from ending it
        RaceConfig.autoplay = false; Time.timeScale = 1f;
        if (Application.CanStreamedLevelBeLoaded("Menu")) SceneManager.LoadScene("Menu");
      }
      return;
    }
    if (SceneManager.GetActiveScene().name != "Menu" || ProbeDriven) return;
    var mouse = Mouse.current; bool moved = false;
    if (mouse != null) { var p = mouse.position.ReadValue(); moved = (p - _lastMouse).sqrMagnitude > 36f; _lastMouse = p; }
    _idle = pressed || moved ? 0f : _idle + Time.unscaledDeltaTime;
    if (_idle > attractSeconds) {
      _idle = 0f;
      Debug.Log($"[Attract] menu idle {attractSeconds:F0} s: demo races");
      RaceConfig.autoplay = true; RaceConfig.LaunchNextAutoplay();
    }
  }
}

}
