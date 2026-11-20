"""Grandma: AccuRig (Reallusion CC_Base skeleton) character, normalised into the same rig layout as Matt so the shared
human pipeline (matt_mjcf.py --creature grandma, CreatureBuilder, the Unity Humanoid avatar) runs on her unchanged:

  blender -b --factory-startup -P tools/blender/grandma_rig.py [-- --src GrandmaRiggedUnity.fbx --check <dir>]

Source: GrandmaRiggedUnity.fbx (+ .json AccuRig settings, _ExpressionFrameMap.ini viseme / expression frame map), one
skinned mesh "node_0", 61 weight groups, CC_Base bones, 1.136 m tall in the file, facing -Y, wide A-stance (ankles
27 cm apart), arms near T. The FBX importer puts the bones in a different frame from the bind mesh: bone rest heads map
onto the skin by (x, y, z) -> (x, z, -y) (checked against every bone's skin-weight centroid). This script
  - takes the bind mesh and those bone heads, scales to her height (HEIGHT, 1.58 m: the file's size is arbitrary),
    soles on z = 0, pelvis over the origin, still facing -Y (Unity +Z),
  - builds Matt's 22-bone Mecanim armature (Hips, Spine, Chest, UpperChest, Neck, Head, Shoulder, UpperArm, LowerArm,
    Hand, UpperLeg, LowerLeg, Foot, Toes) on her CC joints and merges her CC weights into it (twist bones into their
    limb, fingers into Hand, toes into Toes, ribs into UpperChest): her own skinning, no bone-heat guess,
  - straightens the stance: each leg swings in about the hip until the ankle is STANCE m outside the hip joint (the
    knee-forward stoop of the side view is kept: it's her posture), arms down 47 deg to Matt's A-pose (52 deg below
    horizontal) so the G1 shoulder ranges mean the same thing on both bodies; baked as the new rest pose,
  - textures: the 4K diffuse / normal -> 2K PNGs.
Outputs: Assets/Art/Raw/grandma.blend (objects "Grandma" + "GrandmaMesh") and Assets/Art/Exports/GLB/Grandma/grandma.fbx
plus Textures/grandma_albedo.png, grandma_normal.png. --check <dir> renders rest / stride / crouch front + side views.
The facial bones and the expression frame map are not carried over yet (the race body has no face rig).
"""

import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(ROOT, "Assets", "Art", "Raw")
EXP = os.path.join(ROOT, "Assets", "Art", "Exports", "GLB", "Grandma")
HEIGHT = 1.58  # m: an average older woman; the source file is 1.136 m (generator scale, not hers)
STANCE = 0.025  # m: ankle joint this far outside the hip joint after straightening (feet ~ hip width)
ARM_DOWN = 47.0  # deg: T-ish source arms (5 deg down) -> Matt's 52 deg A-pose
TEX = 2048

