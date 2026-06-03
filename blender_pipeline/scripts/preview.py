"""
preview.py - 预渲染验证脚本
渲染3-5个关键帧，验证镜头覆盖和动画节奏，确认后再进行完整渲染。
"""

import bpy, json, os, sys, math
from datetime import datetime

BLENDER_PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config_from_scene():
    """从场景数据推断配置"""
    scene = bpy.context.scene
    # 收集所有构件的边界
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    element_count = 0
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.name == 'Ground':
            continue
        if 'element_type' not in obj and obj.name != 'Ground':
            continue
        element_count += 1
        for vert in obj.data.vertices:
            world_co = obj.matrix_world @ vert.co
            min_x = min(min_x, world_co.x)
            min_y = min(min_y, world_co.y)
            min_z = min(min_z, world_co.z)
            max_x = max(max_x, world_co.x)
            max_y = max(max_y, world_co.y)
            max_z = max(max_z, world_co.z)

    total_w = max_x - min_x
    total_d = max_y - min_y
    total_h = max_z - min_z
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    cz = (min_z + max_z) / 2.0
    return {
        "total_w": total_w, "total_d": total_d, "total_h": total_h,
        "cx": cx, "cy": cy, "cz": cz,
        "element_count": element_count,
        "frame_end": scene.frame_end,
        "fps": scene.render.fps,
        "duration": scene.frame_end / scene.render.fps
    }


def setup_camera_for_preview(info):
    """根据场景尺寸设置合适的摄像机"""
    scene = bpy.context.scene
    # 清除旧相机
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
    cam.data.lens = 28.0  # 广角镜头看全景
    cam.data.clip_end = clip_end
    c = cam.constraints.new(type='TRACK_TO')
    c.target = target
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    scene.camera = cam
    return cam, target


def setup_viewport_and_scene():
    """设置视口和场景基础"""
    scene = bpy.context.scene
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'SOLID'
                        space.shading.color_type = 'MATERIAL'
                        space.shading.light = 'STUDIO'
    # 天空
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.color = (0.45, 0.60, 0.85)
    # 光照
    bpy.ops.object.light_add(type='SUN', location=(info["cx"] + info["total_w"],
                                                     info["cy"] - info["total_d"],
                                                     info["cz"] + info["total_h"] * 2))
    bpy.context.active_object.name = "Sun_Light"
    bpy.context.active_object.data.energy = 3.5


def render_preview_frames(info, out_dir):
    """渲染预览帧"""
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
    """打印验证报告"""
    print("\n" + "=" * 60)
    print("  预渲染验证报告")
    print("=" * 60)
    print(f"  构件数: {info['element_count']}")
    print(f"  场景尺寸: {info['total_w']:.0f}m × {info['total_d']:.0f}m × {info['total_h']:.1f}m")
    print(f"  对角线: {math.sqrt(info['total_w']**2+info['total_d']**2+info['total_h']**2):.0f}m")
    print(f"  动画帧数: {info['frame_end']} 帧")
    print(f"  动画时长: {info['duration']:.1f} 秒 @ {info['fps']}fps")
    # 速度评估
    if info['duration'] < 8:
        print(f"  ⚠️  动画速度: 太快! ({info['duration']:.1f}秒)")
        print(f"     建议: 增大 config 中 frame_per_step 参数")
    elif info['duration'] < 15:
        print(f"  ✅  动画速度: 适中 ({info['duration']:.1f}秒)")
    else:
        print(f"  ✅  动画速度: 充足 ({info['duration']:.1f}秒)")
    # 镜头评估
    if info['total_w'] > 100:
        print(f"  📐 大跨度建筑({info['total_w']:.0f}m)，使用28mm广角+{info['total_w']*1.5:.0f}m距离")
    print("=" * 60)
    print("  请查看预览帧确认镜头和速度，然后运行完整渲染。")
    print("=" * 60)


if __name__ == "__main__":
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(BLENDER_PIPELINE_DIR, "output", f"preview_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    print(f"  预览输出: {out_dir}")

    info = load_config_from_scene()
    print_validation_report(info)

    setup_viewport_and_scene()
    cam, target = setup_camera_for_preview(info)
    render_preview_frames(info, out_dir)

    print(f"\n  预览完成! 查看 {out_dir}/ 中的PNG文件")
    print("  确认无误后运行: python scripts/main_pipeline.py --stage render")
