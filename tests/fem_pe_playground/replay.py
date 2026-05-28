"""
MuJoCo 快速回放：直接加载 frame_model.xml，跳过 FEM 重分析。
"""
import sys
import time
import numpy as np

try:
    import mujoco
    import mujoco.viewer
except ImportError:
    print("[ERROR] pip install mujoco")
    sys.exit(1)

xml_path = sys.argv[1] if len(sys.argv) > 1 else 'frame_model.xml'

try:
    model = mujoco.MjModel.from_xml_path(xml_path)
except Exception as e:
    print(f"[ERROR] 加载 {xml_path} 失败: {e}")
    sys.exit(1)

data = mujoco.MjData(model)

nq = model.nq
neq = model.neq

# 构建约束监测列表
monitor_list = []
for eq_idx in range(neq):
    if data.eq_active[eq_idx] == 0:
        continue
    b1 = int(model.eq_obj1id[eq_idx]) if hasattr(model, 'eq_obj1id') else -1
    b2 = int(model.eq_obj2id[eq_idx])
    relpose_xyz = np.array([model.eq_data[eq_idx][0],
                            model.eq_data[eq_idx][1],
                            model.eq_data[eq_idx][2]])
    monitor_list.append((eq_idx, b1, b2, relpose_xyz))

FRACTURE_THRESHOLD = 0.20

demolish_triggered = [False]
sim_done = [False]
replay_flag = [False]
speed_mult = [1.5]

def eq_id(name):
    return mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_EQUALITY, name)

def key_cb(key, mod):
    if key == 91:
        speed_mult[0] = min(5.0, round(speed_mult[0] + 0.5, 1))
        print(f"  [速度] {1/speed_mult[0]:.1f}x 实时 (倍率 {speed_mult[0]:.1f})")
        return True
    if key == 93:
        speed_mult[0] = max(0.1, round(speed_mult[0] - 0.5, 1))
        print(f"  [速度] {1/speed_mult[0]:.1f}x 实时 (倍率 {speed_mult[0]:.1f})")
        return True
    try:
        k = chr(key).lower()
    except:
        return False
    if k == 'd' and not demolish_triggered[0] and not sim_done[0]:
        demolish_triggered[0] = True
        print("\n  ==> [用户触发] 拆除所有底层柱!")
        count = 0
        for eq_idx in range(neq):
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_EQUALITY, eq_idx) or ""
            if name.startswith('base_'):
                data.eq_active[eq_idx] = 0
                count += 1
        print(f"    禁用了 {count} 个底层约束")
    if k == 'r' and sim_done[0]:
        replay_flag[0] = True
        print("\n  ==> 重播...")
        return True
    return False

def run_sim(step_fn):
    steady_steps = 250
    collapse_steps = 2500
    n_fractured = 0

    print("\n  稳态阶段 (~1s)...")
    for i in range(steady_steps):
        mujoco.mj_step(model, data)
        if not step_fn():
            return

    print("\n  >> [D] 拆除  [ ] 速度  [ESC] 退出")
    while not demolish_triggered[0]:
        mujoco.mj_step(model, data)
        if not step_fn():
            return

    print("\n  倒墔仿真 (10s)...")
    for i in range(collapse_steps):
        mujoco.mj_step(model, data)

        for eq_idx, b1, b2, rel_xyz in monitor_list:
            if data.eq_active[eq_idx] == 0:
                continue
            if b1 < 0 or b2 < 0:
                continue
            p1 = data.xpos[b1]
            R1 = np.array(data.xmat[b1]).reshape(3, 3)
            expected = p1 + R1 @ rel_xyz
            actual = data.xpos[b2]
            deviation = np.linalg.norm(actual - expected)
            if deviation > FRACTURE_THRESHOLD:
                data.eq_active[eq_idx] = 0
                n_fractured += 1
                print(f"    断裂 eq_idx={eq_idx} (偏差={deviation:.3f}m)")

        if not step_fn():
            break

    msg = f" (共 {n_fractured} 处自动断裂)" if n_fractured > 0 else ""
    print(f"\n  [OK] 仿真完成{msg}")

with mujoco.viewer.launch_passive(model, data) as viewer:
    viewer.key_callback = key_cb
    replay_flag[0] = True

    while replay_flag[0]:
        replay_flag[0] = False
        sim_done[0] = False
        demolish_triggered[0] = False
        mujoco.mj_resetData(model, data)

        def gui_step():
            viewer.sync()
            time.sleep(model.opt.timestep * speed_mult[0])
            return viewer.is_running()

        run_sim(gui_step)
        sim_done[0] = True

        print("\n  >> [R] 重播  [ ] 速度  [ESC] 退出")
        while viewer.is_running() and not replay_flag[0]:
            time.sleep(0.1)

print(f"\n  XML: {xml_path}")