CC = "CC_Base_"
# Mecanim bone -> (CC head bone, CC weight groups merged into it)
MAP = {
    "Hips": ("Hip", ["Hip", "Pelvis"]),
    "Spine": ("Waist", ["Waist"]),
    "Chest": ("Spine01", ["Spine01"]),
    "UpperChest": ("Spine02", ["Spine02", "L_RibsTwist", "R_RibsTwist", "L_Breast", "R_Breast"]),
    "Neck": ("NeckTwist01", ["NeckTwist01", "NeckTwist02"]),
    "Head": (
        "Head",
        [
            "Head",
            "FacialBone",
            "JawRoot",
            "UpperJaw",
            "Teeth01",
            "Teeth02",
            "Tongue01",
            "Tongue02",
            "Tongue03",
            "L_Eye",
            "R_Eye",
        ],
    ),
}
for s, c in (("Left", "L_"), ("Right", "R_")):
    MAP.update(
        {
            s + "Shoulder": (c + "Clavicle", [c + "Clavicle"]),
            s + "UpperArm": (c + "Upperarm", [c + "Upperarm", c + "UpperarmTwist01", c + "UpperarmTwist02"]),
            s + "LowerArm": (
                c + "Forearm",
                [c + "Forearm", c + "ForearmTwist01", c + "ForearmTwist02", c + "ElbowShareBone"],
            ),
            s + "Hand": (
                c + "Hand",
                [c + "Hand"] + [c + f + str(i) for f in ("Thumb", "Index", "Mid", "Ring", "Pinky") for i in (1, 2, 3)],
            ),
            s + "UpperLeg": (c + "Thigh", [c + "Thigh", c + "ThighTwist01", c + "ThighTwist02"]),
            s + "LowerLeg": (c + "Calf", [c + "Calf", c + "CalfTwist01", c + "CalfTwist02", c + "KneeShareBone"]),
            s + "Foot": (c + "Foot", [c + "Foot"]),
            s + "Toes": (
                c + "ToeBase",
                [c + "ToeBase", c + "ToeBaseShareBone"]
                + [c + t + "Toe1" for t in ("Big", "Index", "Mid", "Ring", "Pinky")],
            ),
        }
    )

BONES = [
    ("Hips", "Spine", None),
    ("Spine", "Chest", "Hips"),
    ("Chest", "UpperChest", "Spine"),
    ("UpperChest", "Neck", "Chest"),
    ("Neck", "Head", "UpperChest"),
    ("Head", "HeadTop", "Neck"),
]
for _s in ("Left", "Right"):
    BONES += [
        (_s + "Shoulder", _s + "UpperArm", "UpperChest"),
        (_s + "UpperArm", _s + "LowerArm", _s + "Shoulder"),
        (_s + "LowerArm", _s + "Hand", _s + "UpperArm"),
        (_s + "Hand", _s + "HandTip", _s + "LowerArm"),
        (_s + "UpperLeg", _s + "LowerLeg", "Hips"),
        (_s + "LowerLeg", _s + "Foot", _s + "UpperLeg"),
        (_s + "Foot", _s + "Toes", _s + "LowerLeg"),
        (_s + "Toes", _s + "ToeTip", _s + "Foot"),
    ]


def load(src):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=src)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    src_mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    W = arm.matrix_world
    heads = {b.name: (lambda v: Vector((v.x, v.z, -v.y)))(W @ b.head_local) for b in arm.data.bones}
    verts = [src_mesh.matrix_world @ v.co for v in src_mesh.data.vertices]
    return arm, src_mesh, heads, verts


def build(src_mesh, heads, verts):
    zmin = min(v.z for v in verts)
    zmax = max(v.z for v in verts)
    s = HEIGHT / (zmax - zmin)
    hip = heads[CC + "Hip"]
    origin = Vector((hip.x, hip.y, zmin))
    T = lambda p: (p - origin) * s
    V = [T(v) for v in verts]

    # new mesh: same topology, UVs, materials; vertex positions in the normalised frame, object transform identity
    me = src_mesh.data.copy()
    me.name = "GrandmaMesh"
    ob = bpy.data.objects.new("GrandmaMesh", me)
    bpy.context.scene.collection.objects.link(ob)
    if me.shape_keys:
        ob.shape_key_clear()  # the two AccuRig keys are T-pose bookkeeping; the baked rest pose replaces them
    for v, p in zip(me.vertices, V, strict=False):
        v.co = p

    # merged weight groups (Mecanim names)
    src_groups = {g.index: g.name[len(CC) :] if g.name.startswith(CC) else g.name for g in src_mesh.vertex_groups}
    to = {}
    for mec, (_, cc_list) in MAP.items():
        for c in cc_list:
            to[c] = mec
    ob.vertex_groups.clear()
    gs = {mec: ob.vertex_groups.new(name=mec) for mec in MAP}
    lost = 0
    for v in src_mesh.data.vertices:
        acc = {}
        for g in v.groups:
            mec = to.get(src_groups[g.group])
            if mec is None:
                lost += 1
                continue
            acc[mec] = acc.get(mec, 0.0) + g.weight
        tot = sum(acc.values())
        for mec, w in acc.items():
            gs[mec].add([v.index], w / tot, "REPLACE")

    # joints in the normalised frame, plus tips measured on the skin
    J = {mec: T(heads[CC + cc]) for mec, (cc, _) in MAP.items()}

    def owned(name):
        gi = ob.vertex_groups[name].index
        return [
            ob.data.vertices[i].co.copy()
            for i in range(len(ob.data.vertices))
            if any(g.group == gi and g.weight >= 0.5 for g in ob.data.vertices[i].groups)
        ]

    head_v = owned("Head")
    J["HeadTop"] = Vector((J["Head"].x, J["Head"].y, max(p.z for p in head_v)))
    for side in ("Left", "Right"):
        hv = owned(side + "Hand")
        sgn = 1 if side == "Left" else -1
        J[side + "HandTip"] = max(hv, key=lambda p: sgn * p.x)
        tv = owned(side + "Toes")
        tip = min(tv, key=lambda p: p.y)
        J[side + "ToeTip"] = Vector((tip.x, tip.y, J[side + "Toes"].z))
    return ob, J, s, lost


