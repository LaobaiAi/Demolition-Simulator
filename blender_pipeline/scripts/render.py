"""
render.py - OpenGL 视口渲染（UI模式，支持材料颜色）
必须运行在非背景模式下才能使用GPU渲染颜色。
"""

import json
import math
import os
from datetime import datetime

import bpy

from _common import compute_scene_bounds, OUTPUT_DIR, setup_gradient_sky


def load_config():
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    with open(os.path.join(data_dir, "project_config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def setup_viewport():
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
    setup_gradient_sky()
    print(f"  [OK] 天空: 淡蓝渐变")


def setup_lighting():
    bpy.ops.object.light_add(type='SUN', location=(25, 20, 30))
    bpy.context.active_object.name = "Sun_Light"
    bpy.context.active_object.data.energy = 3.5
    bpy.ops.object.light_add(type='SUN', location=(-10, -10, 10))
    bpy.context.active_object.name = "Fill_Light"
    bpy.context.active_object.data.energy = 1.0
    print("  [OK] 光照已设置")


def setup_camera(config, bounds):
    scene = bpy.context.scene
    cam_distance = bounds['diagonal'] * 1.2
    cam_height = bounds['diagonal'] * 0.5
    clip_end = bounds['diagonal'] * 3

    for obj in list(bpy.data.objects):
        if obj.type == 'CAMERA' or obj.name == 'CameraTarget':
            bpy.data.objects.remove(obj)

    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(bounds['cx'], bounds['cy'], bounds['cz']))
    target = bpy.context.active_object
    target.name = "CameraTarget"

    bpy.ops.object.camera_add(
        location=(bounds['cx'] + cam_distance * 0.7,
                  bounds['cy'] - cam_distance * 0.7,
                  bounds['cz'] + cam_height))
    cam = bpy.context.active_object
    cam.name = "MainCamera"
    cam.data.lens = 24.0
    cam.data.clip_end = clip_end
    c = cam.constraints.new(type='TRACK_TO')
    c.target = target
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    scene.camera = cam

    total_frames = scene.frame_end - scene.frame_start
    angles = [45, 50, 55]
    for i, ang in enumerate(angles):
        t = int(total_frames * i / (len(angles) - 1)) if len(angles) > 1 else 0
        t = max(0, min(t, total_frames))
        cam.location = (bounds['cx'] + cam_distance * math.cos(math.radians(ang)),
                         bounds['cy'] - cam_distance * math.sin(math.radians(ang)),
                         bounds['cz'] + cam_height)
        cam.keyframe_insert(data_path="location", frame=t, index=-1)

    if cam.animation_data and cam.animation_data.action:
        for fc in cam.animation_data.action.fcurves:
            for kf in fc.keyframe_points:
                kf.interpolation = 'BEZIER'

    info = f"{bounds['width']:.0f}x{bounds['depth']:.0f}x{bounds['height']:.1f}m, 对角线{bounds['diagonal']:.0f}m, 距离{cam_distance:.0f}m"
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

    project_name = config.get("project_name", "demolition").replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    proj_dir = os.path.join(OUTPUT_DIR, f"{project_name}_{timestamp}")
    os.makedirs(proj_dir, exist_ok=True)

    ts_short = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(proj_dir, f"animation_{ts_short}")
    scene.render.filepath = output_path

    print("=" * 60)
    print("  渲染输出 (OpenGL视口模式)")
    print(f"  项目目录: {proj_dir}")
    print("=" * 60)

    bounds = compute_scene_bounds()
    if bounds is None:
        print("  [ERROR] 场景中没有网格物体!")
        exit(1)

    setup_viewport()
    setup_sky(config)
    setup_lighting()
    setup_camera(config, bounds)
    setup_render(config, scene)
    render_animation(config)

    print(f"\n  输出目录: {proj_dir}")
    print("=" * 60)
    print("  渲染完成!")
    print("=" * 60)
