"""
render.py - OpenGL 视口渲染（UI模式，支持材料颜色）
必须运行在非背景模式下才能使用GPU渲染颜色。
"""

import bpy
import json
import os
import sys
import math
from datetime import datetime

BLENDER_PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BLENDER_PIPELINE_DIR, "data")
OUTPUT_BASE = os.path.join(BLENDER_PIPELINE_DIR, "output")


def load_config():
    with open(os.path.join(DATA_DIR, "project_config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def setup_viewport():
    """设置视口为 SOLID+MATERIAL 模式（唯一能在集成显卡上渲染颜色的方案）"""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'SOLID'
                        space.shading.color_type = 'OBJECT'
                        space.shading.light = 'FLAT'
                        space.shading.show_backface_culling = False
    print("  [OK] 视口: SOLID + MATERIAL + STUDIO")


def setup_sky(config):
    """设置天空颜色"""
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.color = (0.45, 0.60, 0.85)  # 经典淡蓝天空
    print(f"  [OK] 天空: 淡蓝色")


def setup_lighting():
    bpy.ops.object.light_add(type='SUN', location=(25, 20, 30))
    bpy.context.active_object.name = "Sun_Light"
    bpy.context.active_object.data.energy = 3.5
    bpy.ops.object.light_add(type='SUN', location=(-10, -10, 10))
    bpy.context.active_object.name = "Fill_Light"
    bpy.context.active_object.data.energy = 1.0
    print("  [OK] 光照已设置")


def setup_camera(config, bld_override=None):
    """根据场景尺寸智能设置摄像机，确保全景可见"""
    scene = bpy.context.scene

    # 从场景几何计算实际尺寸
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.name == 'Ground':
            continue
        for vert in obj.data.vertices:
            wc = obj.matrix_world @ vert.co
            min_x = min(min_x, wc.x); max_x = max(max_x, wc.x)
            min_y = min(min_y, wc.y); max_y = max(max_y, wc.y)
            min_z = min(min_z, wc.z); max_z = max(max_z, wc.z)

    total_w = max_x - min_x
    total_d = max_y - min_y
    total_h = max_z - min_z
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    cz = (min_z + max_z) / 2.0

    # 相机距离和高度(与白模验证通过的同款公式)
    diagonal = math.sqrt(total_w**2 + total_d**2 + total_h**2)
    cam_distance = diagonal * 1.2
    cam_height = diagonal * 0.5
    clip_end = diagonal * 3

    # 清除旧相机和目标（防止残留旧参数）
    for obj in list(bpy.data.objects):
        if obj.type == 'CAMERA' or obj.name == 'CameraTarget':
            bpy.data.objects.remove(obj)
    # 广角镜头确保全景
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(cx, cy, cz))
    target = bpy.context.active_object
    target.name = "CameraTarget"

    bpy.ops.object.camera_add(
        location=(cx + cam_distance * 0.7,
                  cy - cam_distance * 0.7,
                  cz + cam_height))
    cam = bpy.context.active_object
    cam.name = "MainCamera"
    cam.data.lens = 24.0
    cam.data.clip_end = clip_end
    c = cam.constraints.new(type='TRACK_TO')
    c.target = target
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    scene.camera = cam

    # 摄像机动画: 缓慢环绕，保持同样高度(确保全景)
    total_frames = scene.frame_end - scene.frame_start
    angles = [45, 50, 55]
    for i, ang in enumerate(angles):
        t = int(total_frames * i / (len(angles) - 1)) if len(angles) > 1 else 0
        t = max(0, min(t, total_frames))
        scene.frame_set(t)
        cam.location = (cx + cam_distance * math.cos(math.radians(ang)),
                         cy - cam_distance * math.sin(math.radians(ang)),
                         cz + cam_height)
        cam.keyframe_insert(data_path="location", index=-1)
    if cam.animation_data and cam.animation_data.action:
        for fc in cam.animation_data.action.fcurves:
            for kf in fc.keyframe_points:
                kf.interpolation = 'BEZIER'

    info = f"{total_w:.0f}x{total_d:.0f}x{total_h:.1f}m, 对角线{diagonal:.0f}m, 距离{cam_distance:.0f}m"
    print(f"  [OK] 摄像机: {info} | 镜头24mm广角 | 裁剪{clip_end:.0f}m")


def setup_render(config, scene):
    fps = config.get("fps", 24)
    scene.render.fps = fps
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = config.get("resolution_x", 1280)
    scene.render.resolution_y = config.get("resolution_y", 720)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'MEDIUM'
    scene.render.ffmpeg.ffmpeg_preset = 'GOOD'
    scene.render.ffmpeg.audio_codec = 'NONE'

    # Stamp 时间戳叠加
    scene.render.use_stamp = True
    scene.render.use_stamp_frame = True
    scene.render.use_stamp_time = True
    scene.render.use_stamp_date = True
    scene.render.use_stamp_note = True
    scene.render.stamp_note_text = "Demolition Animation"
    scene.render.use_stamp_labels = True
    scene.render.stamp_font_size = 20
    scene.render.stamp_foreground = (1, 1, 1, 0.9)
    scene.render.stamp_background = (0, 0, 0, 0.5)

    nf = scene.frame_end - scene.frame_start + 1
    dur = nf / fps
    print(f"  [OK] 引擎: OpenGL视口 | {scene.render.resolution_x}x{scene.render.resolution_y}")
    print(f"  [OK] 帧: {scene.frame_start}-{scene.frame_end} ({nf}帧, {dur:.0f}秒)")


def render_animation(config):
    scene = bpy.context.scene
    if scene.camera is None:
        print("  [ERROR] 无摄像机!")
        return None

    # 关键：强制所有3D视口切换到相机视角（否则OpenGL渲染不用场景相机）
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.region_3d.view_perspective = 'CAMERA'

    nf = scene.frame_end - scene.frame_start + 1
    print(f"\n  开始OpenGL渲染(相机视角) {nf} 帧...")
    try:
        bpy.ops.render.opengl(animation=True)
        print("  [OK] 渲染完成")
        return scene.render.filepath
    except Exception as e:
        print(f"  [ERROR] 渲染失败: {e}")
        return None


if __name__ == "__main__":
    config = load_config()
    scene = bpy.context.scene

    # 输出目录（带项目名和时间戳）
    project_name = config.get("project_name", "demolition").replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    proj_dir = os.path.join(OUTPUT_BASE, f"{project_name}_{timestamp}")
    os.makedirs(proj_dir, exist_ok=True)

    ts_short = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(proj_dir, f"animation_{ts_short}")
    scene.render.filepath = output_path

    print("=" * 60)
    print("  渲染输出 (OpenGL视口模式)")
    print(f"  项目目录: {proj_dir}")
    print("=" * 60)

    setup_viewport()
    setup_sky(config)
    setup_lighting()
    setup_camera(config)
    setup_render(config, scene)
    render_animation(config)

    print(f"\n  输出目录: {proj_dir}")
    print("=" * 60)
    print("  渲染完成!")
    print("=" * 60)
