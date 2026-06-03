"""
add_machinery.py - 添加施工机械模型（支持开关控制）
读取 project_config.json 中 machinery.enabled 决定是否添加机械
默认: enabled=false, 不添加机械

运行: blender --background output/blend/scene_animated.blend --python scripts/add_machinery.py
"""

import json
import math
import os

import bpy

from _common import add_cube, add_cylinder, make_material, save_blend, DATA_DIR, BLEND_DIR


def load_config():
    with open(os.path.join(DATA_DIR, "project_config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def join_objects(obj_list, name):
    if not obj_list:
        return None
    if len(obj_list) == 1:
        obj_list[0].name = name
        return obj_list[0]

    bpy.ops.object.select_all(action='DESELECT')
    for obj in obj_list:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = obj_list[0]
    bpy.ops.object.join()
    merged = bpy.context.active_object
    merged.name = name
    return merged


def build_excavator(location, yellow_mat, dark_mat):
    x, y, z = location
    parts = []

    for side in [-1, 1]:
        t = add_cube("", (x, y + side * 2.0, z + 0.4), (4.0, 0.6, 0.6), dark_mat)
        parts.append(t)

    parts.append(add_cube("", (x, y, z + 1.0),   (3.5, 2.5, 0.4), yellow_mat))
    parts.append(add_cube("", (x, y, z + 1.3),   (1.5, 1.5, 0.4), yellow_mat))
    parts.append(add_cube("", (x, y, z + 1.7),   (1.0, 1.0, 0.5), yellow_mat))

    boom = add_cube("", (x + 2.5, y, z + 2.5), (2.5, 0.3, 0.3), yellow_mat)
    boom.rotation_euler = (0, math.radians(45), 0)
    parts.append(boom)

    arm = add_cube("", (x + 4.5, y, z + 5.0), (2.0, 0.25, 0.25), yellow_mat)
    arm.rotation_euler = (0, math.radians(-30), 0)
    parts.append(arm)

    hammer = add_cylinder("", 0.25, 1.5, (x + 5.5, y, z + 3.5), (math.radians(90), 0, 0), dark_mat)
    parts.append(hammer)

    return join_objects(parts, "excavator_01")


def build_truck(location, yellow_mat, dark_mat):
    x, y, z = location
    parts = []

    parts.append(add_cube("", (x, y, z + 0.5),  (2.5, 1.0, 0.3), dark_mat))

    for fx, fy in [(-1.2, -1.2), (-1.2, 1.2), (1.2, -1.2), (1.2, 1.2)]:
        wheel = add_cylinder("", 0.4, 0.2, (x + fx, y + fy, z + 0.4), (0, math.radians(90), 0), dark_mat)
        parts.append(wheel)

    parts.append(add_cube("", (x - 1.8, y, z + 1.0),  (0.8, 0.9, 0.6), yellow_mat))
    parts.append(add_cube("", (x + 1.0, y, z + 1.15), (1.5, 0.95, 0.7), dark_mat))

    return join_objects(parts, "truck_01")


def animate_machinery(excavator, truck, config):
    fps = config["fps"]
    scene = bpy.context.scene

    if excavator:
        excavator.location = (15.0, -5.0, 0.0)
        excavator.keyframe_insert(data_path="location", frame=0, index=-1)

        excavator.location = (12.0, 2.0, 0.0)
        excavator.keyframe_insert(data_path="location", frame=60, index=-1)

        excavator.location = (10.0, 8.0, 0.0)
        excavator.keyframe_insert(data_path="location", frame=200, index=-1)

        excavator.location = (6.0, 12.0, 0.0)
        excavator.keyframe_insert(data_path="location", frame=350, index=-1)

        excavator.location = (8.0, 15.0, 0.0)
        excavator.keyframe_insert(data_path="location", frame=scene.frame_end, index=-1)

    if truck:
        truck.location = (-15.0, -5.0, 0.0)
        truck.keyframe_insert(data_path="location", frame=0, index=-1)

        truck.location = (-10.0, -5.0, 0.0)
        truck.keyframe_insert(data_path="location", frame=100, index=-1)

        truck.location = (-8.0, 5.0, 0.0)
        truck.keyframe_insert(data_path="location", frame=300, index=-1)


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
        save_blend("scene_final.blend")
        print("=" * 60)
        print("  完成 (无机械)")
        print("=" * 60)
        exit(0)

    print("  [INFO] 机械已启用，开始创建...")

    yellow_mat = make_material("MachineryYellow", (0.85, 0.7, 0.1))
    dark_mat  = make_material("MachineryDark",   (0.15, 0.15, 0.15))

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
    save_blend("scene_final.blend")

    print("=" * 60)
    print("  施工机械完成!")
    print("=" * 60)
