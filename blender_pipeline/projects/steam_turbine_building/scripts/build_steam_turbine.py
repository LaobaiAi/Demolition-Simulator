"""
build_steam_turbine.py - 汽轮机厂房白模建模
规格: 24榀×3轴(A/B/C), AB跨24m钢屋架(脊高27m), BC跨9m平梁, 柱高25m
用法: blender --background --python build_steam_turbine.py
输出: output/blend/scene_base.blend
"""

import bpy
import math
import os
import sys
import json

# ── 路径 ────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output", "blend")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 输出路径也可通过环境变量覆盖
BLEND_OUTPUT = os.environ.get("BLEND_OUTPUT_DIR", OUTPUT_DIR)


def load_config():
    with open(os.path.join(DATA_DIR, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


# ── 工具函数 ────────────────────────────────────────
def box(loc, scale, name="Box"):
    """创建一个立方体"""
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    return obj


def column(x, y, h, s, name):
    """柱子: 底面中心(x,y,0), 高h, 截面s×s"""
    return box((x, y, h / 2), (s, s, h), name)


def beam_h(start, end, bw, bh, name):
    """水平梁: 从start(x,y,z)到end(x,y,z), 宽bw, 高bh"""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    L = math.sqrt(dx * dx + dy * dy)
    if L < 0.001:
        return None
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, start[2] + bh / 2)
    obj = box(mid, (L, bw, bh), name)
    # 绕Z轴旋转到正确方向
    angle = math.atan2(dy, dx)
    obj.rotation_euler.z = angle
    return obj


def slab(cx, cy, cz, sx, sy, t, name):
    """楼板/屋面板: 中心(cx,cy,cz), X半长sx, Y半长sy, 厚t"""
    return box((cx, cy, cz + t / 2), (2 * sx, 2 * sy, t), name)


def sloped_roof(cx, y_start, z_start, y_end, z_end, sx, t, name):
    """坡屋面板: 从(y_start,z_start)到(y_end,z_end), X半长sx, 厚t, 绕X轴旋转"""
    dy = y_end - y_start
    dz = z_end - z_start
    length = math.sqrt(dy * dy + dz * dz)
    angle = math.atan2(dz, dy)               # 绕X轴的旋转角
    mid_y = (y_start + y_end) / 2
    mid_z = (z_start + z_end) / 2
    obj = box((cx, mid_y, mid_z), (2 * sx, length, t), name)
    obj.rotation_euler.x = angle
    return obj


def cylinder(start, end, r, name):
    """圆柱(用于桁架杆件): start→end, 半径r"""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    if L < 0.001:
        return None
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, (start[2] + end[2]) / 2)
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=L, location=mid)
    obj = bpy.context.object
    obj.name = name
    # 指向 end
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


def add_gable_triangle(x, y_a, y_b, z_eave, z_ridge, thickness, name):
    """山墙三角: 底边(y_a,z_eave)→(y_b,z_eave), 顶点(中, ridge), X向厚thickness"""
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
    return obj


# ── 白模材质 ─────────────────────────────────────────
def make_white_material():
    mat = bpy.data.materials.new("WhiteModel")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.92, 0.92, 0.92, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.6
    bsdf.inputs["Specular IOR Level"].default_value = 0.1
    return mat


def assign_material(mat):
    """把材质赋给场景中所有MESH对象"""
    for obj in bpy.data.objects:
        if obj.type == 'MESH' and len(obj.data.materials) == 0:
            obj.data.materials.append(mat)


# ── 场景设置 ─────────────────────────────────────────
def setup_scene(config):
    cfg = config["building"]
    total_len = (cfg["frame_count"] - 1) * cfg["column_spacing"]

    # 清空
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    # 阳光
    bpy.ops.object.light_add(type='SUN', location=(total_len / 2, -30, 40))
    sun = bpy.context.object
    sun.data.energy = 2.5
    sun.data.angle = math.radians(3)

    # 底面 — 大平板，略低于z=0
    ground_size = max(total_len, cfg["bay_ab"] + cfg["bay_bc"]) * 3
    bpy.ops.mesh.primitive_plane_add(size=ground_size, location=(total_len / 2, (cfg["bay_ab"] + cfg["bay_bc"]) / 2, -0.05))
    ground = bpy.context.object
    ground.name = "Ground"
    ground.color = (0.35, 0.28, 0.18, 1.0)  # 深土色

    # 相机 - 从东南方向俯瞰
    cam_x = total_len / 2
    cam_y = -50
    cam_z = 30
    bpy.ops.object.camera_add(location=(cam_x, cam_y, cam_z))
    cam = bpy.context.object
    cam.rotation_euler = (math.radians(60), 0, math.radians(25))
    bpy.context.scene.camera = cam

    # 天空背景 — 天蓝色
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.45, 0.65, 0.90, 1.0)  # 天蓝