def armature(J):
    data = bpy.data.armatures.new("GrandmaRig")
    rig = bpy.data.objects.new("Grandma", data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for name, tail, parent in BONES:
        b = data.edit_bones.new(name)
        b.head, b.tail = J[name], J[tail]
        if parent:
            b.parent = data.edit_bones[parent]
            b.use_connect = name not in ("Spine",) and (b.head - b.parent.tail).length < 1e-4
    for b in data.edit_bones:  # consistent rolls: local Z toward the front (-Y) for every bone (as matt_rig.py)
        b.align_roll(Vector((0, -1, 0)) if abs(b.vector.normalized().y) < 0.9 else Vector((0, 0, 1)))
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def rotate_about(pb, axis_world, deg):
    """Rotate a pose bone about a world axis through its head (armature at identity, so world = armature space)."""
    bpy.context.view_layer.update()
    h = pb.head.copy()
    R = Matrix.Translation(h) @ Matrix.Rotation(math.radians(deg), 4, axis_world) @ Matrix.Translation(-h)
    pb.matrix = R @ pb.matrix
    bpy.context.view_layer.update()


def straighten(rig, ob, J):
    """Legs in to a natural stance, arms down to Matt's A-pose; bake into the mesh and make it the rest pose."""
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    ob.parent = rig
    pb = rig.pose.bones
    for side, sgn in (("Left", 1), ("Right", -1)):
        hip, ank = J[side + "UpperLeg"], J[side + "Foot"]
        want = hip.x + sgn * STANCE
        ang = math.degrees(math.atan2(ank.x - hip.x, hip.z - ank.z) - math.atan2(want - hip.x, hip.z - ank.z))
        rotate_about(pb[side + "UpperLeg"], Vector((0, 1, 0)), ang)  # about +Y through the hip: +x side swings in
        rotate_about(pb[side + "UpperArm"], Vector((0, 1, 0)), sgn * ARM_DOWN)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    # feet back on the floor after the swing (the soles rise a little when the legs come in)
    zmin = min(v.co.z for v in ob.data.vertices)
    for v in ob.data.vertices:
        v.co.z -= zmin
    rig.location.z -= zmin
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)


