"""
main.py - 汽轮机厂房项目入口脚本
用法:
    blender --background --python main.py           # 构建模型
    blender --background scene_base.blend --python main.py --animate  # 施工动画

项目结构:
    steam_turbine_building/
        data/
            config.json          # 项目配置
        output/
            blend/               # blender输出文件
        scripts/
            main.py              # 本文件 - 入口
            build_steam_turbine.py  # 建筑建模
"""

import bpy
import sys
import os
import json

# 将项目目录加入路径
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(PROJECT_DIR, "scripts")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output", "blend")

_PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_BLEND_SCRIPTS_DIR = os.path.join(_PIPELINE_DIR, "scripts")
if _BLEND_SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _BLEND_SCRIPTS_DIR)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)


def load_config():
    """加载项目配置"""
    config_path = os.path.join(DATA_DIR, "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_output_dir():
    """确保输出目录存在"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def main():
    config = load_config()
    ensure_output_dir()

    print("=" * 60)
    print(f"  汽轮机厂房 - {config['description']}")
    print("=" * 60)

    # 解析命令行参数
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []

    if "--animate" in args:
        print("  [模式] 施工动画")
        from animate_demolition import main as animate_main
        blend_path = os.path.join(OUTPUT_DIR, "scene_base.blend")
        if not os.path.exists(blend_path):
            print(f"  [ERROR] 缺少基础模型: {blend_path}")
            print(f"  请先运行: blender --background --python main.py")
            return
        animate_main()
    else:
        print("  [模式] 建筑建模")
        from _common import make_material, clear_scene
        from build_steam_turbine import build as build_model, setup_scene
        # clear_scene first, THEN create materials (avoid zero-user material removal)
        clear_scene()
        white_mat = make_material("WhiteModel", (0.92, 0.92, 0.92), roughness=0.6)
        ground_mat = make_material("Ground", (0.35, 0.28, 0.18), roughness=0.8)
        setup_scene(config, ground_mat)
        build_model(config, white_mat)
        # 保存基础模型
        blend_path = os.path.join(OUTPUT_DIR, "scene_base.blend")
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        print(f"\n  [OK] 基础模型已保存: {blend_path}")


if __name__ == "__main__":
    main()
