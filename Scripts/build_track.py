"""Unreal Editor Python: a race level for one track. Idempotent.

    $env:RACE_TRACK = "planar_sprint"
    UnrealEditor-Cmd.exe PoRaceUnreal.uproject -run=pythonscript -script="<abs path>/Scripts/build_track.py" -unattended

Run from PowerShell, not Git Bash (Git Bash rewrites "/Game/..." values into Windows paths).
Needs training/assets/tracks/<track>.xml and its fingerprint first: python training/build_track_model.py <track>.

Builds /Game/Levels/L_<Track>:
  - the track model through URLab (floor, rails, every racer) with a URacerController that runs the race
  - the track surface as drawn meshes (5 m tiles in two shades, start line, checkpoint marks, finish line)
  - sun, sky, fog, the director (ARaceDirector) and its chase camera
Chaos stays out: nothing placed here collides or simulates. MuJoCo (URLab) owns all physics.
"""
import math
import os
import sys

import unreal

PROJ = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
sys.path.insert(0, os.path.join(PROJ, "training"))
from racelib.track import Track, left  # noqa: E402  (pure Python: math + json)

ASSETS = unreal.EditorAssetLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()
MEL = unreal.MaterialEditingLibrary
TRACK = os.environ.get("RACE_TRACK", "planar_sprint")
PASCAL = "".join(w.capitalize() for w in TRACK.split("_"))
LEVEL = f"/Game/Levels/L_{PASCAL}"
FOLDER = f"/Game/Tracks/{PASCAL}"
BP = f"{FOLDER}/BP_{PASCAL}_Track"
OPEN_END = 6.0      # m of drawn surface past each end of an open track (as the rails)
SURFACE_TOP = 0.002  # m: the drawn surface sits 2 mm above MuJoCo's floor plane (no z-fighting; the feet hide it)


def log(msg):
    unreal.log(f"[build_track] {msg}")


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


def tint(name, rgb):
    """A material instance of the engine's basic shape material in one colour."""
    path = f"{FOLDER}/{name}"
    mi = ASSETS.load_asset(path) if ASSETS.does_asset_exist(path) else tools.create_asset(
        name, FOLDER, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mi.set_editor_property("parent", unreal.load_asset("/Engine/BasicShapes/BasicShapeMaterial"))
    MEL.set_material_instance_vector_parameter_value(mi, "Color", unreal.LinearColor(*rgb, 1.0))
    ASSETS.save_loaded_asset(mi)
    return mi


track = Track.load(TRACK)

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

if ASSETS.does_asset_exist(BP):   # URLab won't overwrite; the model may have changed
    ASSETS.delete_asset(BP)
track_bp = next(a for a in import_file(f"training/assets/tracks/{TRACK}.xml", FOLDER) if isinstance(a, unreal.Blueprint))
ASSETS.rename_asset(track_bp.get_path_name().split(".")[0], BP)   # URLab names it after the XML
track_bp = ASSETS.load_asset(BP)

sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
lib = unreal.SubobjectDataBlueprintFunctionLibrary
handles = sub.k2_gather_subobject_data_for_blueprint(track_bp)
if not any(isinstance(lib.get_associated_object(lib.get_data(h)), unreal.RacerController) for h in handles):
    p = unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=unreal.RacerController, blueprint_context=track_bp)
    _, fail = sub.add_new_subobject(p)
    log(f"added RacerController ({fail or 'ok'})")
    handles = sub.k2_gather_subobject_data_for_blueprint(track_bp)
for h in handles:
    obj = lib.get_associated_object(lib.get_data(h))
    if isinstance(obj, unreal.RacerController):
        obj.set_editor_property("track_fingerprint", f"training/models/tracks/{TRACK}_fingerprint.json")
        obj.set_editor_property("mode", unreal.RaceControlMode.POLICY)
unreal.BlueprintEditorLibrary.compile_blueprint(track_bp)
ASSETS.save_loaded_asset(track_bp)


def spawn(cls, label, loc=(0, 0, 0), rot=(0, 0, 0)):
    """loc in Unreal cm; rot = (pitch, yaw, roll) degrees."""
    a = eas.spawn_actor_from_class(cls, unreal.Vector(*loc), unreal.Rotator(pitch=rot[0], yaw=rot[1], roll=rot[2]))
    a.set_actor_label(label)
    return a


