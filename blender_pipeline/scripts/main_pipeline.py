"""
main_pipeline.py - 钢筋混凝土框架拆除动画制作总控脚本
v3.0: OpenGL渲染 + 项目目录隔离 + 拆除模式

用法:
    python main_pipeline.py --run-all              # 完整流程(默认批量拆除)
    python main_pipeline.py --run-all --machinery   # 含机械
    python main_pipeline.py --stage build|animate|machine|render
    python main_pipeline.py --check
"""

import subprocess, os, sys, json, argparse, time, shutil
from datetime import datetime

BLENDER_PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BLENDER_PIPELINE_DIR, "data")
OUTPUT_BASE = os.path.join(BLENDER_PIPELINE_DIR, "output")

SCRIPT_DIR = os.path.join(BLENDER_PIPELINE_DIR, "scripts")

def _find_blender():
    exe = os.environ.get("BLENDER_EXE", "")
    if exe and os.path.exists(exe):
        return exe
    portable = os.path.join(BLENDER_PIPELINE_DIR, "blender_portable", "blender-4.2.8-windows-x64", "blender.exe")
    if os.path.exists(portable):
        return portable
    for p in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(p, "blender.exe")
        if os.path.exists(candidate):
            return candidate
    return None

BLENDER_EXE = _find_blender()


