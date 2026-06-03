"""
add_machinery.py - 添加施工机械模型（支持开关控制）
读取 project_config.json 中 machinery.enabled 决定是否添加机械
默认: enabled=false, 不添加机械

运行: blender --background output/blend/scene_animated.blend --python scripts/add_machinery.py
"""

import bpy
import json
import os
import math

BLENDER_PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BLENDER_PIPELINE_DIR, "data")
OUTPUT_DIR = os.path.join(BLENDER_PIPELINE_DIR, "output")
BLEND_DIR = os.environ.get("BLENDER_OUTPUT_DIR", os.path.join(OUTPUT_DIR, "blend"))
os.makedirs(BLEND_DIR, exist_ok=True)


def load_config():
    with open(os.path.join(DATA_DIR, "project_config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def make_material(name, rgba):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = rgba
    bsdf.inputs['Roughness'].default_value = 0.5
    out = nodes.new(type='ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat


def join_objects(obj_list, name):
    if not obj_list:
        return None
    bpy.ops.object.select_all(action='DESELECT')
    for obj in obj_list:
        obj.select_set(True)
    if len(obj_list) >= 1:
        bpy.context.view_layer.objects.active = obj_list[0]
    if len(obj_list) > 1:
        bpy.ops.object.join()
    merged = bpy.context.active_object
    merged.name = name
    return merged


def build_excavator(location, yellow_mat, dark_mat):
    """几何体搭建挖掘机"""
    x, y, z = location
    parts = []

    # 履带
    for side in [-1, 1]:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y + side * 2.0, z + 0.4))
        t = bpy.context.active_object
        t.scale = (4.0, 0.6, 0.6)
        bpy.ops.object.transform_apply(scale=True)
        t.data.materials.append(dark_mat)
        parts.append(t)

    # 底盘
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z + 1.0))
    chassis = bpy.context.active_object
    chassis.scale = (3.5, 2.5, 0.4)
    bpy.ops.object.transform_apply(scale=True)
    chassis.data.materials.append(yellow_mat)
    parts.append(chassis)

    # 机身
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z + 1.3))
    body = bpy.context.active_object
    body.scale = (1.5, 1.5, 0.4)
    bpy.ops.object.transform_apply(scale=True)
    body.data.materials.append(yellow_mat)
    parts.append(body)

    # 驾驶室
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z + 1.7))
    cab = bpy.context.active_object
    cab.scale = (1.0, 1.0, 0.5)
    bpy.ops.object.transform_apply(scale=True)
    cab.data.materials.append(yellow_mat)
    parts.append(cab)

    # 动臂
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x + 2.5, y, z + 2.5))
    boom = bpy.context.active_object
    boom.scale = (2.5, 0.3, 0.3)
    boom.rotation_euler = (0, math.radians(45), 0)
    bpy.ops.object.transform_apply(scale=True)
    boom.data.materials.append(yellow_mat)
    parts.append(boom)

    # 斗杆
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x + 4.5, y, z + 5.0))
    arm = bpy.context.active_object
    arm.scale = (2.0, 0.25, 0.25)
    arm.rotation_euler = (0, math.radians(-30), 0)
    bpy.ops.object.transform_apply(scale=True)
    arm.data.materials.append(yellow_mat)
    parts.append(arm)

    # 破碎锤
    bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=1.5,
                                         location=(x + 5.5, y, z + 3.5),
                                         rotation=(math.radians(90), 0, 0))
    hammer = bpy.context.active_object
    hammer.data.materials.append(dark_mat)
    parts.append(hammer)

    return join_objects(parts, "excavator_01")


