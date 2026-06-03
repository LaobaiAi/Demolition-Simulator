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
        from build_steam_turbine import animate_construction
        blend_path = os.path.join(OUTPUT_DIR, "scene_base.blend")
        if not os.path.exists(blend_path):
            print(f"  [ERROR] 缺少基础模型: {blend_path}")
            print(f"  请先运行: blender --background --python main.py")
            return
        # 如果已经在blender中打开了文件，直接执行
        animate_construction(config)
    else:
        print("  [模式] 建筑建模")
        from build_steam_turbine import build_model
        build_model(config)
        # 保存基础模型
        blend_path = os.path.join(OUTPUT_DIR, "scene_base.blend")
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        print(f"\n  [OK] 基础模型已保存: {blend_path}")


if __name__ == "__main__":
    main()
