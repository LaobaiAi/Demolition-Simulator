"""
animate_demolition.py - 汽轮机厂房拆除动画
按工序序列控制构件逐组隐藏，步骤7~11加速播放。

用法:
  blender --background output/blend/scene_base.blend --python scripts/animate_demolition.py
"""

import bpy
import os
import sys
import json
import math

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output", "blend")
BLEND_OUTPUT = os.environ.get("BLEND_OUTPUT_DIR") or os.environ.get("BLENDER_OUTPUT_DIR", OUTPUT_DIR)
os.makedirs(BLEND_OUTPUT, exist_ok=True)


def load_config():
    with open(os.path.join(DATA_DIR, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def find_objects(patterns):
    """按名称前缀/精确匹配查找对象列表"""
    result = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        for pat in patterns:
            if pat.endswith('*'):
                if obj.name.startswith(pat[:-1]):
                    result.append(obj)
                    break
            elif obj.name == pat:
                result.append(obj)
                break
    return result


def build_sequence():
    """构建拆除工序序列。每项: (标签, 名称模式列表, 速度)"""
    seq = []

    # ═══ 步骤0: 西端BC跨山墙 ═══
    seq.append(("0_Gable_West_BC", ["Gable_West_BC_lower"], "normal"))

    # ═══ 步骤1: BC跨 Bay23→21 自上而下 ═══
    for bay in [23, 22, 21]:
        seq.append((f"1_BC_B{bay}_Roof",    [f"Roof_BC_{bay}"],          "normal"))
        # 梁: 左梁=bay号, 右梁=bay+1号 (但可能已被前跨拆除)
        beams = [f"Beam_BC_{bay}"]
        if bay == 23:  # 首跨连右梁一起拆
            beams.append(f"Beam_BC_{bay + 1}")
        seq.append((f"1_BC_B{bay}_Beams",   beams,                       "normal"))
        seq.append((f"1_BC_B{bay}_Floor15", [f"Floor_BC_{bay}_z15"],     "normal"))
        seq.append((f"1_BC_B{bay}_Floor8",  [f"Floor_BC_{bay}_z8"],      "normal"))

    # ═══ 步骤2: AB屋面板 Bay23→21 ═══
    for bay in [23, 22, 21]:
        seq.append((f"2_AB_B{bay}_Roof",
                    [f"Roof_AB_{bay}_S", f"Roof_AB_{bay}_N"], "normal"))

    # ═══ 步骤3: 钢屋架 24→22 ═══
    for n in [24, 23, 22]:
        seq.append((f"3_Truss_{n}", [f"Truss_{n}_*"], "normal"))

    # ═══ 步骤4: A轴墙板 23→21 ═══
    for n in [23, 22, 21]:
        seq.append((f"4_Wall_A_{n}", [f"Wall_A_{n}"], "normal"))

    # ═══ 步骤5: 西端AB跨山墙 ═══
    seq.append((f"5_Gable_West_AB_lower", ["Gable_West_AB_lower"], "normal"))
    seq.append((f"5_Gable_West_AB_tri",   ["Gable_West_AB_tri"],   "normal"))

    # ═══ 步骤6: 西端抗风柱 ═══
    seq.append((f"6_WindCol_West", ["WindCol_West_1", "WindCol_West_2"], "normal"))

    # ═══ 步骤7: AB屋面板 Bay20→1 (每5跨一组, 极速) ═══
    for g in range(20, 0, -5):
        batch = []
        for bay in range(g, max(g - 5, 0), -1):
            batch.extend([f"Roof_AB_{bay}_S", f"Roof_AB_{bay}_N"])
        seq.append((f"7_AB_B{g}..{max(g-4,1)}_Roof", batch, "rapid"))

    # ═══ 步骤8: A轴墙板 20→1 (每5跨一组, 极速) ═══
    for g in range(20, 0, -5):
        batch = [f"Wall_A_{n}" for n in range(g, max(g - 5, 0), -1)]
        seq.append((f"8_Wall_A_{g}..{max(g-4,1)}", batch, "rapid"))

    # ═══ 步骤9: 钢屋架 21→1 (每5榀一组, 极速) ═══
    for g in range(21, 0, -5):
        batch = []
        for n in range(g, max(g - 5, 0), -1):
            batch.append(f"Truss_{n}_*")
        seq.append((f"9_Truss_{g}..{max(g-4,1)}", batch, "rapid"))

    # ═══ 步骤10: 东端AB跨山墙 ═══
    seq.append((f"10_Gable_East_AB_lower", ["Gable_East_AB_lower"], "fast"))
    seq.append((f"10_Gable_East_AB_tri",   ["Gable_East_AB_tri"],   "fast"))

    # ═══ 步骤11: 东端抗风柱 ═══
    seq.append((f"11_WindCol_East", ["WindCol_East_1", "WindCol_East_2"], "fast"))

    # ═══ 步骤12: A轴柱子 24→1, 每4根一组 (西→东, 加速) ═══
    for g in range(24, 0, -4):
        batch = [f"Col_A{n}" for n in range(g, max(g - 4, 0), -1)]
        seq.append((f"12_Col_A_{g}..{max(g-3,1)}", batch, "fast"))

    # ═══ 步骤13: 批量拆除除C轴柱子外所有剩余构件 (西→东, 加速) ═══
    seq.append(("13_Rest_except_ColC", ["__ALL_EXCEPT_COLC__"], "fast"))

    # ═══ 步骤14: C轴柱子 24→1, 每4根一组 (西→东, 加速, 最后) ═══
    for g in range(24, 0, -4):
        batch = [f"Col_C{n}" for n in range(g, max(g - 4, 0), -1)]
        seq.append((f"14_Col_C_{g}..{max(g-3,1)}", batch, "fast"))

    return seq


def find_remaining_except_colc():
    """查找所有未被隐藏的MESH构件，排除Col_C_*"""
    result = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        if obj.name.startswith("Col_C"):
            continue
        if obj.hide_viewport:
            continue
        result.append(obj)
    # 按X坐标从大到小排序 (西→东)
    result.sort(key=lambda o: o.location.x, reverse=True)
    return result


def apply_demolition(sequence, fps=24):
    """
    应用拆除动画。
    速度参数:
      normal: 48帧间隔, 12帧过渡
      fast:   12帧间隔,  6帧过渡
    """
    scene = bpy.context.scene
    warn_color = (1.0, 0.35, 0.08, 1.0)

    # 速度配置（preview模式用1/4帧数）
    preview = "--preview" in sys.argv
    if preview:
        SPEED_CFG = {
            "normal": {"spacing": 12, "transition": 4},
            "fast":   {"spacing": 4,  "transition": 2},
            "rapid":  {"spacing": 2,  "transition": 1},
        }
    else:
        SPEED_CFG = {
            "normal": {"spacing": 48, "transition": 12},
            "fast":   {"spacing": 12, "transition": 6},
            "rapid":  {"spacing": 6,  "transition": 3},
        }

    current_frame = 0
    schedule = []
    milestones = {
        "fast_start": None,    # 加速段开始帧
        "col_a_start": None,   # A柱开始帧
        "rest_start": None,    # 批量清理开始帧
    }

    for label, patterns, speed in sequence:
        # 步骤13特殊处理: 匹配所有剩余非ColC构件
        if "__ALL_EXCEPT_COLC__" in patterns:
            all_rest = find_remaining_except_colc()
            # 按bay分组 (西→东), 每组作为一个子步
            bay_groups = {}
            for obj in all_rest:
                bx = int(round(obj.location.x / 8.0))  # 柱距8m
                bay_groups.setdefault(bx, []).append(obj)
            # 按bay降序 (西→东)
            for bx in sorted(bay_groups, reverse=True):
                bay_objs = bay_groups[bx]
                cfg = SPEED_CFG[speed]
                spacing = cfg["spacing"]
                transition = cfg["transition"]
                start_f = current_frame
                for obj in bay_objs:
                    schedule.append({
                        "obj": obj, "start_f": start_f, "transition": transition,
                        "name": obj.name, "speed": speed, "group": "rest",
                    })
                print(f"  {'13_Rest_bay'+str(bx):40s} {len(bay_objs)}构件 @ frame {start_f} ({speed})")
                if milestones["rest_start"] is None:
                    milestones["rest_start"] = start_f
                current_frame = start_f + spacing
        else:
            objs = find_objects(patterns)
            if not objs:
                print(f"  [WARN] 未找到: {patterns}")
                continue

            cfg = SPEED_CFG[speed]
            spacing = cfg["spacing"]
            transition = cfg["transition"]

            start_f = current_frame
            for obj in objs:
                schedule.append({
                    "obj": obj, "start_f": start_f, "transition": transition,
                    "name": obj.name, "speed": speed,
                })
                if speed != "fast":
                    print(f"  {label:40s} {obj.name:35s} @ frame {start_f} ({speed})")

            # 记录里程碑
            if speed == "fast" and milestones["fast_start"] is None:
                milestones["fast_start"] = start_f
            if "Col_A" in label and milestones["col_a_start"] is None:
                milestones["col_a_start"] = start_f
            if "__ALL_EXCEPT_COLC__" in patterns and milestones["rest_start"] is None:
                milestones["rest_start"] = start_f

            current_frame = start_f + spacing

    # ── 应用关键帧 ──
    print(f"\n  应用动画关键帧 ({len(schedule)} 构件)...")

    for i, item in enumerate(schedule):
        obj = item["obj"]
        start_f = item["start_f"]
        transition = item["transition"]
        orig_loc = (obj.location.x, obj.location.y, obj.location.z)
        orig_scale = (obj.scale.x, obj.scale.y, obj.scale.z)
        orig_color = tuple(obj.color) if hasattr(obj, 'color') else (0.8, 0.8, 0.8, 1.0)

        # 重置状态
        obj.hide_viewport = False
        obj.hide_render = False
        obj.scale = orig_scale
        obj.location = orig_loc
        obj.color = orig_color

        # 帧0: 初始状态
        scene.frame_set(0)
        obj.keyframe_insert(data_path="hide_viewport", index=-1)
        obj.keyframe_insert(data_path="hide_render", index=-1)
        obj.keyframe_insert(data_path="scale", index=-1)
        obj.keyframe_insert(data_path="location", index=-1)
        obj.keyframe_insert(data_path="color", index=-1)

        # 拆除前确认
        pre_f = max(0, start_f - 2)
        if pre_f > 0:
            scene.frame_set(pre_f)
            obj.hide_viewport = False
            obj.hide_render = False
            obj.scale = orig_scale
            obj.location = orig_loc
            obj.color = orig_color
            obj.keyframe_insert(data_path="hide_viewport", index=-1)
            obj.keyframe_insert(data_path="hide_render", index=-1)
            obj.keyframe_insert(data_path="scale", index=-1)
            obj.keyframe_insert(data_path="location", index=-1)
            obj.keyframe_insert(data_path="color", index=-1)

        # 拆除起点: 变橙
        scene.frame_set(start_f)
        obj.color = warn_color
        obj.keyframe_insert(data_path="color", index=-1)

        # 过渡中: 缩小+下坠
        mid_f = start_f + transition // 2
        scene.frame_set(mid_f)
        obj.scale = (0.3, 0.3, 0.3)
        obj.location = (orig_loc[0], orig_loc[1], orig_loc[2] - 2.0)
        obj.keyframe_insert(data_path="scale", index=-1)
        obj.keyframe_insert(data_path="location", index=-1)

        # 拆除完成: 隐藏
        scene.frame_set(start_f + transition)
        obj.hide_viewport = True
        obj.hide_render = True
        obj.scale = (0.01, 0.01, 0.01)
        obj.location = (orig_loc[0], orig_loc[1], orig_loc[2] - 5.0)
        obj.keyframe_insert(data_path="hide_viewport", index=-1)
        obj.keyframe_insert(data_path="hide_render", index=-1)
        obj.keyframe_insert(data_path="scale", index=-1)
        obj.keyframe_insert(data_path="location", index=-1)

        # hide + color 用 CONSTANT 插值
        if obj.animation_data and obj.animation_data.action:
            for fc in obj.animation_data.action.fcurves:
                if fc.data_path in ("hide_viewport", "hide_render", "color"):
                    for kf in fc.keyframe_points:
                        kf.interpolation = 'CONSTANT'

        if (i + 1) % 30 == 0:
            print(f"    进度 {i + 1}/{len(schedule)}")

    # 场景帧范围
    total_frames = current_frame + 48  # 末尾留2秒
    scene.frame_start = 0
    scene.frame_end = total_frames
    scene.render.fps = fps

    return total_frames, schedule, milestones


def setup_camera_follow(total_frames, milestones):
    """镜头: 0帧全貌→平移至西端→跟随拆除→最后居中"""
    scene = bpy.context.scene

    # 包围盒
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.name == 'Ground':
            continue
        for v in obj.data.vertices:
            w = obj.matrix_world @ v.co
            min_x = min(min_x, w.x); max_x = max(max_x, w.x)
            min_y = min(min_y, w.y); max_y = max(max_y, w.y)
            min_z = min(min_z, w.z); max_z = max(max_z, w.z)

    W = max_x - min_x
    D = max_y - min_y
    H = max_z - min_z
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    cz = (min_z + max_z) / 2
    diagonal = math.sqrt(W * W + D * D + H * H)
    cam_dist = diagonal * 0.85
    cam_height = diagonal * 0.35

    west_x = max_x - 1
    east_x = min_x + 1
    mid_x = cx

    # 清除旧相机/目标
    for obj in list(bpy.data.objects):
        if obj.type == 'CAMERA' or obj.name == 'CameraTarget':
            bpy.data.objects.remove(obj, do_unlink=True)

    # ── 目标空物体 ──
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(mid_x, cy, cz * 0.7))
    target = bpy.context.active_object
    target.name = "CameraTarget"

    t_fast = milestones.get("fast_start")
    t_col_a = milestones.get("col_a_start")
    t_rest = milestones.get("rest_start")

    # 关键帧: 聚焦西端10秒 → 跟随东移 → 最后居中
    west_focus = 240  # 前10秒(240帧@24fps)聚焦西端

    # K0: 西端聚焦开始
    scene.frame_set(0)
    target.location.x = west_x
    target.keyframe_insert(data_path="location", index=-1)

    # K1: 10秒后 — 保持西端
    scene.frame_set(west_focus)
    target.location.x = west_x
    target.keyframe_insert(data_path="location", index=-1)

    # K2+: 跟随拆除东移
    if t_fast and t_fast > west_focus:
        scene.frame_set(t_fast)
        target.location.x = west_x - 40
        target.keyframe_insert(data_path="location", index=-1)

    if t_col_a and t_col_a > (t_fast or 0):
        scene.frame_set(t_col_a)
        target.location.x = east_x + 10
        target.keyframe_insert(data_path="location", index=-1)

    if t_rest and t_rest > (t_col_a or 0):
        scene.frame_set(t_rest)
        target.location.x = mid_x
        target.keyframe_insert(data_path="location", index=-1)

    scene.frame_set(total_frames)
    target.location.x = mid_x
    target.keyframe_insert(data_path="location", index=-1)

    # ── 相机 ──
    cam_base_x = cx + cam_dist * 0.55
    cam_base_y = cy - cam_dist * 0.70
    cam_base_z = cz + cam_height
    offset_x = cam_base_x - cx

    bpy.ops.object.camera_add(
        location=(west_x + offset_x, cam_base_y, cam_base_z))
    cam = bpy.context.active_object
    cam.name = "MainCamera"
    cam.data.lens = 20.0
    cam.data.clip_end = diagonal * 3

    c = cam.constraints.new(type='TRACK_TO')
    c.target = target
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'

    scene.camera = cam

    # 相机X跟随目标
    key_frames = sorted(set(
        [0, west_focus] +
        ([t_fast] if t_fast else []) +
        ([t_col_a] if t_col_a else []) +
        ([t_rest] if t_rest else []) +
        [total_frames]
    ))
    for kf in key_frames:
        scene.frame_set(kf)
        cam.location.x = target.location.x + offset_x
        cam.keyframe_insert(data_path="location", index=-1)

    # 平滑
    for obj in [cam, target]:
        if obj.animation_data and obj.animation_data.action:
            for fc in obj.animation_data.action.fcurves:
                for kf in fc.keyframe_points:
                    kf.interpolation = 'BEZIER'

    preview = "--preview" in sys.argv
    print(f"  [OK] 镜头: {W:.0f}x{D:.0f}x{H:.0f}m, 距{cam_dist:.0f}m, 20mm"
          f"{' + 全貌开场' if not preview else ' + 全貌开场(preview)'}")


def main():
    config = load_config()
    fps = config["fps"]

    print("=" * 60)
    print("  汽轮机厂房 - 拆除动画")
    print("=" * 60)

    sequence = build_sequence()
    normal_count = sum(1 for _, _, s in sequence if s == "normal")
    fast_count = sum(1 for _, _, s in sequence if s == "fast")
    print(f"  工序: {len(sequence)} 步 (正常{normal_count} + 加速{fast_count})")

    total_frames, schedule, milestones = apply_demolition(sequence, fps)

    print(f"\n  设置镜头跟随...")
    setup_camera_follow(total_frames, milestones)

    # 保存
    blend_path = os.path.join(BLEND_OUTPUT, "scene_animated.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"\n  [OK] 动画已保存: {blend_path}")

    duration = total_frames / fps
    print(f"  时长: {duration:.0f}秒 ({total_frames}帧 @ {fps}fps)")
    print(f"  正常速度步骤: {normal_count} × 48帧间隔")
    print(f"  加速步骤:     {fast_count} × 12帧间隔")
    print("=" * 60)


if __name__ == "__main__":
    main()
