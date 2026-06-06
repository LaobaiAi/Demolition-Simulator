"""
build_steam_turbine_model.py — 蒸汽轮机厂房白模生成（CAIAO pipeline 包装）

通过 BLENDER_CONFIG_PATH 传入 config.json 路径，或通过 BLENDER_STEAM_TURBINE_JSON
传入完整 JSON 字符串（base64 编码）。无参时使用项目默认配置。

用法（CAIAO server）:
    blender --background --python build_steam_turbine_model.py
"""
import base64
import json
import os
import sys

import bpy

# 把项目脚本目录加入 path（给 import build_steam_turbine 用）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_THIS_DIR)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
_STEAM_DIR = os.path.join(_PROJECT_DIR, "projects", "steam_turbine_building", "scripts")
if _STEAM_DIR not in sys.path:
    sys.path.insert(0, _STEAM_DIR)

from _common import make_material, clear_scene
import build_steam_turbine


def load_config():
    override_path = os.environ.get("BLENDER_CONFIG_PATH", "")
    if override_path and os.path.exists(override_path):
        with open(override_path, "r", encoding="utf-8") as f:
            return json.load(f)

    b64 = os.environ.get("BLENDER_STEAM_TURBINE_JSON", "")
    if b64:
        return json.loads(base64.b64decode(b64).decode("utf-8"))

    # 默认使用 steam_turbine_building 项目自带配置
    default_path = os.path.join(
        _PROJECT_DIR, "projects", "steam_turbine_building", "data", "config.json"
    )
    with open(default_path, "r", encoding="utf-8") as f:
        return json.load(f)


def render_preview(out):
    """Render a viewport preview image using Eevee."""
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.image_settings.file_format = 'JPEG'
    scene.render.image_settings.quality = 85

    for cam_obj in bpy.data.objects:
        if cam_obj.type == 'CAMERA':
            scene.camera = cam_obj
            break

    preview_path = os.path.join(out, "preview.jpg")
    scene.render.filepath = preview_path
    bpy.ops.render.render(write_still=True)
    print(f"[PREVIEW] Rendered: {preview_path}")

    with open(preview_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("ascii")
    print(f"[PREVIEW_BASE64] {img_b64}")
    print(f"[PREVIEW_END]")


def main():
    config = load_config()
    output_dir = os.environ.get("BLENDER_OUTPUT_DIR", "")
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        build_steam_turbine.BLEND_OUTPUT = output_dir

    clear_scene()
    white_mat = make_material("WhiteModel", (0.92, 0.92, 0.92), roughness=0.6)
    ground_mat = make_material("Ground", (0.35, 0.28, 0.18), roughness=0.8)

    build_steam_turbine.setup_scene(config, ground_mat)
    build_steam_turbine.build(config, white_mat)
    build_steam_turbine.assign_type_colors()

    out = os.environ.get("BLENDER_OUTPUT_DIR",
        os.path.join(_PROJECT_DIR, "projects", "steam_turbine_building", "output", "blend"))
    os.makedirs(out, exist_ok=True)
    blend_path = os.path.join(out, "scene_base.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"\n[OK] 蒸汽轮机厂房白模已保存: {blend_path}")

    mesh_count = len([o for o in bpy.data.objects if o.type == 'MESH'])
    print(f"总构件数: {mesh_count}")

    render_preview(out)


if __name__ == "__main__":
    main()
