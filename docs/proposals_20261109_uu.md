# UU_PROMPTS — 50-Option Execution Catalog (UE5 + MuJoCo v4 / Warp / URLab)

Scope: RL-trained humanoids (`Matt`, `Grandma`, `Agent04..16`) and quadrupeds (`Dog` / `Go2`) with realistic terrestrial motion (−9.81 m/s²), deployed in Unreal Engine 5 (Chaos disabled; MuJoCo C++ / URLab physics bridge with 100× Z-Up Left-Handed transform + UE5 NNE / ONNX Runtime zero-allocation C++ inference).

---

## 1. [FEATURES — Top 10 Options (Items 1–10)]

1. **Pre-Fall Center-of-Mass & Zero-Moment-Point (ZMP) Instability Cut**
   - **Functional Spec:** Predicts stumbles 150–250 ms before ground impact so the broadcast camera cuts to the stumbling agent before the fall occurs.
   - **Telemetry & Kinematics:** 50 Hz ZMP offset from support polygon (`mjData.subtree_com`, foot contact normals) + root pitch/roll angular velocity (`qvel[3..5]`) exceeding 2.8 rad/s and projected-gravity $g_z > -0.78$.
   - **Engine Integration:** C++ `UURaceDirectorSubsystem` scores pre-fall instability and triggers a UE5 **CineCameraActor** whip-pan with dynamic focal-length breathing and **Custom Depth Stencil** amber edge-outline.
   - **Policies Touched:** None (read-only sensor state).

2. **3D Support Polygon & Capture-Point Ground Projection**
   - **Functional Spec:** Renders a crisp, broadcast-style ground projection under the featured racer showing its instantaneous support triangle/line and extrapolated capture point ($\mathbf{r}_{\text{cp}} = \mathbf{r}_{\text{com}} + \dot{\mathbf{r}}_{\text{com}} / \omega_0$).
   - **Telemetry & Kinematics:** Foot contact positions (`mjData.contact`), `subtree_com`, and COM velocity decimated to 25 Hz.
   - **Engine Integration:** UE5 **DecalComponent** + **Runtime Virtual Texture (RVT)** splatting driven by a custom **Material Parameter Collection (MPC)**; zero dynamic actor spawning.
   - **Policies Touched:** None.

3. **Spline-Integrated Intent Ribbons & Tactical Lane Corridor**
   - **Functional Spec:** Displays each agent's 1.5-second predicted trajectory ribbon on the track surface, shifting color from cyan (clear lane) to orange (drafting/passing) to magenta (blocking/defending).
   - **Telemetry & Kinematics:** Forward-integrates the 50 Hz command vector $(v_x, v_y, \dot{\psi})$ from root pose (`qpos[0..6]`) over $H = 1.5\text{ s}$ with curvature clamping.
   - **Engine Integration:** Pre-allocated **USplineMeshComponent** pool updated via **Niagara Ribbon Renderer** on GPU with distance-field track edge masking.
   - **Policies Touched:** None.

4. **Time-to-Collision (TTC) Overtake & Slipstream Director**
   - **Functional Spec:** Replaces blind waypoint steering in crowded lanes with predictive pairwise TTC avoidance and slipstream slingshot passing while staying strictly inside each policy's trained command envelope.
   - **Telemetry & Kinematics:** Pairwise relative position $\Delta \mathbf{p}$ and relative velocity $\Delta \mathbf{v}$ from `qpos`/`qvel`; triggers lateral lane shift $v_y \in [-0.35, 0.35]\text{ m/s}$ when $\text{TTC} < 0.85\text{ s}$.
   - **Engine Integration:** Native C++ `UUTacticalDirector` state-machine row feeding the NNE command buffer before policy step.
   - **Policies Touched:** None (commands clamped to trained `[vx, vy, wz]` ranges).

5. **Anatomical Joint-Torque & Thermal Strain X-Ray Overlay**
   - **Functional Spec:** Highlights over-stressed knees, hips, and ankles on the broadcast subject using a translucent Subsurface/X-Ray rim glow when actuator effort nears saturation.
   - **Telemetry & Kinematics:** Per-joint strain ratio $\sigma_i = |\tau_i| / \tau_{i,\max}$ from `mjData.qfrc_actuator` and `ctrl`, smoothed with a 10 Hz EMA; redline threshold at $\sigma_i > 0.85$.
   - **Engine Integration:** Per-bone **Custom Primitive Data** float array driving a UE5 **Substrate (Strata)** dual-lobe emissive strain layer on `SKM_Matt`, `SKM_Grandma`, and `SKM_Go2`.
   - **Policies Touched:** None.

