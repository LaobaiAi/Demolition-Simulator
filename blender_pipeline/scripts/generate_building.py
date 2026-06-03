"""
generate_building.py - 程序化生成钢筋混凝土框架结构
每个构件独立命名，携带完整元数据（类型、楼层、网格位置、所属跨、结构重要性）

命名规则:
  柱: COL_{F}_{gx}_{gy}      F=楼层(3=顶层) gx/gy=柱网线号(0~3)
  X梁: BMX_{F}_{bx}_{gy}     bx=X向跨号(0~2) gy=Y向柱网线号
  Y梁: BMY_{F}_{gx}_{by}     gx=X向柱网线号 by=Y向跨号(0~2)
  板: SLAB_{F}
  基础: FND_{gx}_{gy}

自定义属性(每个构件):
  element_type, floor, grid_x, grid_y, bay_x, bay_y, importance

运行: blender --background --python generate_building.py
"""

import bpy
import json
import os

BLENDER_PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BLENDER_PIPELINE_DIR, "data")
OUTPUT_DIR = os.path.join(BLENDER_PIPELINE_DIR, "output")
BLEND_DIR = os.environ.get("BLENDER_OUTPUT_DIR", os.path.join(OUTPUT_DIR, "blend"))
os.makedirs(BLEND_DIR, exist_ok=True)


