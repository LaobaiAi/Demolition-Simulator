"""
preview.py - 预渲染验证脚本
渲染3-5个关键帧，验证镜头覆盖和动画节奏，确认后再进行完整渲染。
"""

import math
import os
from datetime import datetime

import bpy

from _common import compute_scene_bounds, OUTPUT_DIR


def load_scene_info(bounds):
    scene = bpy.context.scene
    element_count = sum(1 for obj in bpy.data.objects if "element_type" in obj)
    return {
        "total_w": bounds['width'],
        "total_d": bounds['depth'],
        "total_h": bounds['height'],
        "cx": bounds['cx'],
        "cy": bounds['cy'],
        "cz": bounds['cz'],
        "element_count": element_count,
        "frame_end": scene.frame_end,
        "fps": scene.render.fps,
        "duration": scene.frame_end / scene.render.fps,
    }


def setup_camera_for_preview(info):
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        if obj.type == 'CAMERA':
            bpy.data.objects.remove(obj)
        if obj.name == 'CameraTarget':
            bpy.data.objects.remove(obj)

    diagonal = math.sqrt(info["total_w"]**2 + info["total_d"]**2 + info["total_h"]**2)
    cam_distance = diagonal * 1.5
    clip_end = diagonal * 3

    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(info["cx"], info["cy"], info["cz"]))
    target = bpy.context.active_object
    target.name = "CameraTarget"

    angle = math.radians(45)
    cam_x = info["cx"] + cam_distance * math.cos(angle)
    cam_y = info["cy"] - cam_distance * math.sin(angle)
    cam_z = info["cz"] + info["total_h"] * 0.8

    bpy.ops.object.camera_add(location=(cam_x, cam_y, cam_z))
    cam = bpy.context.active_object
    cam.name = "MainCamera"
    cam.data.lens = 28.0
    cam.data.clip_end = clip_end
    c = cam.constraints.new(type='TRACK_TO')
    c.target = target
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    scene.camera = cam
    return cam, target


def setup_viewport_and_scene(info):
    scene = bpy.context.scene
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'SOLID'
                        space.shading.color_type = 'MATERIAL'
                        space.shading.light = 'STUDIO'
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.color = (0.45, 0.60, 0.85)
    bpy.ops.object.light_add(type='SUN', location=(info["cx"] + info["total_w"],
                                                     info["cy"] - info["total_d"],
                                                     info["cz"] + info["total_h"] * 2))
    bpy.context.active_object.name = "Sun_Light"
    bpy.context.active_object.data.energy = 3.5


def render_preview_frames(info, out_dir):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.image_settings.file_format = 'PNG'

    key_frames = [0, info["frame_end"] // 3, info["frame_end"] * 2 // 3, info["frame_end"]]
    results = []
    for f in key_frames:
        scene.frame_set(f)
        fpath = os.path.join(out_dir, f"preview_frame_{f:04d}.png")
        scene.render.filepath = fpath
        bpy.ops.render.opengl(write_still=True)
        print(f"  [OK] 预览帧 {f}/{info['frame_end']}")
        results.append(fpath)
    return results


def print_validation_report(info):
    print("\n" + "=" * 60)
    print("  预渲染验证报告")
    print("=" * 60)
    print(f"  构件数: {info['element_count']}")
    print(f"  场景尺寸: {info['total_w']:.0f}m x {info['total_d']:.0f}m x {info['total_h']:.1f}m")
    print(f"  对角线: {math.sqrt(info['total_w']**2+info['total_d']**2+info['total_h']**2):.0f}m")
    print(f"  动画帧数: {info['frame_end']} 帧")
    print(f"  动画时长: {info['duration']:.1f} 秒 @ {info['fps']}fps")
    if info['duration'] < 8:
        print(f"  WARNING  动画速度: 太快! ({info['duration']:.1f}秒)")
        print(f"     建议: 增大 config 中 frame_per_step 参数")
    elif info['duration'] < 15:
        print(f"  OK  动画速度: 适中 ({info['duration']:.1f}秒)")
    else:
        print(f"  OK  动画速度: 充足 ({info['duration']:.1f}秒)")
    if info['total_w'] > 100:
        print(f"  大跨度建筑({info['total_w']:.0f}m)，使用28mm广角+{info['total_w']*1.5:.0f}m距离")
    print("=" * 60)
    print("  请查看预览帧确认镜头和速度，然后运行完整渲染。")
    print("=" * 60)


if __name__ == "__main__":
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(OUTPUT_DIR, f"preview_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    print(f"  预览输出: {out_dir}")

    bounds = compute_scene_bounds()
    if bounds is None:
        print("  [ERROR] 场景中没有网格物体!")
        exit(1)

    info = load_scene_info(bounds)
    print_validation_report(info)

    setup_viewport_and_scene(info)
    cam, target = setup_camera_for_preview(info)
    render_preview_frames(info, out_dir)

    print(f"\n  预览完成! 查看 {out_dir}/ 中的PNG文件")
