"""Unreal Editor Python: the menu level /Game/Levels/L_Menu. Idempotent.

    UnrealEditor-Cmd.exe PoRaceUnreal.uproject -run=pythonscript -script="<abs path>/Scripts/build_menu.py" -unattended

No MuJoCo here: ARaceHUD finds no race controller and shows the menu (on an opaque backdrop; the level behind it is
only sky and light). START opens the picked track's level.
"""
import unreal

ASSETS = unreal.EditorAssetLibrary
LEVEL = "/Game/Levels/L_Menu"
unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(["/Game"], True)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
if ASSETS.does_asset_exist(LEVEL):
    les.load_level(LEVEL)
    for a in eas.get_all_level_actors():
        eas.destroy_actor(a)
else:
    les.new_level(LEVEL)


def spawn(cls, label, loc=(0, 0, 0), rot=(0, 0, 0)):
    a = eas.spawn_actor_from_class(cls, unreal.Vector(*loc), unreal.Rotator(pitch=rot[0], yaw=rot[1], roll=rot[2]))
    a.set_actor_label(label)
    return a


sun = spawn(unreal.DirectionalLight, "Sun", rot=(-35, 40, 0))
sun.light_component.set_editor_property("atmosphere_sun_light", True)
spawn(unreal.SkyLight, "SkyLight").light_component.set_editor_property("real_time_capture", True)
spawn(unreal.SkyAtmosphere, "SkyAtmosphere")
cam = spawn(unreal.CameraActor, "MenuCamera", (0, 0, 200), (5, 0, 0))
cam.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
for a in eas.get_all_level_actors():
    for c in a.get_components_by_class(unreal.PrimitiveComponent):
        c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        c.set_simulate_physics(False)
les.save_current_level()
unreal.log("[build_menu] done")
