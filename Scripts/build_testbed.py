"""Unreal Editor Python: the parity testbed level (one Go2 on a flat floor). Idempotent.

    UnrealEditor-Cmd.exe PoRaceUnreal.uproject -run=pythonscript -script="<abs path>/Scripts/build_testbed.py" -unattended

Run from PowerShell, not Git Bash (Git Bash rewrites "/Game/..." values into Windows paths).
Imports training/assets/go2/scene_porace.xml through URLab, puts a URacerController on the imported Blueprint and
builds /Game/Levels/L_Testbed. RACE_BRAIN = an .onnx to import as the default brain (default go2_loco).

Chaos stays out: nothing placed here collides or simulates. MuJoCo (URLab) owns all physics.
"""
import os
import unreal

PROJ = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
ASSETS = unreal.EditorAssetLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()
# a commandlet starts before the asset registry has scanned Content: without this, does_asset_exist() answered False for
# a Blueprint that was there, the old one was never deleted and the new import could not take its name (Slice 3)
unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(["/Game"], True)
MODEL = os.environ.get("RACE_MODEL", "training/assets/go2/scene_porace.xml")
BRAIN = os.environ.get("RACE_BRAIN", "training/models/brains/go2_loco.onnx")
LEVEL = "/Game/Levels/L_Testbed"
BP = "/Game/Racers/Go2/BP_Go2_testbed"


def log(msg):
    unreal.log(f"[build_testbed] {msg}")


def import_file(src, dest, name=None):
    t = unreal.AssetImportTask()
    t.filename = os.path.join(PROJ, src)
    if not os.path.isfile(t.filename):   # a missing source crashes ImportAssetTasks
        raise FileNotFoundError(t.filename)
    t.destination_path = dest
    t.destination_name = name or ""
    t.automated = True
    t.replace_existing = True
    t.save = True
    tools.import_asset_tasks([t])
    log(f"imported {src} -> {list(t.imported_object_paths)}")
    return [ASSETS.load_asset(p) for p in t.imported_object_paths]


brain = import_file(BRAIN, "/Game/Brains")[0]

# The level first: wipe and save it so the old Blueprint has no references left (URLab refuses to import over a
# Blueprint the open level still instantiates).
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
if ASSETS.does_asset_exist(LEVEL):
    les.load_level(LEVEL)
    for a in eas.get_all_level_actors():
        eas.destroy_actor(a)
    les.save_current_level()
else:
    les.new_level(LEVEL)

if ASSETS.does_asset_exist(BP):   # URLab won't overwrite; the MJCF may have changed
    ASSETS.delete_asset(BP)
imported = import_file(MODEL, "/Game/Racers/Go2")
racer_bp = next(a for a in imported if isinstance(a, unreal.Blueprint))
ASSETS.rename_asset(racer_bp.get_path_name().split(".")[0], BP)   # URLab names it after the XML
racer_bp = ASSETS.load_asset(BP)

# the controller component on the imported Blueprint (URLab binds it after the model compiles)
sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
lib = unreal.SubobjectDataBlueprintFunctionLibrary
handles = sub.k2_gather_subobject_data_for_blueprint(racer_bp)
if not any(isinstance(lib.get_associated_object(lib.get_data(h)), unreal.RacerController) for h in handles):
    p = unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=unreal.RacerController, blueprint_context=racer_bp)
    _, fail = sub.add_new_subobject(p)
    log(f"added RacerController ({fail or 'ok'})")
    handles = sub.k2_gather_subobject_data_for_blueprint(racer_bp)
for h in handles:
    obj = lib.get_associated_object(lib.get_data(h))
    if isinstance(obj, unreal.RacerController):
        obj.set_editor_property("brain", brain)
        obj.set_editor_property("fingerprint", "training/models/go2_fingerprint.json")
        obj.set_editor_property("mode", unreal.RaceControlMode.POLICY)
unreal.BlueprintEditorLibrary.compile_blueprint(racer_bp)
ASSETS.save_loaded_asset(racer_bp)


def spawn(cls, label, loc=(0, 0, 0), rot=(0, 0, 0)):
    # rot = (pitch, yaw, roll)
    a = eas.spawn_actor_from_class(cls, unreal.Vector(*loc), unreal.Rotator(pitch=rot[0], yaw=rot[1], roll=rot[2]))
    a.set_actor_label(label)
    return a


mgr = spawn(unreal.AMjManager, "MjManager")
engine = mgr.get_component_by_class(unreal.MjPhysicsEngine)
engine.set_editor_property("save_debug_xml", True)   # Saved/URLab/scene_compiled.mjb: the model the parity gate steps
engine.set_editor_property("is_paused", False)       # run on Play
mgr.set_editor_property("auto_create_simulate_widget", False)
spawn(racer_bp.generated_class(), "Go2")

# enough light and a camera to look at it in a window (the parity runs are headless)
sun = spawn(unreal.DirectionalLight, "Sun", rot=(-50, 30, 0))
sun.get_component_by_class(unreal.DirectionalLightComponent).set_editor_property("intensity", 6.0)
spawn(unreal.SkyLight, "SkyLight").get_component_by_class(unreal.SkyLightComponent).set_editor_property("real_time_capture", True)
spawn(unreal.SkyAtmosphere, "SkyAtmosphere")
cam = spawn(unreal.CameraActor, "TestbedCamera", loc=(150, -300, 120), rot=(-12, 100, 0))
cam.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)

n = 0
for a in eas.get_all_level_actors():
    for c in a.get_components_by_class(unreal.PrimitiveComponent):
        c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        c.set_simulate_physics(False)
        n += 1
log(f"Chaos off on {n} primitive components")

les.save_current_level()
unreal.get_editor_subsystem(unreal.EditorAssetSubsystem).save_directory("/Game", only_if_is_dirty=True, recursive=True)
log("done")
