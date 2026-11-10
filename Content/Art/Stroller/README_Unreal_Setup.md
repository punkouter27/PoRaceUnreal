# Stroller — Chaos Vehicle setup (UE5)

## Files
| File | What |
|---|---|
| `SK_Stroller.fbx` | Skeletal mesh, LOD0 (~38k tris), textures embedded |
| `SK_Stroller_LOD1.fbx` | Same rig, ~9.5k tris — import as LOD1 |
| `Textures/T_Stroller_D.jpg`, `T_Stroller_N.jpg` | 4K diffuse + normal (also embedded in the FBX) |
| `stroller_vehicle.blend` | Source scene (rig + clean wheels) for future edits |

Model facts: faces **+X**, Z-up, ground at Z=0, origin at bottom-center of the rear axle line.
Size ≈ 112 × 78 × 100 cm.

| Bone | Location (cm, UE) | Wheel radius | Wheel width |
|---|---|---|---|
| `root` | 0, 0, 0 | — | — |
| `wheel_front` | X 43.7, Z 12.8 | 12.8 cm | 4.5 cm |
| `wheel_rear_l` | X -23.2, Z 16.8 | 16.8 cm | 6 cm |
| `wheel_rear_r` | X -23.2, Z 16.8 | 16.8 cm | 6 cm |

Each wheel is skinned 100% to its bone; everything else is skinned to `root`.

## 1. Import
1. Enable the **ChaosVehicles** plugin (Edit → Plugins), restart.
2. Drag `SK_Stroller.fbx` into the Content Browser:
   - Skeletal Mesh ✔, Import Mesh ✔, Create Physics Asset ✔
   - Import Animations ✘
   - Materials: Create New Materials, Import Textures ✔
3. Check the size against a mannequin (~112 cm long). If it comes in 100× too small or large, re-import with Import Uniform Scale 100 or 0.01.
4. Open the skeletal mesh → LOD Settings → LOD Import → **Import LOD Level 1** → `SK_Stroller_LOD1.fbx`.
   (Or skip that and use Auto-generate LODs.)
5. In the Body material, make sure the normal map texture is set to compression **Normalmap**.

## 2. Physics Asset (important — auto-generated collision for scans is messy)
1. Open `SK_Stroller_PhysicsAsset`. Delete all generated bodies.
2. Add one **Box** body on `root` covering the frame/seats. Keep its bottom ~8–10 cm **above** the ground, so only the wheels touch the ground.
   Optionally add a second box for the handlebar.
3. Do **not** add bodies on the wheel bones (Chaos wheels are raycast). If any exist, delete them.

## 3. Animation Blueprint
1. Right-click the skeleton → Create → Anim Blueprint, parent class **VehicleAnimationInstance**.
2. AnimGraph: `Mesh Space Ref Pose` → **Wheel Controller** → `Component To Local` → Output Pose.

## 4. Wheel Blueprints (ChaosVehicleWheel)
**BP_StrollerWheel_Front**
- Wheel Radius **12.8**, Wheel Width **4.5**
- Affected by Steering ✔, Max Steer Angle **45**
- Affected by Engine ✘, Affected by Handbrake ✘

**BP_StrollerWheel_Rear**
- Wheel Radius **16.8**, Wheel Width **6**
- Affected by Engine ✔ (rear-wheel drive = a parent pushing), Affected by Handbrake ✔, Affected by Steering ✘

Suspension, both: Max Raise **2**, Max Drop **3**, Spring Rate **~30**, Spring Preload **~10** (tune).

## 5. Vehicle Pawn
1. Create a Blueprint, parent class **WheeledVehiclePawn**. Set Mesh → `SK_Stroller`, Anim Class → your AnimBP.
2. Vehicle Movement Component → **Wheel Setups** (3 entries):
   - `BP_StrollerWheel_Front` — Bone **wheel_front**
   - `BP_StrollerWheel_Rear` — Bone **wheel_rear_l**
   - `BP_StrollerWheel_Rear` — Bone **wheel_rear_r**
3. Starting values for a stroller (default car values will flip it):
   - Mass **14** kg
   - Center Of Mass Override ✔ → about **(-10, 0, 20)** (low, toward the rear axle)
   - Engine: Max Torque **15–25**, Max RPM **1500**
   - Transmission: Automatic, one forward gear
   - Drag Coefficient **0.1**, Downforce **0**
4. Hook up throttle, steering and brake input like the vehicle template project.

## Troubleshooting
- **Wheels spin around the wrong axis or wobble:** check the Wheel Setups bone names. The wheel bones' pivots are exactly at the hub centers.
- **Vehicle drags or bounces:** a physics body is touching the ground. Raise the chassis box.
- **Tips over in turns:** lower the center of mass (smaller Z), reduce Max Steer Angle, or widen it with the Stability/Arcade settings.