def load_config():
    override_path = os.environ.get("BLENDER_CONFIG_OVERRIDE", "")
    if override_path and os.path.exists(override_path):
        with open(override_path, "r", encoding="utf-8") as f:
            return json.load(f)
    with open(os.path.join(DATA_DIR, "project_config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for block in bpy.data.meshes:
        bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        bpy.data.materials.remove(block)


def make_material(name, base_rgb):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (*base_rgb, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.6
    out = nodes.new(type='ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    mat.diffuse_color = (*base_rgb, 1.0)
    return mat


def get_materials():
    return {
        "COL": make_material("Mat_Column",      (0.65, 0.56, 0.48)),
        "BMX": make_material("Mat_BeamX",        (0.62, 0.66, 0.70)),
        "BMY": make_material("Mat_BeamY",        (0.66, 0.70, 0.64)),
        "SLAB": make_material("Mat_Slab",        (0.82, 0.78, 0.72)),
        "FND":  make_material("Mat_Foundation",  (0.50, 0.42, 0.36)),
        "GROUND": make_material("Mat_Ground",    (0.38, 0.44, 0.36)),
    }


def set_element_props(obj, etype, floor, gx, gy, bx, by, importance):
    obj["element_type"] = etype
    obj["floor"] = floor
    obj["grid_x"] = gx
    obj["grid_y"] = gy
    obj["bay_x"] = bx if bx >= 0 else -1
    obj["bay_y"] = by if by >= 0 else -1
    obj["importance"] = importance
    labels = {"COL": "柱", "BMX": "X向梁", "BMY": "Y向梁", "SLAB": "楼板", "FND": "基础"}
    obj["label_cn"] = f"{labels.get(etype, etype)} {floor}F"


def add_cube(name, location, scale, material):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(scale=True)
    if material:
        obj.data.materials.append(material)
        obj.color = material.diffuse_color
    return obj


def build_frame(config):
    bld = config["building"]
    imp = config["demolition_strategy"]["importance_map"]
    mats = get_materials()

    stories = bld["stories"]
    bays_x = bld["bays_x"]
    bays_y = bld["bays_y"]
    bay_wx = bld["bay_width_x"]
    bay_wy = bld["bay_width_y"]
    story_h = bld["story_height"]
    col_sz = bld["column_size"]
    bm_w = bld["beam_width"]
    bm_h = bld["beam_height"]
    slab_t = bld["slab_thickness"]

    grid_x = [i * bay_wx for i in range(bays_x + 1)]
    grid_y = [i * bay_wy for i in range(bays_y + 1)]

    total_wx = bays_x * bay_wx
    total_wy = bays_y * bay_wy

    created_count = {"COL": 0, "BMX": 0, "BMY": 0, "SLAB": 0, "FND": 0}
    all_objects = []

    for f_idx in range(stories):
        floor_num = f_idx + 1
        floor_label = floor_num
        z_bottom = f_idx * story_h
        z_top = z_bottom + story_h

        for ix in range(bays_x + 1):
            for iy in range(bays_y + 1):
                x = grid_x[ix]
                y = grid_y[iy]
                z_center = z_bottom + story_h / 2.0
                name = f"COL_{floor_label}F_{ix}_{iy}"
                obj = add_cube(name, (x, y, z_center),
                               (col_sz, col_sz, story_h),
                               mats["COL"])
                set_element_props(obj, "COL", floor_label, ix, iy, -1, -1, imp["column"])
                all_objects.append(obj)
                created_count["COL"] += 1

        for bx in range(bays_x):
            for iy in range(bays_y + 1):
                x0 = grid_x[bx] + col_sz / 2.0
                x1 = grid_x[bx + 1] - col_sz / 2.0
                length = x1 - x0
                if length <= 0.01:
                    continue
                x_center = (grid_x[bx] + grid_x[bx + 1]) / 2.0
                y = grid_y[iy]
                z = z_top
                name = f"BMX_{floor_label}F_{bx}_{iy}"
                obj = add_cube(name, (x_center, y, z),
                               (length, bm_w, bm_h), mats["BMX"])
                set_element_props(obj, "BMX", floor_label, -1, iy, bx, -1, imp["beam_x"])
                all_objects.append(obj)
                created_count["BMX"] += 1

        for by in range(bays_y):
            for ix in range(bays_x + 1):
                y0 = grid_y[by] + col_sz / 2.0
                y1 = grid_y[by + 1] - col_sz / 2.0
                length = y1 - y0
                if length <= 0.01:
                    continue
                y_center = (grid_y[by] + grid_y[by + 1]) / 2.0
                x = grid_x[ix]
                z = z_top
                name = f"BMY_{floor_label}F_{ix}_{by}"
                obj = add_cube(name, (x, y_center, z),
                               (bm_w, length, bm_h), mats["BMY"])
                set_element_props(obj, "BMY", floor_label, ix, -1, -1, by, imp["beam_y"])
                all_objects.append(obj)
                created_count["BMY"] += 1

        name = f"SLAB_{floor_label}F"
        obj = add_cube(name,
                       (total_wx / 2.0, total_wy / 2.0, z_top - slab_t / 2.0),
                       (total_wx, total_wy, slab_t), mats["SLAB"])
        set_element_props(obj, "SLAB", floor_label, -1, -1, -1, -1, imp["slab"])
        all_objects.append(obj)
        created_count["SLAB"] += 1

    for ix in range(bays_x + 1):
        for iy in range(bays_y + 1):
            x = grid_x[ix]
            y = grid_y[iy]
            name = f"FND_{ix}_{iy}"
            obj = add_cube(name, (x, y, -0.4),
                           (0.8, 0.8, 0.6), mats["FND"])
            set_element_props(obj, "FND", 0, ix, iy, -1, -1, imp["foundation"])
            all_objects.append(obj)
            created_count["FND"] += 1

    bpy.ops.mesh.primitive_plane_add(size=50, location=(total_wx / 2.0, total_wy / 2.0, -0.05))
    ground = bpy.context.active_object
    ground.name = "Ground"
    ground.data.materials.append(mats["GROUND"])

    return created_count, all_objects


def save_blend():
    path = os.path.join(BLEND_DIR, "scene_base.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print(f"  [OK] 保存: {path}")
    return path


if __name__ == "__main__":
    print("=" * 60)
    print("  框架结构生成 - 构件元数据系统")
    print("=" * 60)

    config = load_config()
    bld = config["building"]
    stg = config["demolition_strategy"]
    imp = stg["importance_map"]

    print(f"  层数:{bld['stories']}  跨数:{bld['bays_x']}x{bld['bays_y']}")
    print(f"  柱距:{bld['bay_width_x']}x{bld['bay_width_y']}m  层高:{bld['story_height']}m")
    print(f"  拆除策略: {stg['order']}  同层排序: {stg['within_floor_sort']}")
    print(f"  重要性: 板={imp['slab']} > 梁={imp['beam_x']} > 柱={imp['column']} > 基础={imp['foundation']}")
    print()

    clear_scene()
    counts, all_objs = build_frame(config)

    print(f"  生成构件统计:")
    total = 0
    for k, v in counts.items():
        print(f"    {k}: {v}个")
        total += v
    print(f"    总计: {total}个构件")
    print()

    obj_with_props = sum(1 for o in all_objs if "element_type" in o)
    print(f"  元数据验证: {obj_with_props}/{total} 个构件已设置属性")

    if all_objs:
        sample = all_objs[0]
        print(f"  示例构件: {sample.name}")
        for key in ["element_type", "floor", "grid_x", "grid_y", "bay_x", "bay_y", "importance", "label_cn"]:
            if key in sample:
                print(f"    {key} = {sample[key]}")

    save_blend()
    print("=" * 60)
    print("  模型生成完成!")
    print("=" * 60)
