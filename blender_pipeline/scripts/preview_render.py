"""
preview_render.py - 白模快速预览渲染
背景模式WORKBENCH，渲染速度快(0.1秒/帧)，用于检查镜头和动画节奏。
确认无误后再用正式渲染(render.py)。
"""

import math
import os
from datetime import datetime

import bpy

from _common import compute_scene_bounds, OUTPUT_DIR


def quick_preview():
    scene = bpy.context.scene
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(OUTPUT_DIR, f"preview_{ts}")
    os.makedirs(out_dir, exist_ok=True)

    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = 640
    scene.render.resolution_y = 360
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'HIGH'
    scene.render.ffmpeg.ffmpeg_preset = 'REALTIME'
    scene.render.ffmpeg.audio_codec = 'NONE'

    output_path = os.path.join(out_dir, f"white_preview_{ts}")
    scene.render.filepath = output_path

    bounds = compute_scene_bounds()
    if bounds is None:
        print("  [ERROR] 场景中没有网格物体!")
        return

    for obj in list(bpy.data.objects):
        if obj.type == 'CAMERA':
            bpy.data.objects.remove(obj)

    dist = bounds['diagonal'] * 1.3
    bpy.ops.object.camera_add(
        location=(bounds['cx'] + dist * 0.7,
                  bounds['cy'] - dist * 0.7,
                  bounds['cz'] + dist * 0.5))
    cam = bpy.context.active_object
    cam.data.lens = 24
    cam.data.clip_end = bounds['diagonal'] * 3

    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(bounds['cx'], bounds['cy'], bounds['cz']))
    c = cam.constraints.new(type='TRACK_TO')
    c.target = bpy.context.active_object
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    scene.camera = cam

    nf = scene.frame_end - scene.frame_start + 1
    dur = nf / scene.render.fps
    print(f"  白模预览: {nf}帧/{dur:.0f}秒 @ {scene.render.resolution_x}x{scene.render.resolution_y}")
    print(f"  输出: {output_path}")
    print(f"  预计耗时: ~{nf*0.1:.0f}秒")

    bpy.ops.render.render(animation=True)
    print(f"  完成! {out_dir}")

    for f in os.listdir(out_dir):
        if f.endswith('.mp4'):
            print(f"  视频: {os.path.join(out_dir, f)}")
            print(f"  大小: {os.path.getsize(os.path.join(out_dir, f))/1024:.0f}KB")


if __name__ == "__main__":
    quick_preview()