6. **Incident Force-Vector & Impulse Slow-Motion Replay**
   - **Functional Spec:** Automatically buffers the last 6 seconds of `mjData` state (`qpos`, `qvel`, `contact`) and plays a 0.25× picture-in-picture incident replay with 3D contact force arrows after any fall or heavy collision.
   - **Telemetry & Kinematics:** `mj_contactForce` 6D wrench $(f_n, f_{t1}, f_{t2})$ at each active contact point with impulse $J > 12\text{ N}\cdot\text{s}$.
   - **Engine Integration:** Pre-allocated circular state buffer in C++ replayed onto a secondary **SceneCaptureComponent2D** + **Niagara** 3D arrow mesh renderer.
   - **Policies Touched:** None.

7. **16-Agent Autonomous Tournament Broadcast Director**
   - **Functional Spec:** Runs the symmetric 16-player knockout bracket (`Slots 0..7` Left, `Slots 8..15` Right, `WINNER` in Center) unattended from R16 to Champion, updating persistent ELO ratings (`K = 32`) and cutting between pre-match tale-of-the-tape cards and live track action.
   - **Telemetry & Kinematics:** Match finish times, peak speed, fall count, and ELO delta $\Delta R = K(S - E)$.
   - **Engine Integration:** `UGameInstanceSubsystem` state machine driving level streaming / MuJoCo state reset without dynamic actor destruction.
   - **Policies Touched:** None.

8. **Yellow-Flag Pace Compression & Pack Re-Grouping**
   - **Functional Spec:** When $\ge 2$ racers enter `FALLEN_RECOVERING`, triggers a 5-second track caution that caps the leader's target $v_x$ to 80% of cruise so the pack compresses for high-tension restarts.
   - **Telemetry & Kinematics:** Count of agents with root height $z < z_{\text{fall}}$ or recovery skill active; command scaler $\alpha = 0.80$.
   - **Engine Integration:** `UURaceRulesDirector` + trackside **RectLight** amber caution strobes and HUD caution banner.
   - **Policies Touched:** None (stays within trained velocity command range).

9. **Dynamic Head-On Rivalry Camera & Look-At Neck Bias**
   - **Functional Spec:** When the gap between P1 and P2 drops below 2.5 m, engages a low-angle reverse lead camera with shallow depth-of-field tracking both racers' eyes/heads.
   - **Telemetry & Kinematics:** Inter-agent arc-length gap $\Delta s < 2.5\text{ m}$ and closing speed $\dot{\Delta s} < -0.2\text{ m/s}$.
   - **Engine Integration:** UE5 **CineCameraActor** on a track-parallel **USplineComponent** with **Control Rig** additive head/eye look-at target (visual-only neck rotation post-physics, zero physics feedback).
   - **Policies Touched:** None.

10. **Live Neural Activation & Gait Phase Oscilloscope (`TAB` Inspector)**
    - **Functional Spec:** Visualizes the featured agent's 103-D observation vector, 2-D gait phase clock $(\sin\phi, \cos\phi)$, and 29-D / 12-D action outputs in real time for debugging policy hand-overs.
    - **Telemetry & Kinematics:** Raw NNE input/output tensors and foot contact booleans at 50 Hz.
    - **Engine Integration:** GPU-instanced Slate / UMG oscilloscope strip toggled via `TAB`.
    - **Policies Touched:** None.

---

## 2. [CLEAN — Top 10 Options: Artifact Purge & Directory Standardization (Items 11–20)]

11. **Automated Training Run & Checkpoint Pruner (`tools/prune.py`)**
    - **Spec:** Purges failed runs, short checks (`< 5,000` steps), and redundant intermediate `.pkl`/`.onnx`/`.pt` checkpoints while strictly protecting runs modified within the last 24 hours or referenced in `rl_optimization_log.md`. Reports total MB/GB reclaimed.

12. **Strict Unreal Asset Prefix Enforcement (`BP_`, `SM_`, `SKM_`, `M_`, `MI_`, `T_`, `NS_`, `MS_`)**
    - **Spec:** Standardizes all runtime assets under `Content/` (`BP_` Blueprints, `SM_` Static Meshes, `SKM_` Skeletal Meshes, `M_`/`MI_` Master/Instance Materials, `T_` Textures, `NS_` Niagara Systems, `MS_` MetaSounds) via automated CLI asset audit.

13. **PascalCase Directory Hierarchy (`Content/Core/`, `Content/Shared/`, `Content/UI/`, `Content/Art/`)**
    - **Spec:** Reorganizes project folders into strict PascalCase (`Content/Core/`, `Content/Shared/`, `Content/UI/`, `Content/Art/Raw/`, `Content/Art/Exports/`) with zero spaces or lowercase drift.

