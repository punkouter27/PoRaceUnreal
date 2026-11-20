"""Batch export (proposal r3 B10): every .blend in Assets/Art/Raw/ becomes one runtime GLB, headless:

  blender --background --factory-startup --python tools/blender/batch_export.py -- \
      [--src Assets/Art/Raw] [--out Assets/Art/Exports/GLB] [--only name.blend] [--dry-run]

Per .blend -> <out>/<stem>.glb (relative paths resolve against the repo root):
  - static meshes: modifiers applied, rotation / scale applied (location stays on an empty named after the object,
    so the prop keeps its pivot), triangulated, then three siblings under that empty: <name>_LOD0 (original),
    <name>_LOD1 (~50 % of the triangles, collapse decimate), <name>_LOD2 (~20 %). The empty gives each prop its
    own LODGroup (Unity groups _LODn siblings under their parent). An authored LOD already in the file
    (<name>_lod1, as trackside_props.py makes) is used in place of the decimated one.
  - skinned meshes (armature modifier / armature parent / shape keys, i.e. Matt): exported as is, LOD0 only, no
    decimation (it breaks skin weights and shape keys); armature, skin, morph targets, actions and materials go in.
    The glTF exporter triangulates them.
  - textures are embedded in the GLB. Image paths that went stale (absolute paths from an older checkout) are
    re-found by file name under Assets/Art/.
The source .blend is opened, changed in memory only and never saved. Prints a summary table; exits 1 if any export
failed. matt_game.blend is Matt's runtime look; matt.blend is the pinned scan the MuJoCo body is fitted to.
"""

import argparse
import glob
import os
import re
import sys
import time
import traceback

import bmesh
import bpy
from mathutils import Matrix

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LODS = (1.0, 0.5, 0.2)
AUTHORED = re.compile(r"^(.*)_lod(\d)$", re.IGNORECASE)


def args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="batch_export.py")
    p.add_argument("--src", default="Assets/Art/Raw")
    p.add_argument("--out", default="Assets/Art/Exports/GLB")
    p.add_argument("--only", default=None, help="one file name, e.g. matt_game.blend")
    p.add_argument("--dry-run", action="store_true", help="open and count, write nothing")
    a = p.parse_args(argv)
    a.src = a.src if os.path.isabs(a.src) else os.path.join(ROOT, a.src)
    a.out = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    return a


