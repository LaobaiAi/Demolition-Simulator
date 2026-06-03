"""
apply_demolition.py - 逻辑驱动拆除动画
扫描场景中所有构件的元数据，按demolition_strategy规则自动排序生成拆除序列。
不再依赖静态CSV，而是通过属性查询和排序实现逻辑控制。

拆除规则:
  1. 按floor排序 (top_down: 3F→2F→1F→基础)
  2. 同层按importance降序 (板3→梁2→柱1)
  3. 同类型同层按bay依次拆除
  4. 每步 frame_per_step 帧，过渡 transition_frames 帧

运行: blender --background output/blend/scene_base.blend --python scripts/apply_demolition.py
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
    with open(os.path.join(DATA_DIR, "project_config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def collect_elements():
    """扫描场景中所有带element_type属性的构件"""
    elements = []
    for obj in bpy.data.objects:
        if "element_type" not in obj:
            continue
        etype = obj["element_type"]
        # 收集元数据
        elem = {
            "obj": obj,
            "name": obj.name,
            "element_type": etype,
            "floor": obj.get("floor", 0),
            "grid_x": obj.get("grid_x", -1),
            "grid_y": obj.get("grid_y", -1),
            "bay_x": obj.get("bay_x", -1),
            "bay_y": obj.get("bay_y", -1),
            "importance": obj.get("importance", 0),
            "label_cn": obj.get("label_cn", ""),
        }
        elements.append(elem)
    return elements


def compute_demolition_order(elements, strategy):
    """根据拆除策略计算拆除顺序"""
    order = strategy["order"]          # top_down | bottom_up
    within_sort = strategy["within_floor_sort"]  # importance_desc | importance_asc

    # 排序key: (floor_rank, importance_rank, bay_x, bay_y, element_type_rank)
    # floor_rank: top_down时楼层越大越先 → -floor; bottom_up时楼层越小越先 → floor
    # importance_rank: importance_desc时importance越大越先 → -importance

    if order == "top_down":
        floor_rank = lambda e: -e["floor"]
    elif order == "bottom_up":
        floor_rank = lambda e: e["floor"]
    else:
        floor_rank = lambda e: -e["floor"]  # 默认top_down

    if within_sort == "importance_asc":
        imp_rank = lambda e: e["importance"]   # 小的先拆(柱→梁→板)
    else:
        imp_rank = lambda e: -e["importance"]  # 大的先拆(板→梁→柱), 默认

    # 类型排序: SLAB→BMX→BMY→COL→FND (同importance时)
    type_order = {"SLAB": 0, "BMX": 1, "BMY": 2, "COL": 3, "FND": 4}

    sorted_elements = sorted(elements, key=lambda e: (
        floor_rank(e),
        imp_rank(e),
        type_order.get(e["element_type"], 9),
        e.get("bay_x", 0) if e.get("bay_x", -1) >= 0 else 0,
        e.get("bay_y", 0) if e.get("bay_y", -1) >= 0 else 0,
        e.get("grid_x", 0) if e.get("grid_x", -1) >= 0 else 0,
        e.get("grid_y", 0) if e.get("grid_y", -1) >= 0 else 0,
    ))
    return sorted_elements


def group_elements(sorted_elements, mode):
    """按模式将构件分组。返回 [(group_label, [elements]), ...]"""
    groups = []
    if mode == "single":
        # 逐个构件
        for e in sorted_elements:
            groups.append((e["name"], [e]))
    elif mode == "by_floor":
        # 按楼层分组 (3F一起, 2F一起, 1F一起, 基础一起)
        by_floor = {}
        for e in sorted_elements:
            f = e["floor"]
            key = f"{f}F" if f > 0 else "基础"
            by_floor.setdefault(key, []).append(e)
        for key in sorted(by_floor, reverse=True):
            groups.append((key, by_floor[key]))
    elif mode == "by_type":
        # 按类型分组 (所有板一起, 所有X梁一起, ...)
        type_order = {"SLAB": 0, "BMX": 1, "BMY": 2, "COL": 3, "FND": 4}
        by_type = {}
        for e in sorted_elements:
            t = e["element_type"]
            labels = {"SLAB": "楼板", "BMX": "X向梁", "BMY": "Y向梁", "COL": "柱", "FND": "基础"}
            key = labels.get(t, t)
            by_type.setdefault(key, []).append(e)
        for key in sorted(by_type, key=lambda k: type_order.get(k, 9)):
            groups.append((key, by_type[key]))
    elif mode == "by_floor_type":
        # 按楼层+类型分组 (3F板, 3F梁X, 3F梁Y, 3F柱, 2F板, ...) —— 默认模式
        type_order = {"SLAB": 0, "BMX": 1, "BMY": 2, "COL": 3, "FND": 4}
        labels = {"SLAB": "楼板", "BMX": "X向梁", "BMY": "Y向梁", "COL": "柱", "FND": "基础"}
        by_ft = {}
        for e in sorted_elements:
            f = e["floor"]
            t = e["element_type"]
            f_label = f"{f}F" if f > 0 else "基础"
            t_label = labels.get(t, t)
            key = (f, t)
            by_ft.setdefault(key, {"label": f"{f_label}{t_label}", "elements": []})
            by_ft[key]["elements"].append(e)
        # 按floor降序, type升序排列
        for key in sorted(by_ft, key=lambda k: (-k[0], type_order.get(k[1], 9))):
            groups.append((by_ft[key]["label"], by_ft[key]["elements"]))
    else:
        # 默认同 by_floor_type
        return group_elements(sorted_elements, "by_floor_type")
    return groups


def assign_frames(sorted_elements, strategy):
    """给排序分组的构件分配动画帧号"""
    mode = strategy.get("demolition_mode", "by_floor_type")
    frame_per_step = strategy.get("frame_per_step", 24)
    overlap = strategy.get("overlap_frames", 4)
    transition = strategy.get("transition_frames", 8)

    groups = group_elements(sorted_elements, mode)

    schedule = []
    current_frame = 0
    for group_label, elements in groups:
        start_frame = current_frame
        end_frame = start_frame + frame_per_step
        for elem in elements:
            schedule.append({
                **elem,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "transition_frames": transition,
                "method": "hide",
                "group_label": group_label,
            })
        current_frame = start_frame + frame_per_step - overlap

    return schedule, groups


def make_material(name, rgba, emission_strength=0.0, emission_color=None):
    """创建材质"""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = rgba
    bsdf.inputs['Roughness'].default_value = 0.5
    if emission_strength > 0 and emission_color:
        bsdf.inputs['Emission Color'].default_value = emission_color
        bsdf.inputs['Emission Strength'].default_value = emission_strength
    out = nodes.new(type='ShaderNodeOutputMaterial')
    mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat


def apply_animation(schedule, config):
    """应用拆除动画关键帧。
    使用 obj.color 变色（SOLID渲染兼容）而非材质替换。
    """
    fps = config["fps"]
    scene = bpy.context.scene
    transition = schedule[0]["transition_frames"] if schedule else 12

    warn_color = (1.0, 0.35, 0.08, 1.0)  # 橙红警示

    for i, item in enumerate(schedule):
        obj = item["obj"]
        start_f = item["start_frame"]
        orig_loc = (obj.location.x, obj.location.y, obj.location.z)
        orig_color = tuple(obj.color) if hasattr(obj, 'color') else (0.8, 0.8, 0.8, 1.0)

        # 重置
        obj.hide_viewport = False
        obj.hide_render = False
        obj.scale = (1.0, 1.0, 1.0)
        obj.location = orig_loc
        obj.color = orig_color

        # 帧0: 锁定全部状态
        scene.frame_set(0)
        obj.keyframe_insert(data_path="hide_viewport", index=-1)
        obj.keyframe_insert(data_path="hide_render", index=-1)
        obj.keyframe_insert(data_path="scale", index=-1)
        obj.keyframe_insert(data_path="location", index=-1)
        obj.keyframe_insert(data_path="color", index=-1)

        # 拆除前: 确认原位
        pre_frame = max(0, start_f - 2)
        if pre_frame > 0:
            scene.frame_set(pre_frame)
            obj.hide_viewport = False
            obj.hide_render = False
            obj.scale = (1.0, 1.0, 1.0)
            obj.location = orig_loc
            obj.color = orig_color
            obj.keyframe_insert(data_path="hide_viewport", index=-1)
            obj.keyframe_insert(data_path="hide_render", index=-1)
            obj.keyframe_insert(data_path="scale", index=-1)
            obj.keyframe_insert(data_path="location", index=-1)
            obj.keyframe_insert(data_path="color", index=-1)

        # 拆除起点: 变橙红
        scene.frame_set(start_f)
        obj.color = warn_color
        obj.keyframe_insert(data_path="color", index=-1)
        obj.keyframe_insert(data_path="scale", index=-1)
        obj.keyframe_insert(data_path="location", index=-1)

        # 过渡中: 剧烈缩小+下坠 (替代颜色变化作为视觉警告)
        mid_frame = start_f + transition // 2
        scene.frame_set(mid_frame)
        obj.scale = (0.3, 0.3, 0.3)
        obj.location = (orig_loc[0], orig_loc[1], orig_loc[2] - 2.0)
        obj.keyframe_insert(data_path="scale", index=-1)
        obj.keyframe_insert(data_path="location", index=-1)

        # 完成: 完全消失
        end_frame = start_f + transition
        scene.frame_set(end_frame)
        obj.hide_viewport = True
        obj.hide_render = True
        obj.scale = (0.01, 0.01, 0.01)
        obj.location = (orig_loc[0], orig_loc[1], orig_loc[2] - 5.0)
        obj.keyframe_insert(data_path="hide_viewport", index=-1)
        obj.keyframe_insert(data_path="hide_render", index=-1)
        obj.keyframe_insert(data_path="scale", index=-1)
        obj.keyframe_insert(data_path="location", index=-1)

        # 插值类型: hide和color用CONSTANT(瞬间切换)
        if obj.animation_data and obj.animation_data.action:
            for fcurve in obj.animation_data.action.fcurves:
                if fcurve.data_path in ("hide_viewport", "hide_render", "color"):
                    for kf in fcurve.keyframe_points:
                        kf.interpolation = 'CONSTANT'

        if i % 30 == 0 and i > 0:
            print(f"    已设置 {i}/{len(schedule)} 个构件动画...")

    # 设置场景帧范围
    last_end = schedule[-1]["end_frame"] + 24 if schedule else 504
    scene.frame_start = 0
    scene.frame_end = last_end
    scene.render.fps = fps

    return last_end


def export_schedule_csv(schedule, strategy):
    """导出计算出的拆除工序为CSV（供参考）"""
    proj_dir = os.path.dirname(BLEND_DIR)
    csv_path = os.path.join(proj_dir, "computed_demolition_schedule.csv")
    with open(csv_path, "w", encoding="utf-8-sig") as f:
        f.write("step,element_id,element_type,floor,grid_x,grid_y,bay_x,bay_y,importance,label_cn,start_frame,end_frame,method\n")
        for i, item in enumerate(schedule):
            f.write(f"{i+1},{item['name']},{item['element_type']},{item['floor']},"
                    f"{item['grid_x']},{item['grid_y']},{item['bay_x']},{item['bay_y']},"
                    f"{item['importance']},{item['label_cn']},"
                    f"{item['start_frame']},{item['end_frame']},{item['method']}\n")
    print(f"  [OK] 拆除工序已导出: {csv_path}")


def print_schedule_summary(schedule, groups):
    """打印工序摘要"""
    mode = "分组批量" if len(groups) < len(schedule) else "逐个构件"
    print(f"\n  拆除模式: {mode} ({len(groups)}组, {len(schedule)}步)")
    print(f"  组序列: ", end="")
    for label, _ in groups[:8]:
        print(f"[{label}]", end=" ")
    if len(groups) > 8:
        print(f"... 共{len(groups)}组")
    else:
        print()
    print(f"  首步: {schedule[0]['name']} ({schedule[0]['label_cn']}) @ frame {schedule[0]['start_frame']}")
    print(f"  末步: {schedule[-1]['name']} ({schedule[-1]['label_cn']}) @ frame {schedule[-1]['start_frame']}")
    print(f"  总帧数: {schedule[-1]['end_frame'] + 24}")


def save_blend():
    path = os.path.join(BLEND_DIR, "scene_animated.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print(f"\n  [OK] 保存: {path}")


# ── 主流程 ──
if __name__ == "__main__":
    print("=" * 60)
    print("  逻辑驱动拆除动画")
    print("=" * 60)

    config = load_config()
    strategy = config["demolition_strategy"]
    fps = config["fps"]

    print(f"  策略: {strategy['order']} | 同层排序: {strategy['within_floor_sort']}")
    imp_map = strategy['importance_map']
    imp_str = ", ".join(f"{k}={v}" for k, v in sorted(imp_map.items(), key=lambda x: -x[1]))
    print(f"  重要性映射: {imp_str}")
    print(f"  帧率: {fps}fps | 每步: {strategy['frame_per_step']}帧 | "
          f"过渡: {strategy['transition_frames']}帧 | 重叠: {strategy['overlap_frames']}帧")

    # 1. 收集所有构件
    elements = collect_elements()
    print(f"\n  扫描到 {len(elements)} 个构件")

    if len(elements) == 0:
        print("  [ERROR] 未找到任何带元数据的构件！")
        print("  请先运行 generate_building.py 生成模型")
        exit(1)

    # 2. 按策略排序
    ordered = compute_demolition_order(elements, strategy)

    # 3. 分组 + 分配帧号
    schedule, groups = assign_frames(ordered, strategy)

    # 4. 打印摘要
    print_schedule_summary(schedule, groups)

    # 5. 应用动画
    print(f"\n  应用动画关键帧...")
    scene = bpy.context.scene
    scene.frame_set(0)
    total_frames = apply_animation(schedule, config)

    # 6. 导出工序CSV
    export_schedule_csv(schedule, strategy)

    # 7. 保存
    save_blend()

    duration = total_frames / fps
    print(f"\n  时长: {duration:.1f}秒 ({total_frames}帧)")
    print("=" * 60)
    print("  拆除动画生成完成!")
    print("=" * 60)