14. **Orphaned Texture, Material & Mesh Reference Sweeper**
    - **Spec:** Scans the asset registry / GUID graph for unreferenced `.uasset` / `.mat` / `.png` / `.glb` files not linked by any level, character card, or C++ registry, archiving or purging dead files and reporting reclaimed disk space.

15. **MuJoCo-Warp & Console Log Noise Suppression**
    - **Spec:** Suppresses high-frequency `solver iterations limit reached` and non-critical runtime telemetry spam (`m.opt.warn_overflow = 0` in trainer; `UE_LOG` verbosity gated to `Warning` in shipping/race loops), preventing multi-hundred-MB log bloat.

16. **Scratch & Intermediate Import Cache Purge (`Assets/Local/MjImports`, `Temp/`, `Logs/`)**
    - **Spec:** Cleans stale MJCF scratch imports and logs older than 7 days while keeping deterministic flattened runtime XMLs in `Content/Art/Exports/MJCF/`.

17. **Dead Code Branch & Unused Policy Stub Removal**
    - **Spec:** Audits C++ / C# controllers and removes unreachable legacy fallback branches, unused policy slots, and obsolete debug harnesses while preserving regression gates.

18. **Shared Math, Ring-Buffer & EMA Filter Consolidation (`Core/RacerMath`)**
    - **Spec:** Consolidates duplicate exponential moving averages, quaternion-to-heading helpers, and ring buffers across telemetry, strain, wobble, and audio modules into a single zero-allocation utility header/class.

19. **Screenshot & HTML Report Compaction (`SCREENSHOTS/`)**
    - **Spec:** Prunes superseded intermediate PNG captures not referenced by any `SCREENSHOTS/*.html` or `docs/` report, reporting disk space saved.

20. **Primary Viewport UX Declutter & Slide-Out Modal Routing**
    - **Spec:** Strips permanent debug text, raw command vectors, bump counters, and secondary camera buttons from the main race viewport; routes all secondary controls, weather details, and tuning parameters into a single right-edge slide-out drawer and `TAB` debug overlay.

---

## 3. [GFX & AUDIO — Top 10 Options: UE5 High-End Visuals, Acoustics & CCD (Items 21–30)]

21. **Lumen Hardware Ray-Traced Global Illumination & Reflections**
    - **Spec:** Enables UE5 **Lumen** multi-bounce diffuse GI and high-precision screen-space + hardware ray-traced reflections on wet/polished track surfaces and metallic robot chassis (`Go2`), governed to maintain a strict $\ge 30\text{ FPS}$ floor.

22. **Virtual Shadow Maps (VSM) & High-Resolution Contact Shadows**
    - **Spec:** Deploys UE5 **Virtual Shadow Maps** with per-pixel contact shadows so foot-to-ground touchdowns (`Dog` paws, `Matt` and `Grandma` shoes) exhibit zero shadow detachment or peter-panning.

23. **Substrate (Strata) Dual-Specular Skin & Subsurface Scattering**
    - **Spec:** Upgrades human characters (`Matt`, `Grandma`) to UE5 **Substrate** subsurface scattering profiles with pore-level micro-normal maps baked from Blender and roughness clamping (`gloss <= 0.45`) to eliminate plastic mirror artifacts.

24. **Volumetric Fog, God-Rays & Chromatic Lens Dispersion**
    - **Spec:** Adds stadium spotlight volumetric shafts, subtle atmospheric haze, and physical camera chromatic dispersion / lens flare via UE5 **Volumetric Fog** and **PostProcessVolume** convolution bloom.

25. **Niagara GPU Compute Impact Bursts & Tire/Shoe Rubber Scuff Decals**
    - **Spec:** Spawns 10,000-particle GPU **Niagara** spark/dust bursts and persistent **DBuffer Decal** skid/scuff marks driven directly by MuJoCo contact impulse $J$ and tangential slip velocity $\mathbf{v}_t$.

26. **Adaptive 30 FPS Frame-Budget Governor (`UUQualityGovernor`)**
    - **Spec:** Monitors rolling p95 frame time (2 s window) and dynamically scales **Temporal Super Resolution (TSR)** screen percentage (`100% <-> 70%`), Lumen ray count, and Niagara particle density to hold $\ge 30\text{ FPS}$ under 16-agent load.