def load_config():
    with open(os.path.join(DATA_DIR, "project_config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def make_project_dir():
    """创建项目时间戳目录"""
    config = load_config()
    name = config.get("project_name", "demolition").replace(" ", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    proj_dir = os.path.join(OUTPUT_BASE, f"{name}_{ts}")
    os.makedirs(proj_dir, exist_ok=True)
    blend_dir = os.path.join(proj_dir, "blend")
    os.makedirs(blend_dir, exist_ok=True)
    return proj_dir, blend_dir


def check_environment():
    print("=" * 60)
    print("  环境检查")
    print("=" * 60)
    if not os.path.exists(BLENDER_EXE):
        print(f"  [ERROR] Blender未找到: {BLENDER_EXE}")
        return False
    r = subprocess.run([BLENDER_EXE, "--version"], capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')
    if r.returncode == 0:
        print(f"  [OK] {r.stdout.strip().split(chr(10))[0]}")
    else:
        print(f"  [ERROR] Blender运行失败")
        return False
    for fn in ["project_config.json", "building_description.txt"]:
        fp = os.path.join(DATA_DIR, fn)
        print(f"  {'[OK]' if os.path.exists(fp) else '[MISS]'} {fn}")
    config = load_config()
    stg = config.get("demolition_strategy", {})
    print(f"  [INFO] 拆除模式: {stg.get('demolition_mode','by_floor_type')}")
    print(f"  [INFO] 机械: {'启用' if config.get('machinery',{}).get('enabled') else '禁用'}")
    print("  环境OK\n")
    return True


def run_blender(script_name, blend_input=None, stage_name="", background=True):
    script_path = os.path.join(SCRIPT_DIR, script_name)
    if not os.path.exists(script_path):
        print(f"  [ERROR] 脚本不存在: {script_path}")
        return False
    cmd = [BLENDER_EXE]
    if background:
        cmd.append("--background")
    if blend_input and os.path.exists(blend_input):
        cmd.append(blend_input)
    cmd.extend(["--python", script_path])
    print(f"\n  -- {stage_name or script_name} --")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, encoding='utf-8', errors='replace')
        if r.stdout:
            for line in r.stdout.split('\n'):
                line = line.strip()
                if line and 'Append frame' not in line and 'Time:' not in line:
                    print(f"    {line}")
        if r.returncode == 0:
            print(f"  [OK] {stage_name or script_name} 完成")
            return True
        else:
            print(f"  [ERROR] 返回码: {r.returncode}")
            if r.stderr:
                for line in r.stderr.split('\n')[:10]:
                    if line.strip():
                        print(f"    [ERR] {line.strip()}")
            return False
    except subprocess.TimeoutExpired:
        print(f"  [ERROR] 超时")
        return False
    except Exception as e:
        print(f"  [ERROR] 异常: {e}")
        return False


def get_paths():
    """获取当前项目的路径"""
    proj_dir, blend_dir = make_project_dir()
    return proj_dir, blend_dir


def stage_build(blend_dir):
    # 通过环境变量传递输出目录
    env = os.environ.copy()
    env["BLEND_OUTPUT_DIR"] = blend_dir
    script_path = os.path.join(SCRIPT_DIR, "generate_building.py")
    cmd = [BLENDER_EXE, "--background", "--python", script_path]
    print(f"\n  -- 建筑建模 --")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding='utf-8', errors='replace', env=env)
    if r.stdout:
        for line in r.stdout.split('\n'):
            line = line.strip()
            if line:
                print(f"    {line}")
    ok = r.returncode == 0
    print(f"  {'[OK]' if ok else '[FAIL]'} 建筑建模")
    return ok


def stage_animate(blend_dir):
    blend = os.path.join(blend_dir, "scene_base.blend")
    if not os.path.exists(blend):
        print(f"  [ERROR] 缺少: {blend}")
        return False
    env = os.environ.copy()
    env["BLEND_OUTPUT_DIR"] = blend_dir
    script_path = os.path.join(SCRIPT_DIR, "apply_demolition.py")
    cmd = [BLENDER_EXE, "--background", blend, "--python", script_path]
    print(f"\n  -- 拆除动画 --")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, encoding='utf-8', errors='replace', env=env)
    if r.stdout:
        for line in r.stdout.split('\n'):
            line = line.strip()
            if line:
                print(f"    {line}")
    ok = r.returncode == 0
    print(f"  {'[OK]' if ok else '[FAIL]'} 拆除动画")
    return ok


def stage_machine(blend_dir):
    config = load_config()
    if not config.get("machinery", {}).get("enabled", False):
        print("  [SKIP] 机械已禁用")
        src = os.path.join(blend_dir, "scene_animated.blend")
        dst = os.path.join(blend_dir, "scene_final.blend")
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  [OK] scene_final.blend (无机械)")
            return True
        return False
    blend = os.path.join(blend_dir, "scene_animated.blend")
    if not os.path.exists(blend):
        print(f"  [ERROR] 缺少: {blend}")
        return False
    env = os.environ.copy()
    env["BLEND_OUTPUT_DIR"] = blend_dir
    script_path = os.path.join(SCRIPT_DIR, "add_machinery.py")
    cmd = [BLENDER_EXE, "--background", blend, "--python", script_path]
    print(f"\n  -- 施工机械 --")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding='utf-8', errors='replace', env=env)
    if r.stdout:
        for line in r.stdout.split('\n'):
            line = line.strip()
            if line:
                print(f"    {line}")
    ok = r.returncode == 0
    print(f"  {'[OK]' if ok else '[FAIL]'} 施工机械")
    return ok


def stage_render(blend_dir):
    blend = os.path.join(blend_dir, "scene_final.blend")
    if not os.path.exists(blend):
        print(f"  [ERROR] 缺少: {blend}")
        return False
    script_path = os.path.join(SCRIPT_DIR, "render.py")
    cmd = [BLENDER_EXE, blend, "--python", script_path]  # 不加 --background，用UI模式
    print(f"\n  -- 渲染输出 (UI模式) --")
    print(f"  启动Blender窗口渲染，请勿关闭...")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, encoding='utf-8', errors='replace')
        if r.stdout:
            for line in r.stdout.split('\n'):
                line = line.strip()
                if line and 'Append frame' not in line and 'Time:' not in line:
                    print(f"    {line}")
        ok = r.returncode == 0
        print(f"  {'[OK]' if ok else '[FAIL]'} 渲染输出")
        return ok
    except subprocess.TimeoutExpired:
        print(f"  [ERROR] 渲染超时(20分钟)")
        return False
    except Exception as e:
        print(f"  [ERROR] 异常: {e}")
        return False


