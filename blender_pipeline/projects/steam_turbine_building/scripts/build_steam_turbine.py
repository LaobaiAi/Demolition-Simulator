"""
build_steam_turbine.py - 汽轮机厂房白模建模
规格: 24榀×3轴(A/B/C), AB跨24m钢屋架(脊高27m), BC跨9m平梁, 柱高25m
用法: blender --background --python build_steam_turbine.py
输出: output/blend/scene_base.blend
"""

import math
import os
import sys
import json

import bpy

_PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS_DIR = os.path.join(_PIPELINE_DIR, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _common import add_cube, add_cylinder, make_material, clear_scene, compute_scene_bounds

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output", "blend")
os.makedirs(OUTPUT_DIR, exist_ok=True)

BLEND_OUTPUT = os.environ.get("BLEND_OUTPUT_DIR", OUTPUT_DIR)


def load_config():
    with open(os.path.join(DATA_DIR, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def column(x, y, h, s, name, mat):
    return add_cube(name, (x, y, h / 2), (s, s, h), mat)


def beam_h(start, end, bw, bh, name, mat):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    L = math.sqrt(dx * dx + dy * dy)
    if L < 0.001:
        return None
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, start[2] + bh / 2)
    obj = add_cube(name, mid, (L, bw, bh), mat)
    obj.rotation_euler.z = math.atan2(dy, dx)
    return obj


def slab(cx, cy, cz, sx, sy, t, name, mat):
    return add_cube(name, (cx, cy, cz + t / 2), (2 * sx, 2 * sy, t), mat)


def sloped_roof(cx, y_start, z_start, y_end, z_end, sx, t, name, mat):
    dy = y_end - y_start
    dz = z_end - z_start
    length = math.sqrt(dy * dy + dz * dz)
    angle = math.atan2(dz, dy)
    mid_y = (y_start + y_end) / 2
    mid_z = (z_start + z_end) / 2
    obj = add_cube(name, (cx, mid_y, mid_z), (2 * sx, length, t), mat)
    obj.rotation_euler.x = angle
    return obj


def truss_member(start, end, r, name, mat):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    if L < 0.001:
        return None
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, (start[2] + end[2]) / 2)
    obj = add_cylinder(name, r, L, mid, (0, 0, 0), mat)
    dir_vec = (dx / L, dy / L, dz / L)
    z_axis = (0, 0, 1)
    angle = math.acos(dir_vec[2])
    if angle > 0.001:
        axis = (-dir_vec[1], dir_vec[0], 0)
        axis_len = math.sqrt(axis[0] ** 2 + axis[1] ** 2)
        if axis_len > 0.001:
            axis = (axis[0] / axis_len, axis[1] / axis_len, 0)
        obj.rotation_mode = 'AXIS_ANGLE'
        obj.rotation_axis_angle = (angle, axis[0], axis[1], axis[2])
    return obj


def add_gable_triangle(x, y_a, y_b, z_eave, z_ridge, thickness, name, mat):
    from mathutils import Vector
    mid_y = (y_a + y_b) / 2
    verts = [
        Vector((0, y_a, z_eave)),
        Vector((0, y_b, z_eave)),
        Vector((0, mid_y, z_ridge)),
    ]
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    center = sum(verts, Vector((0, 0, 0))) / 3
    mesh.from_pydata([v - center for v in verts], [], [(0, 1, 2)])
    mesh.update()
    obj.location = (x, center.y, center.z)
    obj.scale.x = thickness / 2
    if mat:
        obj.data.materials.append(mat)
    return obj


TYPE_COLORS = {
    "Col":      (0.90, 0.55, 0.10, 1.0),
    "LongBeam": (0.15, 0.45, 0.90, 1.0),
    "Truss":    (0.92, 0.10, 0.08, 1.0),
    "Beam_BC":  (0.05, 0.70, 0.72, 1.0),
    "Floor_BC": (0.95, 0.80, 0.05, 1.0),
    "Roof_AB":  (0.55, 0.15, 0.65, 1.0),
    "Roof_BC":  (0.12, 0.50, 0.45, 1.0),
    "Wall":     (0.18, 0.72, 0.28, 1.0),
    "Gable":    (0.72, 0.35, 0.12, 1.0),
    "WindCol":  (0.85, 0.20, 0.65, 1.0),
}


def setup_scene(config, ground_mat):
    cfg = config["building"]
    total_len = (cfg["frame_count"] - 1) * cfg["column_spacing"]

    clear_scene()

    bpy.ops.object.light_add(type='SUN', location=(total_len / 2, -30, 40))
    sun = bpy.context.object
    sun.data.energy = 2.5
    sun.data.angle = math.radians(3)

    ground_size = max(total_len, cfg["bay_ab"] + cfg["bay_bc"]) * 3
    ground = add_cube("Ground",
                      (total_len / 2, (cfg["bay_ab"] + cfg["bay_bc"]) / 2, -0.05),
                      (ground_size, ground_size, 0.1),
                      ground_mat)
    ground.color = (0.35, 0.28, 0.18, 1.0)

    cam_x = total_len / 2
    cam_y = -50
    cam_z = 30
    bpy.ops.object.camera_add(location=(cam_x, cam_y, cam_z))
    cam = bpy.context.object
    cam.rotation_euler = (math.radians(60), 0, math.radians(25))
    bpy.context.scene.camera = cam

    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.45, 0.65, 0.90, 1.0)