def build_truck(location, yellow_mat, dark_mat):
    """几何体搭建渣土车"""
    x, y, z = location
    parts = []

    # 底盘
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z + 0.5))
    chassis = bpy.context.active_object
    chassis.scale = (2.5, 1.0, 0.3)
    bpy.ops.object.transform_apply(scale=True)
    chassis.data.materials.append(dark_mat)
    parts.append(chassis)

    # 车轮
    for fx, fy in [(-1.2, -1.2), (-1.2, 1.2), (1.2, -1.2), (1.2, 1.2)]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.4, depth=0.2,
                                             location=(x + fx, y + fy, z + 0.4),
                                             rotation=(0, math.radians(90), 0))
        wheel = bpy.context.active_object
        wheel.data.materials.append(dark_mat)
        parts.append(wheel)

    # 驾驶室
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x - 1.8, y, z + 1.0))
    cab = bpy.context.active_object
    cab.scale = (0.8, 0.9, 0.6)
    bpy.ops.object.transform_apply(scale=True)
    cab.data.materials.append(yellow_mat)
    parts.append(cab)

    # 车厢
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x + 1.0, y, z + 1.15))
    bed = bpy.context.active_object
    bed.scale = (1.5, 0.95, 0.7)
    bpy.ops.object.transform_apply(scale=True)
    bed.data.materials.append(dark_mat)
    parts.append(bed)

    return join_objects(parts, "truck_01")


def animate_machinery(excavator, truck, config):
    """设置机械运动动画"""
    fps = config["fps"]
    scene = bpy.context.scene

    if excavator:
        bpy.context.scene.frame_set(0)
        excavator.location = (15.0, -5.0, 0.0)
        excavator.keyframe_insert(data_path="location", index=-1)

        bpy.context.scene.frame_set(60)
        excavator.location = (12.0, 2.0, 0.0)
        excavator.keyframe_insert(data_path="location", index=-1)

        bpy.context.scene.frame_set(200)
        excavator.location = (10.0, 8.0, 0.0)
        excavator.keyframe_insert(data_path="location", index=-1)

        bpy.context.scene.frame_set(350)
        excavator.location = (6.0, 12.0, 0.0)
        excavator.keyframe_insert(data_path="location", index=-1)

        bpy.context.scene.frame_set(scene.frame_end)
        excavator.location = (8.0, 15.0, 0.0)
        excavator.keyframe_insert(data_path="location", index=-1)

    if truck:
        bpy.context.scene.frame_set(0)
        truck.location = (-15.0, -5.0, 0.0)
        truck.keyframe_insert(data_path="location", index=-1)

        bpy.context.scene.frame_set(100)
        truck.location = (-10.0, -5.0, 0.0)
        truck.keyframe_insert(data_path="location", index=-1)

        bpy.context.scene.frame_set(300)
        truck.location = (-8.0, 5.0, 0.0)
        truck.keyframe_insert(data_path="location", index=-1)


def save_blend():
    path = os.path.join(BLEND_DIR, "scene_final.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print(f"  [OK] 保存: {path}")


# ── 主流程 ──
if __name__ == "__main__":
    print("=" * 60)
    print("  施工机械脚本")
    print("=" * 60)

    config = load_config()
    machinery_config = config.get("machinery", {})
    enabled = machinery_config.get("enabled", False)

    if not enabled:
        print("  [INFO] 机械已禁用 (machinery.enabled=false)")
        print("  直接保存场景...")
        save_blend()
        print("=" * 60)
        print("  完成 (无机械)")
        print("=" * 60)
        exit(0)

    print("  [INFO] 机械已启用，开始创建...")

    yellow_mat = make_material("MachineryYellow", (0.85, 0.7, 0.1, 1.0))
    dark_mat = make_material("MachineryDark", (0.15, 0.15, 0.15, 1.0))

    machines = machinery_config.get("items", [])
    excavator = None
    truck = None

    for m in machines:
        mtype = m.get("type", "")
        loc = m.get("location", [0, 0, 0])
        print(f"  创建: {mtype} 位置: {loc}")
        if "挖掘" in mtype:
            excavator = build_excavator(loc, yellow_mat, dark_mat)
        elif "运输" in mtype or "渣土" in mtype:
            truck = build_truck(loc, yellow_mat, dark_mat)

    animate_machinery(excavator, truck, config)
    save_blend()

    print("=" * 60)
    print("  施工机械完成!")
    print("=" * 60)