def textures(ob):
    os.makedirs(os.path.join(EXP, "Textures"), exist_ok=True)
    out = {}
    for n in ob.data.materials[0].node_tree.nodes:
        if n.type != "TEX_IMAGE" or n.image is None:
            continue
        img = n.image
        key = "normal" if "ormal" in img.name else "albedo"
        dst = bpy.data.images.new("grandma_" + key, TEX, TEX, alpha=True, is_data=key == "normal")
        img.scale(TEX, TEX)
        px = np.empty(TEX * TEX * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        dst.pixels.foreach_set(px)
        dst.filepath_raw = os.path.join(EXP, "Textures", f"grandma_{key}.png")
        dst.file_format = "PNG"
        dst.save()
        dst.filepath = dst.filepath_raw
        n.image = dst
        out[key] = img.size[:]
    return out


def check(rig, out):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.color_type = "TEXTURE"
    sc.display.shading.light = "STUDIO"
    sc.render.resolution_x = sc.render.resolution_y = 640
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 2.0
    pb = rig.pose.bones
    for b in pb:
        b.rotation_mode = "XYZ"

    def pose(**rot):
        for b in pb:
            b.rotation_euler = (0, 0, 0)
        for k, v in rot.items():
            pb[k].rotation_euler = [math.radians(a) for a in v]
        bpy.context.view_layer.update()

    poses = {
        "rest": {},
        "stride": {
            "LeftUpperLeg": (-35, 0, 0),
            "LeftLowerLeg": (40, 0, 0),
            "RightUpperLeg": (25, 0, 0),
            "RightLowerLeg": (10, 0, 0),
        },
        "crouch": {
            "LeftUpperLeg": (-70, 0, 0),
            "RightUpperLeg": (-70, 0, 0),
            "LeftLowerLeg": (110, 0, 0),
            "RightLowerLeg": (110, 0, 0),
            "LeftFoot": (-40, 0, 0),
            "RightFoot": (-40, 0, 0),
            "Spine": (-25, 0, 0),
        },
    }
    os.makedirs(out, exist_ok=True)
    for name, rot in poses.items():
        pose(**rot)
        for view, (loc, eul) in {"front": ((0, -4, 0.8), (90, 0, 0)), "side": ((4, 0, 0.8), (90, 0, 90))}.items():
            cam.location = loc
            cam.rotation_euler = [math.radians(a) for a in eul]
            sc.render.filepath = os.path.join(out, f"grandma_{name}_{view}.png")
            bpy.ops.render.render(write_still=True)
    pose()


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    src = argv[argv.index("--src") + 1] if "--src" in argv else os.path.join(ROOT, "GrandmaRiggedUnity.fbx")
    check_dir = argv[argv.index("--check") + 1] if "--check" in argv else None
    arm, src_mesh, heads, verts = load(src)
    ob, J, s, lost = build(src_mesh, heads, verts)
    for o in [o for o in bpy.data.objects if o is not ob]:
        bpy.data.objects.remove(o)
    rig = armature(J)
    straighten(rig, ob, J)
    tex = textures(ob)
    for a in list(bpy.data.actions):
        bpy.data.actions.remove(a)
    os.makedirs(EXP, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(RAW, "grandma.blend"))
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    rig.select_set(True)
    bpy.ops.export_scene.fbx(
        filepath=os.path.join(EXP, "grandma.fbx"),
        use_selection=True,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        axis_forward="-Z",
        axis_up="Y",
        object_types={"MESH", "ARMATURE"},
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        mesh_smooth_type="FACE",
        use_armature_deform_only=True,
        bake_anim=False,
        path_mode="STRIP",
    )
    ank = [rig.data.bones[s + "Foot"].head_local for s in ("Left", "Right")]
    print(
        f"[grandma] scale x{s:.3f} -> {HEIGHT} m; {len(ob.data.vertices)} verts, {len(rig.data.bones)} bones, "
        f"{len(ob.vertex_groups)} groups ({lost} unmapped weights); ankles {ank[0].x:+.3f} / {ank[1].x:+.3f} m, "
        f"pelvis z {rig.data.bones['Hips'].head_local.z:.3f}; textures {tex}"
    )
    if check_dir:
        check(rig, check_dir)


main()