def build(config, mat):
    cfg = config["building"]
    n = cfg["frame_count"]
    sp = cfg["column_spacing"]
    ab = cfg["bay_ab"]
    bc = cfg["bay_bc"]
    ch = cfg["column_height"]
    ridge = cfg["roof_ridge_height"]
    cs = cfg["column_size"]
    bw = cfg["beam_width"]
    bh = cfg["beam_height"]
    tr = cfg["truss_member_size"]
    st = cfg["slab_thickness"]
    wt = cfg["wall_thickness"]
    bc_floors = cfg.get("bc_floors", [8.0, 15.0])

    ay, by, cy = 0.0, ab, ab + bc
    total_len = (n - 1) * sp
    xs = [i * sp for i in range(n)]

    print(f"  轴线: A(y={ay})  B(y={by})  C(y={cy})")
    print(f"  全长: {total_len}m, {n}榀 × {sp}m")
    print(f"  柱高: {ch}m, 屋脊: {ridge}m")

    print("  [1/8] 柱子...")
    for i, x in enumerate(xs):
        for axis_name, y in [("A", ay), ("B", by), ("C", cy)]:
            column(x, y, ch, cs, f"Col_{axis_name}{i + 1}", mat)

    print("  [2/8] 柱顶通长纵梁...")
    for axis_name, y in [("A", ay), ("B", by), ("C", cy)]:
        for i in range(n - 1):
            x1, x2 = xs[i], xs[i + 1]
            beam_h((x1, y, ch - bh), (x2, y, ch - bh), bw, bh,
                   f"LongBeam_{axis_name}_{i + 1}", mat)

    print("  [3/8] AB跨钢屋架...")
    ridge_z = ridge
    for i, x in enumerate(xs):
        prefix = f"Truss_{i + 1}"
        truss_member((x, ay, ch), (x, by, ch), tr, f"{prefix}_bottom", mat)
        truss_member((x, ay, ch), (x, (ay + by) / 2, ridge_z), tr, f"{prefix}_topL", mat)
        truss_member((x, (ay + by) / 2, ridge_z), (x, by, ch), tr, f"{prefix}_topR", mat)
        truss_member((x, (ay + by) / 2, ch), (x, (ay + by) / 2, ridge_z), tr,
                     f"{prefix}_vertical", mat)
        for q in [1, 3]:
            yq = ay + ab * q / 4
            zq = ch + (ridge_z - ch) * (1 - abs(q - 2) / 2)
            truss_member((x, yq, ch), (x, yq, zq), tr, f"{prefix}_web{q}", mat)

    print("  [4/8] BC跨平梁...")
    for i, x in enumerate(xs):
        beam_h((x, by, ch - bh), (x, cy, ch - bh), bw, bh, f"Beam_BC_{i + 1}", mat)

    print("  [5/8] BC跨楼板...")
    for i in range(n - 1):
        cx = (xs[i] + xs[i + 1]) / 2
        cy_bc = (by + cy) / 2
        for fz in bc_floors:
            slab(cx, cy_bc, fz, sp / 2, bc / 2, st,
                 f"Floor_BC_{i + 1}_z{fz:.0f}", mat)

    print("  [6/8] 屋面板...")
    mid_y = (ay + by) / 2
    for i in range(n - 1):
        cx = (xs[i] + xs[i + 1]) / 2
        sloped_roof(cx, ay, ch, mid_y, ridge_z, sp / 2, st,
                    f"Roof_AB_{i + 1}_S", mat)
        sloped_roof(cx, mid_y, ridge_z, by, ch, sp / 2, st,
                    f"Roof_AB_{i + 1}_N", mat)
        slab(cx, (by + cy) / 2, ch, sp / 2, bc / 2, st,
             f"Roof_BC_{i + 1}", mat)

    print("  [7/8] 纵墙板...")
    for i in range(n - 1):
        cx = (xs[i] + xs[i + 1]) / 2
        slab(cx, ay, 0, sp / 2, wt / 2, ch, f"Wall_A_{i + 1}", mat)
        slab(cx, cy, 0, sp / 2, wt / 2, ch, f"Wall_C_{i + 1}", mat)

    print("  [8/8] 端部山墙 + 抗风柱...")
    for end_x, end_name in [(0, "East"), (total_len, "West")]:
        slab(end_x, (ay + by) / 2, 0, wt / 2, ab / 2, ch,
             f"Gable_{end_name}_AB_lower", mat)
        slab(end_x, (by + cy) / 2, 0, wt / 2, bc / 2, ch,
             f"Gable_{end_name}_BC_lower", mat)
        add_gable_triangle(end_x, ay, by, ch, ridge_z, wt,
                           f"Gable_{end_name}_AB_tri", mat)
        for wi, wy in enumerate([ay + ab / 3, ay + 2 * ab / 3], 1):
            column(end_x, wy, ridge_z, cs, f"WindCol_{end_name}_{wi}", mat)

    print("  建模完成, 赋予颜色...")