27. **MuJoCo v4 Continuous Collision Detection (CCD) & Zero-Penetration Solver Audit**
    - **Spec:** Enforces primitive-only colliders (capsules/spheres/boxes), `ccd_iterations >= 35`, accurate anatomical mass ratios (`Go2` 15 kg, `Matt` 86 kg, `Grandma` 73.6 kg), and continuous penetration auditing (`ContactAudit` gate $< 1\text{ cm}$ sustained) with realistic momentum transfer.

28. **Modal Impact & Continuous Shear-Friction Synthesis (`MetaSounds`)**
    - **Spec:** Replaces static WAV impacts with a procedural modal resonator bank (damped frequency/decay modes per material pair: rubber-asphalt, metal-metal, cloth-turf) excited by collision energy $E = J^2 / (2 m_{\text{red}})$, plus continuous foot-slide friction modulated by tangential shear speed $|\mathbf{v}_t|$.

29. **100-Slot Procedural Formant Voice Synth + HRTF Binaural Spatialization**
    - **Spec:** Routes each agent's 100 expressive vocal slots (`HAPPY`, `ANGRY`, `HURT`, `INSULT` $\times 5 \times 5$, WAV with Rosenberg glottal + 3-formant $F_1, F_2, F_3$ procedural synthesis fallback) through UE5 **HRTF Binaural Spatialization** and stadium **Geometric Acoustic Reverb**.

30. **Headless Blender 5.2 Automated LOD, Normal-Bake & MJCF Export Pipeline**
    - **Spec:** Runs `blender --background --python` across `Content/Art/Raw/*.blend` to generate `LOD0/LOD1/LOD2` meshes (100% / 50% / 20%), bake tangent-space cavity/thickness maps, and verify 1:1 bone/joint frame parity with exported MJCF XMLs.

---

## 4. [UI — Top 10 Options: Single-Screen Zero-Scroll HUD & Flow (Items 31–40)]

31. **`TL` Corner: Compact Scene & Lap Pill (`Flat Oval · Lap 1/2`)**
    - **Spec:** Anchors a single notch-safe top-left badge displaying the active track name, lap counter, and compact weather icon at $\ge 11\text{ pt}$ (`fontSize >= 22` at 720p).

32. **`TC` Corner: Minimal Frame & Physics Step Pill (`60 FPS · 250 Hz`)**
    - **Spec:** Displays only real-time render FPS and MuJoCo physics step rate (`250 Hz` sim / `50 Hz` policy) in top-center; hides verbose solver and inference timings behind `TAB`.

33. **`TR` Corner: Single Settings & Pause Gear Trigger**
    - **Spec:** Consolidates Pause, Camera Flip, Graphics Tier, Audio Mix, Restart, and Main Menu actions into one top-right gear button that opens a clean slide-out sheet.

34. **`BL` Corner: Featured Agent Live Telemetry Stream**
    - **Spec:** Displays the broadcast subject's live speed ($\text{m/s}$), stride cadence ($\text{Hz}$), stride length ($\text{m}$), actuator effort bar ($\%$), and current ELO rating in a compact bottom-left card.

35. **`BR` Corner: Automated `YYMMDD` Build Stamp (`v0.1.0 261109`)**
    - **Spec:** Renders the isolated, high-contrast `YYMMDD` build watermark in the bottom-right corner per `AGENTS.md` Section 1.

36. **Symmetric 16-Player Bracket View (8 Left, 8 Right, Winner Center)**
    - **Spec:** Renders `Slots 0..7` on the left (`R16 -> QF -> SF`), `Slots 8..15` on the right (`R16 -> QF -> SF`), and the gold-bordered `WINNER` box in the exact center (`x = 360`) with live ELO ratings, `BYE` placeholders, and click-to-preview character vocalizations.

37. **One-Thumb Bottom-Sheet Tabs for Spectator Betting & Nudge Votes**
    - **Spec:** Moves spectator odds and hazard/nudge voting into a collapsible bottom-sheet tab within one-thumb reach on mobile-portrait and ultrawide (16:9 to 21:9) viewports, never occluding the center racing action.

38. **Explicit 4-Stage State Flow (`Menu -> RacerIntro -> Gameplay -> Win/Loss -> Reset`)**
    - **Spec:** Enforces deterministic screen transitions: Main Menu $\rightarrow$ 1.8 s per-racer camera push-in intro (with `HAPPY`/`INSULT` vocalization) $\rightarrow$ Race $\rightarrow$ Results Card (Winner banner, aligned split times, ELO delta, `OK` button + 3.5 s auto-advance in self-playing tournament).

39. **Notch-Safe 16:9 to 21:9 Aspect-Ratio Safe-Zone Enforcer (`ShotProbe`)**
    - **Spec:** Validates zero AABB bounding-box overlap and zero text clipping across `16:9`, `19.5:9`, `20:9`, and `21:9` viewports with simulated camera-cutout safe margins.