def tris(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


def skinned(ob):
    return (
        any(m.type == "ARMATURE" for m in ob.modifiers)
        or (ob.parent and ob.parent.type == "ARMATURE")
        or ob.data.shape_keys is not None
    )


def relink_images():
    """Re-find images whose file is missing by name under Assets/Art (in memory only). Returns names still missing."""
    index = {}
    for f in glob.glob(os.path.join(ROOT, "Assets", "Art", "**", "*.*"), recursive=True):
        index.setdefault(os.path.basename(f).lower(), f)
    missing = []
    for im in bpy.data.images:
        if im.packed_file or im.source not in {"FILE", "TILED"} or not im.filepath:
            continue
        if os.path.isfile(bpy.path.abspath(im.filepath)):
            continue
        hit = index.get(os.path.basename(im.filepath.replace("\\", "/")).lower())
        if hit:
            im.filepath = hit
            im.reload()
        else:
            missing.append(im.name)
    return missing


def baked_mesh(ob, name):
    """Evaluated (modifiers applied) copy of ob's mesh, rotation / scale applied, triangulated."""
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    me.name = name
    _, rot, scale = ob.matrix_world.decompose()
    me.transform(rot.to_matrix().to_4x4() @ Matrix.Diagonal((*scale, 1.0)))
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    return me


def decimated(me, ratio, name):
    tmp = bpy.data.objects.new("_tmp_" + name, me.copy())
    bpy.context.scene.collection.objects.link(tmp)
    mod = tmp.modifiers.new("lod", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = ratio
    mod.use_collapse_triangulate = True
    out = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    out.name = name
    old = tmp.data
    bpy.data.objects.remove(tmp)
    bpy.data.meshes.remove(old)
    return out


def build_lods(scene):
    """Replace every static mesh object in the scene with <name> empty + _LOD0/1/2 children. Returns tris per LOD."""
    counts = [0, 0, 0]
    obs = [o for o in scene.objects if o.type == "MESH"]
    authored = {}
    for o in obs:
        m = AUTHORED.match(o.name)
        if m and int(m.group(2)) > 0:
            authored[(m.group(1), int(m.group(2)))] = o
    for ob in obs:
        if skinned(ob):
            continue
        if any(ob is a for a in authored.values()):
            continue
        base = ob.name
        meshes = [baked_mesh(ob, base + "_LOD0")]
        for i, ratio in enumerate(LODS[1:], start=1):
            src = authored.get((base, i))
            meshes.append(baked_mesh(src, f"{base}_LOD{i}") if src else decimated(meshes[0], ratio, f"{base}_LOD{i}"))
        loc = ob.matrix_world.to_translation()
        colls = list(ob.users_collection)
        ob.name = base + "__src"
        root = bpy.data.objects.new(base, None)
        root.matrix_world = Matrix.Translation(loc)
        for c in colls:
            c.objects.link(root)
        for i, me in enumerate(meshes):
            child = bpy.data.objects.new(me.name, me)
            for c in colls:
                c.objects.link(child)
            child.parent = root
            counts[i] += tris(me)
        bpy.data.objects.remove(ob)
    for o in authored.values():
        if o.name in bpy.data.objects:
            bpy.data.objects.remove(o)
    return counts


def skinned_tris(scene):
    n = 0
    for o in scene.objects:
        if o.type == "MESH" and skinned(o):
            o.data.calc_loop_triangles()
            n += len(o.data.loop_triangles)
    return n


def export_one(path, out_dir, dry):
    t0 = time.time()
    bpy.ops.wm.open_mainfile(filepath=path, load_ui=False)
    scene = bpy.context.scene
    missing = relink_images()
    counts = build_lods(scene)
    sk = skinned_tris(scene)
    counts[0] += sk  # skinned meshes: LOD0 only
    out = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0] + ".glb")
    has_armature = any(o.type == "ARMATURE" for o in scene.objects)
    if not dry:
        os.makedirs(out_dir, exist_ok=True)
        bpy.ops.export_scene.gltf(
            filepath=out,
            export_format="GLB",
            use_selection=False,
            use_visible=False,
            use_renderable=True,
            export_apply=False,
            export_yup=True,
            export_texcoords=True,
            export_normals=True,
            export_tangents=True,
            export_materials="EXPORT",
            export_image_format="AUTO",
            export_skins=has_armature,
            export_morph=True,
            export_animations=has_armature,
            export_def_bones=False,
            export_cameras=False,
            export_lights=False,
            export_extras=False,
        )
    n_obj = sum(1 for o in scene.objects if o.type in {"MESH", "ARMATURE"})
    size = os.path.getsize(out) / 1e6 if (not dry and os.path.isfile(out)) else 0.0
    return dict(
        objects=n_obj,
        tris=counts,
        out=os.path.relpath(out, ROOT),
        mb=size,
        s=time.time() - t0,
        missing=missing,
        skinned=sk > 0,
    )


def main():
    a = args()
    files = sorted(glob.glob(os.path.join(a.src, "*.blend")))
    if a.only:
        files = [f for f in files if os.path.basename(f).lower() == a.only.lower()]
        if not files:
            print(f"batch_export: {a.only} not found in {a.src}")
            sys.exit(1)
    rows, failed = [], []
    for f in files:
        name = os.path.basename(f)
        print(f"batch_export: {name} ...", flush=True)
        try:
            rows.append((name, export_one(f, a.out, a.dry_run)))
        except Exception:
            traceback.print_exc()
            failed.append(name)
    print()
    print(f"{'file':<22}{'objs':>5}{'tris LOD0':>11}{'LOD1':>8}{'LOD2':>8}  {'output':<40}{'MB':>7}{'s':>7}")
    for name, r in rows:
        l0, l1, l2 = r["tris"]
        lods = ("-", "-") if r["skinned"] and not (l1 or l2) else (l1, l2)
        print(
            f"{name:<22}{r['objects']:>5}{l0:>11}{lods[0]:>8}{lods[1]:>8}  {r['out'].replace(os.sep, '/'):<40}"
            f"{r['mb']:>7.2f}{r['s']:>7.1f}"
        )
        if r["missing"]:
            print(f"  missing images: {', '.join(r['missing'])}")
        if r["mb"] > 50:
            print(f"  WARNING: {r['mb']:.1f} MB, consider downscaling textures")
    for name in failed:
        print(f"{name:<22}  FAILED")
    if a.dry_run:
        print("(dry run: nothing written)")
    sys.exit(1 if failed else 0)


main()