def assign_type_colors():
    counts = {}
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        name = obj.name
        matched = False
        for prefix, rgba in TYPE_COLORS.items():
            if name.startswith(prefix):
                obj.color = rgba
                counts[prefix] = counts.get(prefix, 0) + 1
                matched = True
                break
        if not matched:
            obj.color = (0.85, 0.85, 0.85, 1.0)

    print("  构件分色:")
    for prefix, n in sorted(counts.items(), key=lambda x: -x[1]):
        rgba = TYPE_COLORS[prefix]
        print(f"    {prefix:12s} ×{n:3d}  RGB({rgba[0]:.2f},{rgba[1]:.2f},{rgba[2]:.2f})")


def main():
    config = load_config()
    print("=" * 60)
    print(f"  汽轮机厂房 - 白模")
    print(f"  {config['description']}")
    print("=" * 60)

    white_mat = make_material("WhiteModel", (0.92, 0.92, 0.92), roughness=0.6)
    ground_mat = make_material("Ground", (0.35, 0.28, 0.18), roughness=0.8)

    setup_scene(config, ground_mat)
    build(config, white_mat)

    assign_type_colors()

    blend_path = os.path.join(BLEND_OUTPUT, "scene_base.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"\n  [OK] 白模已保存: {blend_path}")

    mesh_count = len([o for o in bpy.data.objects if o.type == 'MESH'])
    print(f"  总构件数: {mesh_count}")


if __name__ == "__main__":
    main()