40. **`TAB` Toggleable Engineering & Policy Diagnostics Overlay**
    - **Spec:** Keeps the default spectator viewport 100% clutter-free while allowing instant `TAB` toggle of the 5-second contact penetration audit, frame-time histogram, active policy state-machine row, and NNE inference microsecond budget.

---

## 5. [CLEAN & AI ANIMAL REALISM — Top 10 Options: Biomechanics, MuJoCo v4 & RL Curriculum (Items 41–50)]

41. **Anatomical DoF Envelopes & Mass Distribution Audit (`check_model.py`)**
    - **Spec:** Enforces terrestrial gravity ($-9.81\text{ m/s}^2$), realistic segment masses (`73.6 kg` Grandma, `86.0 kg` Matt, `15.0 kg` Go2), and physiological joint range-of-motion and torque limits across all primitive capsule/sphere/box collision geoms with zero rest penetration.

42. **Speed-Coupled Adaptive Gait Phase Clock ($\omega(v_x) = \omega_0 + k \max(0, |v_x| - v_0)$)**
    - **Spec:** Replaces fixed-frequency stepping with a velocity-dependent phase oscillator integrated identically in Python (`matt/env.py`, `grandma/env.py`) and runtime (`HumanSpec`), enabling smooth transitions from walk ($0.9\text{ Hz}$) to brisk run ($1.55\text{ Hz}$).

43. **Sub-Step High-Frequency Foot-Contact & Ground-Reaction Sensing**
    - **Spec:** Aggregates foot contact flags and vertical ground-reaction forces across all 5 MuJoCo physics sub-steps ($dt_{\text{sim}} = 0.004\text{ s}$ per $dt_{\text{ctrl}} = 0.02\text{ s}$) and appends them at the end of the observation vector with zero-initialized weights (strictly preserving frozen-interface compatibility).

44. **First-Order Low-Pass Action Filter & Jerk/Oscillation Penalty**
    - **Spec:** Applies a causal exponential low-pass filter ($\mathbf{u}_t = \alpha \mathbf{u}_{t-1} + (1-\alpha)\mathbf{a}_t$) and FFT > 8 Hz joint-velocity power penalty (`< 10%` high-frequency share gate) to eliminate servo chatter and produce fluid terrestrial motion.

45. **5-Stage Biomechanical Curriculum (`L1 Stand -> L2 Walk -> L3 Turn -> L4 Fast/Perturb -> L5 Slope`)**
    - **Spec:** Advances each character from balance (`L1`) to slow locomotion (`L2`), yaw tracking (`L3`), push-recovery & brisk cruise (`L4`), and $\pm 10\%$ grade slopes (`L5`), gating progression on survival rate and velocity tracking error.

46. **MuJoCo v4 / Warp Implicit-Fast Integrator & Solver Warmstart Optimization**
    - **Spec:** Uses MuJoCo v4 / `mujoco_warp` `implicitfast` integration, elliptic friction cones (`impratio = 1..10`), tuned `ccd_iterations`, and contact solver warm-starting across 1,024 parallel GPU environments on RTX 2060.

47. **Real-Fall Get-Up & Balance Hand-Over Distillation**
    - **Spec:** Trains dedicated recovery/get-up policies initialized directly from distribution of real simulated falls; preloads all policies at level init and carries over the last action vector $\mathbf{a}_{t-1}$ across director transitions without pose snapping.

48. **Character-Card Trait-Driven Style Rewards (Zero Brain Sharing)**
    - **Spec:** Derives each character's gait signature from its `CreatureDefinition` card traits (e.g., Grandma's shorter stride, upright torso, wider stance vs. Matt's long athletic stride), training a separate policy per character from scratch.

49. **Preflight Cryptographic Snapshot & Interface Tag Gate (`preflight.py`)**
    - **Spec:** Computes and verifies SHA-256 hashes of the MJCF physics model, observation layout (`obs_dim`), action map (`act_dim`), timestep, and gait clock parameters (`tags.json`) prior to training restore or ONNX export, blocking cross-creature or mismatched-interface loads.

50. **100-Episode Graduation Gate & 5-Second Kinematic/Contact Rollout Benchmark**
    - **Spec:** Exports `.onnx` to runtime only after holding target reward for 100 consecutive episodes with zero NaN gradients and passing a 5-second rollout check verifying (1) root velocity, angular momentum, and joint angles match the MuJoCo baseline within $< 10^{-4}$ parity, and (2) zero foot sliding, ground clipping, or contact chatter.
