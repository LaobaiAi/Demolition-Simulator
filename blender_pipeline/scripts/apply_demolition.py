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

import json
import os

import bpy

from _common import DATA_DIR, BLEND_DIR


def load_config():
    with open(os.path.join(DATA_DIR, "project_config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def collect_elements():
    elements = []
    for obj in bpy.data.objects:
        if "element_type" not in obj:
            continue
        elem = {
            "obj": obj,
            "name": obj.name,
            "element_type": obj["element_type"],
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
    order = strategy["order"]
    within_sort = strategy["within_floor_sort"]

    if order == "top_down":
        floor_rank = lambda e: -e["floor"]
    elif order == "bottom_up":
        floor_rank = lambda e: e["floor"]
    else:
        floor_rank = lambda e: -e["floor"]

    if within_sort == "importance_asc":
        imp_rank = lambda e: e["importance"]
    else:
        imp_rank = lambda e: -e["importance"]

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
    groups = []
    if mode == "single":
        for e in sorted_elements:
            groups.append((e["name"], [e]))
    elif mode == "by_floor":
        by_floor = {}
        for e in sorted_elements:
            f = e["floor"]
            key = f"{f}F" if f > 0 else "基础"
            by_floor.setdefault(key, []).append(e)
        for key in sorted(by_floor, reverse=True):
            groups.append((key, by_floor[key]))
    elif mode == "by_type":
        type_order = {"SLAB": 0, "BMX": 1, "BMY": 2, "COL": 3, "FND": 4}
        by_type = {}
        for e in sorted_elements:
            t = e["element_type"]
            labels = {"SLAB": "楼板", "BMX": "X向梁", "BMY": "Y向梁", "COL": "柱", "FND": "基础"}
            by_type.setdefault(labels.get(t, t), []).append(e)
        for key in sorted(by_type, key=lambda k: type_order.get(k, 9)):
            groups.append((key, by_type[key]))
    elif mode == "by_floor_type":
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
        for key in sorted(by_ft, key=lambda k: (-k[0], type_order.get(k[1], 9))):
            groups.append((by_ft[key]["label"], by_ft[key]["elements"]))
    else:
        return group_elements(sorted_elements, "by_floor_type")
    return groups


def assign_frames(sorted_elements, strategy):
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


def apply_animation(schedule, config):
    """Apply demolition animation keyframes using direct frame= parameter.

    No scene.frame_set() calls — avoids 695 depsgraph evaluations.
    """
    fps = config["fps"]
    scene = bpy.context.scene
    transition = schedule[0]["transition_frames"] if schedule else 12
    warn_color = (1.0, 0.35, 0.08, 1.0)

    for i, item in enumerate(schedule):
        obj = item["obj"]
        start_f = item["start_frame"]
        orig_loc = (obj.location.x, obj.location.y, obj.location.z)
        orig_color = tuple(obj.color) if hasattr(obj, 'color') else (0.8, 0.8, 0.8, 1.0)

        obj.hide_viewport = False
        obj.hide_render = False
        obj.scale = (1.0, 1.0, 1.0)
        obj.location = orig_loc
        obj.color = orig_color

        obj.keyframe_insert(data_path="hide_viewport", frame=0, index=-1)
        obj.keyframe_insert(data_path="hide_render",   frame=0, index=-1)
        obj.keyframe_insert(data_path="scale",         frame=0, index=-1)
        obj.keyframe_insert(data_path="location",      frame=0, index=-1)
        obj.keyframe_insert(data_path="color",         frame=0, index=-1)

        pre_frame = max(0, start_f - 2)
        if pre_frame > 0:
            obj.hide_viewport = False
            obj.hide_render = False
            obj.scale = (1.0, 1.0, 1.0)
            obj.location = orig_loc
            obj.color = orig_color
            obj.keyframe_insert(data_path="hide_viewport", frame=pre_frame, index=-1)
            obj.keyframe_insert(data_path="hide_render",   frame=pre_frame, index=-1)
            obj.keyframe_insert(data_path="scale",         frame=pre_frame, index=-1)
            obj.keyframe_insert(data_path="location",      frame=pre_frame, index=-1)
            obj.keyframe_insert(data_path="color",         frame=pre_frame, index=-1)

        obj.color = warn_color
        obj.keyframe_insert(data_path="color",    frame=start_f, index=-1)
        obj.keyframe_insert(data_path="scale",    frame=start_f, index=-1)
        obj.keyframe_insert(data_path="location", frame=start_f, index=-1)

        mid_frame = start_f + transition // 2
        obj.scale = (0.3, 0.3, 0.3)
        obj.location = (orig_loc[0], orig_loc[1], orig_loc[2] - 2.0)
        obj.keyframe_insert(data_path="scale",    frame=mid_frame, index=-1)
        obj.keyframe_insert(data_path="location", frame=mid_frame, index=-1)

        end_frame = start_f + transition
        obj.hide_viewport = True
        obj.hide_render = True
        obj.scale = (0.01, 0.01, 0.01)
        obj.location = (orig_loc[0], orig_loc[1], orig_loc[2] - 5.0)
        obj.keyframe_insert(data_path="hide_viewport", frame=end_frame, index=-1)
        obj.keyframe_insert(data_path="hide_render",   frame=end_frame, index=-1)
        obj.keyframe_insert(data_path="scale",         frame=end_frame, index=-1)
        obj.keyframe_insert(data_path="location",      frame=end_frame, index=-1)

        if obj.animation_data and obj.animation_data.action:
            for fcurve in obj.animation_data.action.fcurves:
                if fcurve.data_path in ("hide_viewport", "hide_render", "color"):
                    for kf in fcurve.keyframe_points:
                        kf.interpolation = 'CONSTANT'

        if i % 30 == 0 and i > 0:
            print(f"    已设置 {i}/{len(schedule)} 个构件动画...")

    last_end = schedule[-1]["end_frame"] + 24 if schedule else 504
    scene.frame_start = 0
    scene.frame_end = last_end
    scene.render.fps = fps

    return last_end


def export_schedule_csv(schedule, strategy):
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


if __name__ == "__main__":
    print("=" * 60)
    print("  逻辑驱动拆除动画")
    print("=" * 60)

    config = load_config()
    strategy = config["demolition_strategy"]
    anim_override_path = os.environ.get("BLENDER_ANIM_OVERRIDE", "")
    if anim_override_path and os.path.exists(anim_override_path):
        with open(anim_override_path, "r", encoding="utf-8") as f:
            anim_override = json.load(f)
        if "demolition_strategy" in anim_override:
            strategy.update(anim_override["demolition_strategy"])
        print("  [INFO] 已应用拆除策略覆盖")
    fps = config["fps"]

    print(f"  策略: {strategy['order']} | 同层排序: {strategy['within_floor_sort']}")
    imp_map = strategy['importance_map']
    imp_str = ", ".join(f"{k}={v}" for k, v in sorted(imp_map.items(), key=lambda x: -x[1]))
    print(f"  重要性映射: {imp_str}")
    print(f"  帧率: {fps}fps | 每步: {strategy['frame_per_step']}帧 | "
          f"过渡: {strategy['transition_frames']}帧 | 重叠: {strategy['overlap_frames']}帧")

    elements = collect_elements()
    print(f"\n  扫描到 {len(elements)} 个构件")

    if len(elements) == 0:
        print("  [ERROR] 未找到任何带元数据的构件！")
        print("  请先运行 generate_building.py 生成模型")
        exit(1)

    ordered = compute_demolition_order(elements, strategy)
    print(f"[ANIM_STEP] 拆除排序完成：{len(ordered)}个构件 按{strategy['order']}+{strategy['within_floor_sort']}排序")
    schedule, groups = assign_frames(ordered, strategy)
    print(f"[ANIM_STEP] 帧分配完成：{len(groups)}组 {len(schedule)}步")
    for i, (label, elems) in enumerate(groups):
        print(f"[ANIM_STEP] {i+1}/{len(groups)} {label} ({len(elems)}个构件)")
    print_schedule_summary(schedule, groups)

    print(f"\n  应用动画关键帧...")
    total_frames = apply_animation(schedule, config)
    print(f"[ANIM_STEP] 动画关键帧设置完成：{len(schedule)}个构件 {total_frames}帧")

    export_schedule_csv(schedule, strategy)
    save_blend()

    duration = total_frames / fps
    print(f"\n  时长: {duration:.1f}秒 ({total_frames}帧)")
    print("=" * 60)
    print("  拆除动画生成完成!")
    print("=" * 60)