# ── 主体建模 ─────────────────────────────────────────
def build(config):
    cfg = config["building"]
    n = cfg["frame_count"]           # 24榀
    sp = cfg["column_spacing"]       # 8m
    ab = cfg["bay_ab"]              # 24m
    bc = cfg["bay_bc"]              # 9m
    ch = cfg["column_height"]       # 25m
    ridge = cfg["roof_ridge_height"]  # 27m
    cs = cfg["column_size"]         # 0.8
    bw = cfg["beam_width"]          # 0.4
    bh = cfg["beam_height"]         # 0.8
    tr = cfg["truss_member_size"]   # 0.15
    st = cfg["slab_thickness"]      # 0.2
    wt = cfg["wall_thickness"]      # 0.2
    bc_floors = cfg.get("bc_floors", [8.0, 15.0])

    # 轴线Y坐标
    ay, by, cy = 0.0, ab, ab + bc            # A=0, B=24, C=33
    total_len = (n - 1) * sp                  # 全长 184m
    xs = [i * sp for i in range(n)]           # 24个X坐标

    print(f"  轴线: A(y={ay})  B(y={by})  C(y={cy})")
    print(f"  全长: {total_len}m, {n}榀 × {sp}m")
    print(f"  柱高: {ch}m, 屋脊: {ridge}m")

    # ── 1. 柱子 ──
    print("  [1/8] 柱子...")
    for i, x in enumerate(xs):
        for axis_name, y in [("A", ay), ("B", by), ("C", cy)]:
            column(x, y, ch, cs, f"Col_{axis_name}{i + 1}")

    # ── 2. 柱顶通长纵梁 (沿X方向, A/B/C三轴) ──
    print("  [2/8] 柱顶通长纵梁...")
    for axis_name, y in [("A", ay), ("B", by), ("C", cy)]:
        for i in range(n - 1):
            x1, x2 = xs[i], xs[i + 1]
            beam_h((x1, y, ch - bh), (x2, y, ch - bh), bw, bh,
                   f"LongBeam_{axis_name}_{i + 1}")

    # ── 3. 每榀: AB跨钢屋架 ──
    print("  [3/8] AB跨钢屋架...")
    ridge_z = ridge
    for i, x in enumerate(xs):
        prefix = f"Truss_{i + 1}"
        # 下弦 (A→B, z=ch=25)
        cylinder((x, ay, ch), (x, by, ch), tr, f"{prefix}_bottom")
        # 上弦左 (A→屋脊)
        cylinder((x, ay, ch), (x, (ay + by) / 2, ridge_z), tr, f"{prefix}_topL")
        # 上弦右 (屋脊→B)
        cylinder((x, (ay + by) / 2, ridge_z), (x, by, ch), tr, f"{prefix}_topR")
        # 竖腹杆 (跨中@屋脊)
        cylinder((x, (ay + by) / 2, ch), (x, (ay + by) / 2, ridge_z), tr,
                 f"{prefix}_vertical")
        # 斜腹杆 (四等分点)
        for q in [1, 3]:
            yq = ay + ab * q / 4
            zq = ch + (ridge_z - ch) * (1 - abs(q - 2) / 2)  # 线性插值到上弦
            # 下弦→上弦
            cylinder((x, yq, ch), (x, yq, zq), tr, f"{prefix}_web{q}")

    # ── 4. 每榀: BC跨平梁 ──
    print("  [4/8] BC跨平梁...")
    for i, x in enumerate(xs):
        beam_h((x, by, ch - bh), (x, cy, ch - bh), bw, bh, f"Beam_BC_{i + 1}")

    # ── 5. BC跨楼板 (8m, 15m 标高, 每区隔) ──
    print("  [5/8] BC跨楼板...")
    for i in range(n - 1):
        cx = (xs[i] + xs[i + 1]) / 2
        cy_bc = (by + cy) / 2
        for fz in bc_floors:
            slab(cx, cy_bc, fz, sp / 2, bc / 2, st,
                 f"Floor_BC_{i + 1}_z{fz:.0f}")

    # ── 6. 屋面板 (每区隔) ──
    print("  [6/8] 屋面板...")
    mid_y = (ay + by) / 2                         # 12m — 屋脊Y
    for i in range(n - 1):
        cx = (xs[i] + xs[i + 1]) / 2

        # AB跨: 双坡屋面 — 南半(A→脊) + 北半(脊→B)
        sloped_roof(cx, ay, ch, mid_y, ridge_z, sp / 2, st,
                    f"Roof_AB_{i + 1}_S")
        sloped_roof(cx, mid_y, ridge_z, by, ch, sp / 2, st,
                    f"Roof_AB_{i + 1}_N")

        # BC跨: 平屋面@25m
        slab(cx, (by + cy) / 2, ch, sp / 2, bc / 2, st,
             f"Roof_BC_{i + 1}")

    # ── 7. 墙板 (每区隔: A轴南面 + C轴北面, z=0~ch) ──
    print("  [7/8] 纵墙板...")
    for i in range(n - 1):
        cx = (xs[i] + xs[i + 1]) / 2
        slab(cx, ay, 0, sp / 2, wt / 2, ch,
             f"Wall_A_{i + 1}")
        slab(cx, cy, 0, sp / 2, wt / 2, ch,
             f"Wall_C_{i + 1}")

    # ── 8. 端部山墙 (x=0 东端 + x=total_len 西端) ──
    print("  [8/8] 端部山墙 + 抗风柱...")
    for end_x, end_name in [(0, "East"), (total_len, "West")]:
        # AB跨矩形墙: A→B, z=0→ch
        slab(end_x, (ay + by) / 2, 0, wt / 2, ab / 2, ch,
             f"Gable_{end_name}_AB_lower")
        # BC跨矩形墙: B→C, z=0→ch
        slab(end_x, (by + cy) / 2, 0, wt / 2, bc / 2, ch,
             f"Gable_{end_name}_BC_lower")
        # AB跨山墙三角: 顶点 (A,ch) / (B,ch) / (脊,ridge)
        add_gable_triangle(end_x, ay, by, ch, ridge_z, wt,
                           f"Gable_{end_name}_AB_tri")
        # 抗风柱: AB跨均匀分布2根, z=0→ridge
        for wi, wy in enumerate([ay + ab / 3, ay + 2 * ab / 3], 1):
            column(end_x, wy, ridge_z, cs,
                   f"WindCol_{end_name}_{wi}")

    print("  建模完成, 赋予材质...")


