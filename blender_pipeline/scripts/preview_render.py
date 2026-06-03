"""
preview_render.py - 白模快速预览渲染
背景模式WORKBENCH，渲染速度快(0.1秒/帧)，用于检查镜头和动画节奏。
确认无误后再用正式渲染(render.py)。
"""

import bpy, os, math, sys
from datetime import datetime

BLENDER_PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def quick_preview():
    scene = bpy.context.scene
    proj_name = "preview"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(BLENDER_PIPELINE_DIR, "output", f"{proj_name}_{ts}")
    os.makedirs(out_dir, exist_ok=True)

    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = 640
    scene.render.resolution_y = 360
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'HIGH'  # 小文件
    scene.render.ffmpeg.ffmpeg_preset = 'REALTIME'      # 快速编码
    scene.render.ffmpeg.audio_codec = 'NONE'

    output_path = os.path.join(out_dir, f"white_preview_{ts}")
    scene.render.filepath = output_path

    # 清除旧相机，强制重建（防止残留旧参数）
    for obj in list(bpy.data.objects):
        if obj.type == 'CAMERA':
            bpy.data.objects.remove(obj)
    # 重建相机
        min_x = min_y = min_z = float('inf')
        max_x = max_y = max_z = float('-inf')
        for obj in bpy.data.objects:
            if obj.type == 'MESH' and obj.name != 'Ground':
                for v in obj.data.vertices:
                    wc = obj.matrix_world @ v.co
                    min_x=min(min_x,wc.x); max_x=max(max_x,wc.x)
                    min_y=min(min_y,wc.y); max_y=max(max_y,wc.y)
                    min_z=min(min_z,wc.z); max_z=max(max_z,wc.z)
        cx=(min_x+max_x)/2; cy=(min_y+max_y)/2; cz=(min_z+max_z)/2
        diag=math.sqrt((max_x-min_x)**2+(max_y-min_y)**2+(max_z-min_z)**2)
        dist=diag*1.3
        bpy.ops.object.camera_add(location=(cx+dist*0.7, cy-dist*0.7, cz+dist*0.5))
        cam=bpy.context.active_object; cam.data.lens=24; cam.data.clip_end=diag*3
        bpy.ops.object.empty_add(type='PLAIN_AXES',location=(cx,cy,cz))
        c=cam.constraints.new(type='TRACK_TO'); c.target=bpy.context.active_object
        c.track_axis='TRACK_NEGATIVE_Z'; c.up_axis='UP_Y'; scene.camera=cam

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
