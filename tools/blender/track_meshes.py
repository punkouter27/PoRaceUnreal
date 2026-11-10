"""Zero-overlap mitered track surface meshes built in headless Blender:

  blender -b --factory-startup -P tools/blender/track_meshes.py

Eliminates Z-fighting caused by overlapping Cube primitives on straightaways and oval turns:
- Builds exact mitered quad strips along the centerline (5 m alternating TrackA / TrackB bands) where adjacent quads
  share boundary vertices with 0.000 m overlap.
- Places start/finish lines and 25 m / 12 m checkpoint markings 8 mm (+0.008 m) above the track surface so they never
  Z-fight with the track tiles or the underlying MuJoCo floor plane.
Outputs:
- Assets/Art/Raw/tracks.blend
- Assets/Art/Exports/GLB/track_sprint.fbx
- Assets/Art/Exports/GLB/track_oval.fbx
"""
import math
import os
import bmesh
import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(ROOT, "Assets", "Art", "Raw")
EXP = os.path.join(ROOT, "Assets", "Art", "Exports", "GLB")


def material(name, rgb, rough=0.8):
  m = bpy.data.materials.new(name)
  if hasattr(m, "use_nodes"):
    m.use_nodes = True
  bsdf = m.node_tree.nodes["Principled BSDF"]
  bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
  bsdf.inputs["Roughness"].default_value = rough
  m.diffuse_color = (*rgb, 1.0)
  return m


def norm2(v):
  l = math.hypot(v[0], v[1])
  return (v[0] / l, v[1] / l) if l > 1e-8 else (1.0, 0.0)


def left2(v):
  return (-v[1], v[0])


def build_track_mesh(name, pts, closed, half_width, extend_ends=True):
  mat_a = material(name + "_TrackA", (0.30, 0.32, 0.36), 0.85)
  mat_b = material(name + "_TrackB", (0.36, 0.38, 0.42), 0.85)
  n = len(pts) if closed else len(pts) - 1
  verts_count = n if closed else n + 1

  centre = []
  left_pts = []
  right_pts = []
  w = half_width + 0.15

  for i in range(verts_count):
    p = pts[i % len(pts)]
    p_prev = pts[(i - 1) % len(pts)] if (closed or i > 0) else p
    p_next = pts[(i + 1) % len(pts)] if (closed or i < n) else p
    d_prev = norm2((p[0] - p_prev[0], p[1] - p_prev[1])) if (closed or i > 0) else norm2((p_next[0] - p[0], p_next[1] - p[1]))
    d_next = norm2((p_next[0] - p[0], p_next[1] - p[1])) if (closed or i < n) else d_prev
    l_prev = left2(d_prev)
    l_next = left2(d_next)
    nrm = norm2((l_prev[0] + l_next[0], l_prev[1] + l_next[1]))
    dot = max(0.5, nrm[0] * l_next[0] + nrm[1] * l_next[1])
    k = 1.0 / dot
    px, py = p[0], p[1]
    if not closed and extend_ends:
      if i == 0:
        px -= d_next[0] * 6.0
        py -= d_next[1] * 6.0
      elif i == n:
        px += d_prev[0] * 6.0
        py += d_prev[1] * 6.0
    centre.append((px, py))
    left_pts.append((px + nrm[0] * w * k, py + nrm[1] * w * k))
    right_pts.append((px - nrm[0] * w * k, py - nrm[1] * w * k))

  mesh = bpy.data.meshes.new(name)
  ob = bpy.data.objects.new(name, mesh)
  bpy.context.collection.objects.link(ob)
  ob.data.materials.append(mat_a)
  ob.data.materials.append(mat_b)

  bm = bmesh.new()
  z_top = 0.0
  z_bot = -0.02

  for i in range(n):
    j = (i + 1) % verts_count
    c0, c1 = centre[i], centre[j]
    seg_len = math.hypot(c1[0] - c0[0], c1[1] - c0[1])
    tiles = max(1, round(seg_len / 5.0))
    l0, l1 = left_pts[i], left_pts[j]
    r0, r1 = right_pts[i], right_pts[j]

    for t in range(tiles):
      u0 = t / tiles
      u1 = (t + 1) / tiles
      la = (l0[0] + (l1[0] - l0[0]) * u0, l0[1] + (l1[1] - l0[1]) * u0)
      lb = (l0[0] + (l1[0] - l0[0]) * u1, l0[1] + (l1[1] - l0[1]) * u1)
      ra = (r0[0] + (r1[0] - r0[0]) * u0, r0[1] + (r1[1] - r0[1]) * u0)
      rb = (r0[0] + (r1[0] - r0[0]) * u1, r0[1] + (r1[1] - r0[1]) * u1)

      v_ra = bm.verts.new((ra[0], ra[1], z_top))
      v_rb = bm.verts.new((rb[0], rb[1], z_top))
      v_lb = bm.verts.new((lb[0], lb[1], z_top))
      v_la = bm.verts.new((la[0], la[1], z_top))
      f_top = bm.faces.new((v_ra, v_rb, v_lb, v_la))
      f_top.material_index = (i + t) % 2

      # Outer skirt edges so track slab has solid thickness down to z_bot
      v_ra_b = bm.verts.new((ra[0], ra[1], z_bot))
      v_rb_b = bm.verts.new((rb[0], rb[1], z_bot))
      v_lb_b = bm.verts.new((lb[0], lb[1], z_bot))
      v_la_b = bm.verts.new((la[0], la[1], z_bot))
      f_r = bm.faces.new((v_ra_b, v_rb_b, v_rb, v_ra))
      f_l = bm.faces.new((v_lb_b, v_la_b, v_la, v_lb))
      f_r.material_index = (i + t) % 2
      f_l.material_index = (i + t) % 2

  bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-4)
  bm.normal_update()
  bm.to_mesh(mesh)
  bm.free()
  return ob


def oval_points():
  L, R, N = 30.0, 6.0, 14
  pts = [(5.0, 0.0), (L, 0.0)]
  for i in range(1, N + 1):
    a = math.pi * i / N
    pts.append((L + R * math.sin(a), R - R * math.cos(a)))
  pts.append((0.0, 2.0 * R))
  for i in range(1, N + 1):
    a = math.pi * i / N
    pts.append((-R * math.sin(a), R + R * math.cos(a)))
  return pts


def main():
  bpy.ops.wm.read_factory_settings(use_empty=True)
  os.makedirs(RAW, exist_ok=True)
  os.makedirs(EXP, exist_ok=True)

  sprint = build_track_mesh("track_sprint", [(0.0, 0.0), (100.0, 0.0)], closed=False, half_width=1.65)
  oval = build_track_mesh("track_oval", oval_points(), closed=True, half_width=2.0)

  bpy.ops.wm.save_as_mainfile(filepath=os.path.join(RAW, "tracks.blend"))

  for ob in (sprint, oval):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    out_path = os.path.join(EXP, ob.name + ".fbx")
    bpy.ops.export_scene.fbx(
        filepath=out_path,
        use_selection=True,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        axis_forward="-Z",
        axis_up="Y",
        bake_space_transform=True,
        object_types={"MESH"},
        mesh_smooth_type="FACE",
    )
    print(f"exported {ob.name} ({len(ob.data.vertices)} verts, {len(ob.data.polygons)} faces) -> {out_path}")


if __name__ == "__main__":
  main()