# ── 构件分色 ─────────────────────────────────────────
TYPE_COLORS = {
    # (R, G, B, A) — 用于 obj.color，饱和醒目
    "Col":      (0.90, 0.55, 0.10, 1.0),   # 橙色 — 柱子
    "LongBeam": (0.15, 0.45, 0.90, 1.0),   # 蓝色 — 纵梁
    "Truss":    (0.92, 0.10, 0.08, 1.0),   # 红色 — 钢屋架
    "Beam_BC":  (0.05, 0.70, 0.72, 1.0),   # 青色 — BC平梁
    "Floor_BC": (0.95, 0.80, 0.05, 1.0),   # 黄色 — 楼板
    "Roof_AB":  (0.55, 0.15, 0.65, 1.0),   # 紫色 — AB屋面板
    "Roof_BC":  (0.12, 0.50, 0.45, 1.0),   # 深青 — BC屋面板
    "Wall":     (0.18, 0.72, 0.28, 1.0),   # 绿色 — 墙板
    "Gable":    (0.72, 0.35, 0.12, 1.0),   # 棕色 — 山墙
    "WindCol":  (0.85, 0.20, 0.65, 1.0),   # 品红 — 抗风柱
}


def assign_type_colors():
    """按构件名称前缀设置 obj.color"""
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        name = obj.name
        matched = False
        for prefix, rgba in TYPE_COLORS.items():
            if name.startswith(prefix):
                obj.color = rgba
                matched = True
                break
        if not matched:
            obj.color = (0.85, 0.85, 0.85, 1.0)  # 默认浅灰

    # 统计
    counts = {}
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        for prefix in TYPE_COLORS:
            if obj.name.startswith(prefix):
                counts[prefix] = counts.get(prefix, 0) + 1
                break
    print("  构件分色:")
    for prefix, n in sorted(counts.items(), key=lambda x: -x[1]):
        rgba = TYPE_COLORS[prefix]
        print(f"    {prefix:12s} ×{n:3d}  RGB({rgba[0]:.2f},{rgba[1]:.2f},{rgba[2]:.2f})")


# ── 主入口 ───────────────────────────────────────────
def main():
    config = load_config()
    print("=" * 60)
    print(f"  汽轮机厂房 - 白模")
    print(f"  {config['description']}")
    print("=" * 60)

    setup_scene(config)
    build(config)

    mat = make_white_material()
    assign_material(mat)

    # 构件类别分色
    assign_type_colors()

    # 保存
    blend_path = os.path.join(BLEND_OUTPUT, "scene_base.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"\n  [OK] 白模已保存: {blend_path}")

    # 统计
    mesh_count = len([o for o in bpy.data.objects if o.type == 'MESH'])
    print(f"  总构件数: {mesh_count}")


if __name__ == "__main__":
    main()