def run_all(with_machinery=False, with_render=False):
    if with_machinery:
        config = load_config()
        config["machinery"]["enabled"] = True
        with open(os.path.join(DATA_DIR, "project_config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print("  [INFO] 已启用机械")
    else:
        config = load_config()
        config["machinery"]["enabled"] = False
        with open(os.path.join(DATA_DIR, "project_config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    if with_render:
        config = load_config()
        config["render_enabled"] = True
        with open(os.path.join(DATA_DIR, "project_config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    proj_dir, blend_dir = make_project_dir()
    render_enabled = load_config().get("render_enabled", False)
    print(f"\n  项目目录: {proj_dir}")
    config = load_config()
    mode = config.get("demolition_strategy", {}).get("demolition_mode", "by_floor_type")
    print(f"  拆除模式: {mode} | 机械: {'开' if config.get('machinery',{}).get('enabled') else '关'} | 渲染: {'开' if render_enabled else '关'}")

    all_stages = [
        ("建筑建模", lambda: stage_build(blend_dir)),
        ("拆除动画", lambda: stage_animate(blend_dir)),
        ("施工机械", lambda: stage_machine(blend_dir)),
    ]
    if render_enabled:
        all_stages.append(("渲染输出", lambda: stage_render(blend_dir)))
    else:
        print("  [INFO] 渲染已跳过 (加 --render 启用)")

    print("\n" + "=" * 60)
    print("  全流程执行")
    print("=" * 60)
    start = time.time()
    results = {}
    for name, func in all_stages:
        print(f"\n{'─' * 50}")
        print(f"  >>> {name}")
        print(f"{'─' * 50}")
        ok = func()
        results[name] = ok
        if not ok:
            print(f"\n  [FAIL] {name} 失败，终止")
            break
        time.sleep(1)

    elapsed = time.time() - start
    print("\n" + "=" * 60)
    print("  执行总结")
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {'[OK]' if ok else '[FAIL]'}  {name}")
    if all(results.values()):
        print(f"\n  全部完成! 耗时: {elapsed:.0f}秒")
        print(f"  输出目录: {proj_dir}")
        for f in sorted(os.listdir(proj_dir)):
            fpath = os.path.join(proj_dir, f)
            sz = os.path.getsize(fpath) / 1024 / 1024 if os.path.isfile(fpath) else 0
            if sz > 0:
                print(f"    {f} ({sz:.1f}MB)")
        # 找视频文件
        for root, dirs, files in os.walk(proj_dir):
            for fn in files:
                if fn.endswith('.mp4'):
                    print(f"\n  >>> 视频: {os.path.join(root, fn)}")
    else:
        print("\n  部分失败，请检查日志")
    return all(results.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="钢筋混凝土框架拆除动画制作")
    parser.add_argument("--run-all", action="store_true", help="完整流程")
    parser.add_argument("--machinery", action="store_true", help="启用机械")
    parser.add_argument("--render", action="store_true", help="启用渲染(默认关闭)")
    parser.add_argument("--stage", choices=["build", "animate", "machine", "render"], help="单阶段")
    parser.add_argument("--check", action="store_true", help="环境检查")
    args = parser.parse_args()

    if not check_environment():
        sys.exit(1)
    if args.check:
        sys.exit(0)

    if args.run_all:
        success = run_all(with_machinery=args.machinery, with_render=args.render)
        sys.exit(0 if success else 1)
    elif args.stage:
        proj_dir, blend_dir = make_project_dir()
        print(f"  项目目录: {proj_dir}")
        stage_map = {
            "build": lambda: stage_build(blend_dir),
            "animate": lambda: stage_animate(blend_dir),
            "machine": lambda: stage_machine(blend_dir),
            "render": lambda: stage_render(blend_dir),
        }
        success = stage_map[args.stage]()
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
        print("\n示例:")
        print("  python main_pipeline.py --check")
        print("  python main_pipeline.py --run-all")
        print("  python main_pipeline.py --run-all --machinery")