def ue(x, y, z=0.0):
    """MuJoCo metres (x forward, y left, z up) -> Unreal cm (Y mirrored)."""
    return (x * 100.0, -y * 100.0, z * 100.0)


mgr = spawn(unreal.AMjManager, "MjManager")
engine = mgr.get_component_by_class(unreal.MjPhysicsEngine)
engine.set_editor_property("save_debug_xml", True)
engine.set_editor_property("is_paused", False)
mgr.set_editor_property("auto_create_simulate_widget", False)
spawn(track_bp.generated_class(), "Track")

# ---- the drawn surface: a strip per centre-line segment, cut into ~5 m tiles of two shades
cube = unreal.load_asset("/Engine/BasicShapes/Cube")
mats = {"A": tint("MI_TrackA", (0.20, 0.21, 0.24)), "B": tint("MI_TrackB", (0.26, 0.27, 0.30)),
        "line": tint("MI_Line", (0.95, 0.95, 0.95)), "mark": tint("MI_Marker", (0.95, 0.78, 0.10))}
width = 2.0 * track.half_width + 0.3


def slab(label, x, y, yaw, length, wide, thick, top, mat):
    """A flat box, MuJoCo frame centre (x, y), its top at `top` metres, turned yaw radians."""
    a = spawn(unreal.StaticMeshActor, label, ue(x, y, top - 0.5 * thick), (0, -math.degrees(yaw), 0))
    c = a.static_mesh_component
    c.set_static_mesh(cube)
    c.set_material(0, mat)
    a.set_actor_scale3d(unreal.Vector(length, wide, thick))   # the engine cube is 1 m
    c.set_editor_property("cast_shadow", False)
    a.set_folder_path("TrackSurface")
    return a


tiles = 0
for i in range(track.n):
    a, b = track.P(i), track.P(i + 1)
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.sqrt(dx * dx + dy * dy)
    d = (dx / ln, dy / ln)
    s0, s1 = 0.0, ln
    if not track.closed and i == 0:
        s0 -= OPEN_END
    if not track.closed and i == track.n - 1:
        s1 += OPEN_END
    count = max(1, round((s1 - s0) / 5.0))
    step = (s1 - s0) / count
    for t in range(count):
        mid = s0 + (t + 0.5) * step
        slab(f"tile_{i}_{t}", a[0] + d[0] * mid, a[1] + d[1] * mid, math.atan2(d[1], d[0]), step + 0.01, width, 0.02,
             SURFACE_TOP, mats["A" if (i + t) % 2 == 0 else "B"])
        tiles += 1


def stripe(label, s, along, mat):
    p, t = track.point_at(s)
    slab(label, p[0], p[1], math.atan2(t[1], t[0]), along, width, 0.004, SURFACE_TOP + 0.002, mat)


stripe("start_line", 0.0, 0.32, mats["line"])
if not track.closed:
    stripe("finish_line", track.length, 0.32, mats["line"])
marks = 0
s = track.checkpoint_spacing
while s < track.length - 0.5:
    stripe(f"mark_{s:.0f}", s, 0.30, mats["mark"])
    marks += 1
    s += track.checkpoint_spacing
log(f"{track.name}: {tiles} tiles, {marks} checkpoint marks")

# ---- light and air
sun = spawn(unreal.DirectionalLight, "Sun", rot=(-42, 35, 0))
sun.light_component.set_editor_property("intensity", 7.0)
sun.light_component.set_editor_property("atmosphere_sun_light", True)
spawn(unreal.SkyLight, "SkyLight").light_component.set_editor_property("real_time_capture", True)
spawn(unreal.SkyAtmosphere, "SkyAtmosphere")
spawn(unreal.ExponentialHeightFog, "Fog").component.set_editor_property("fog_density", 0.01)

# ---- director and its chase camera, starting behind the grid
p0, t0 = track.point_at(0.0)
cam = spawn(unreal.CameraActor, "RaceCamera", ue(p0[0] - 4.5 * t0[0], p0[1] - 4.5 * t0[1], 1.8), (-18, -math.degrees(math.atan2(t0[1], t0[0])), 0))
cam.camera_component.set_editor_property("field_of_view", 70.0)
director = spawn(unreal.RaceDirector, "RaceDirector")
director.set_editor_property("camera", cam)

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
