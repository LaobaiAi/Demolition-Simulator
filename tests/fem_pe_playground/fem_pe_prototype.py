"""
FEM-PE Hybrid Prototype: OpenSeesPy + MuJoCo
===============================================
三维一层一跨钢框架：OpenSeesPy 弹性分析 → 识别关键柱 → MuJoCo 物理倒塌模拟。

依赖安装:
  pip install openseespy numpy mujoco

执行:
  python fem_pe_prototype.py              # 仅 FEM 分析
  python fem_pe_prototype.py --physics    # FEM + MuJoCo 物理仿真

注: OpenSeesPy 需 Python 3.12+。推荐在项目 venv 中运行:
    .venv/Scripts/python tests/fem_pe_playground/fem_pe_prototype.py --physics
"""

import sys
import argparse
import math
import time

import numpy as np

# ── OpenSeesPy ──────────────────────────────────────────────────────────────
try:
    import openseespy.opensees as ops
except ImportError as e:
    print(f"[ERROR] OpenSeesPy 导入失败: {e}")
    print("请执行: pip install openseespy  (需 Python 3.12+)")
    sys.exit(1)

# ── MuJoCo (可选) ────────────────────────────────────────────────────────────
MUJOCO_AVAILABLE = False
try:
    import mujoco
    import mujoco.viewer
    MUJOCO_AVAILABLE = True
except ImportError:
    print("[WARN] MuJoCo 未安装 — 仅执行 FEM 分析部分")
    print("       pip install mujoco 后 --physics 可用\n")


# ============================================================================
#  第 1 部分: OpenSeesPy 结构建模与分析
# ============================================================================

def build_and_analyze(nx=2, ny=2, nz=3) -> dict:
    """建立多跨多层钢框架，静力分析，识别关键柱。"""
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)

    L, H = 4.0, 3.0  # bay width, story height

    E, G = 206e9, 79.3e9
    fy = 345e6

    # ── 柱截面: HW150×150 (GB/T 11263) ──
    A_col = 40.55e-4
    I_strong = 1660e-8
    I_weak  = 564e-8
    J_col = 1.0e-6
    Wpl_strong = 1.12 * 221e-6
    Wpl_weak   = 1.12 * 75.1e-6
    Py = A_col * fy
    Mp_strong = Wpl_strong * fy
    Mp_weak   = Wpl_weak * fy

    # ── 梁截面: HN150×75 (近似) ──
    Ab = 18.0e-4
    Iyb = 67.9e-8
    Izb = 955e-8
    Jb = 1.0e-7

    def nid(i, j, k):
        """Node ID: i in [0,nx], j in [0,ny], k in [0,nz]"""
        return k * (nx + 1) * (ny + 1) + j * (nx + 1) + i + 1

    node_coords = {}
    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx + 1):
                nd = nid(i, j, k)
                x = (i - nx / 2) * L
                y = (j - ny / 2) * L
                z = k * H
                ops.node(nd, x, y, z)
                node_coords[nd] = (x, y, z)

    # 固定基础节点 (k=0)
    for i in range(nx + 1):
        for j in range(ny + 1):
            ops.fix(nid(i, j, 0), 1, 1, 1, 1, 1, 1)

    ops.geomTransf('Linear', 1, 1, 0, 0)  # 柱
    ops.geomTransf('Linear', 2, 0, 0, 1)  # 梁

    elem_id = 0

    # 柱: (i,j,k) → (i,j,k+1)
    for k in range(nz):
        for j in range(ny + 1):
            for i in range(nx + 1):
                elem_id += 1
                ops.element('elasticBeamColumn', elem_id,
                            nid(i, j, k), nid(i, j, k + 1),
                            A_col, E, G, J_col, I_strong, I_weak, 1)

    # X 向梁: (i,j,k) → (i+1,j,k)
    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx):
                elem_id += 1
                ops.element('elasticBeamColumn', elem_id,
                            nid(i, j, k), nid(i + 1, j, k),
                            Ab, E, G, Jb, Iyb, Izb, 2)

    # Y 向梁: (i,j,k) → (i,j+1,k)
    for k in range(nz + 1):
        for j in range(ny):
            for i in range(nx + 1):
                elem_id += 1
                ops.element('elasticBeamColumn', elem_id,
                            nid(i, j, k), nid(i, j + 1, k),
                            Ab, E, G, Jb, Iyb, Izb, 2)

    # 刚性隔板: 每层耦合 UX/UY
    for k in range(1, nz + 1):
        master = nid(0, 0, k)
        for j in range(ny + 1):
            for i in range(nx + 1):
                slave = nid(i, j, k)
                if slave != master:
                    ops.equalDOF(master, slave, 1, 2)

    # 水平载荷: 10 kN 沿 X 作用于顶层所有节点
    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)
    for i in range(nx + 1):
        for j in range(ny + 1):
            ops.load(nid(i, j, nz), 10e3, 0.0, 0.0, 0.0, 0.0, 0.0)

    ops.system('BandGeneral')
    ops.numberer('RCM')
    ops.constraints('Transformation')
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')

    if ops.analyze(1) != 0:
        print("[ERROR] OpenSees 静力分析不收敛")
        raise RuntimeError("Static analysis failed")

    n_cols = (nx + 1) * (ny + 1) * nz
    n_beams = nx * (ny + 1) * (nz + 1) + (nx + 1) * ny * (nz + 1)
    print(f"[OK] 静力分析完成 ({n_cols} 柱, {n_beams} 梁)\n")

    critical_id, critical_ratio = -1, -1.0
    column_forces = []

    for col_id in range(1, n_cols + 1):
        f = ops.eleForce(col_id)
        P = f[2]
        Mx = f[3]
        My = f[4]
        ratio = abs(P) / Py + abs(Mx) / Mp_weak + abs(My) / Mp_strong
        # 柱 col_id 对应拓扑位置 (i,j,k)
        per_floor = (nx + 1) * (ny + 1)
        ck = (col_id - 1) // per_floor
        cj = ((col_id - 1) % per_floor) // (nx + 1)
        ci = (col_id - 1) % (nx + 1)
        label = f"C({ci},{cj},{ck})"
        column_forces.append({
            'id': col_id, 'P': P, 'Mx': Mx, 'My': My, 'ratio': ratio,
            'i': ci, 'j': cj, 'k': ck,
        })
        print(f"  {label:>10s}  |  P={P/1e3:>+7.1f} kN  "
              f"Mx={Mx/1e3:>+7.1f} kN-m  My={My/1e3:>+7.1f} kN-m  "
              f"ratio={ratio:.4f}")
        if ratio > critical_ratio:
            critical_id, critical_ratio = col_id, ratio

    ci = (critical_id - 1) % (nx + 1)
    cj = ((critical_id - 1) % ((nx + 1) * (ny + 1))) // (nx + 1)
    ck = (critical_id - 1) // ((nx + 1) * (ny + 1))
    crit_label = f"C({ci},{cj},{ck})"
    print(f"\n  ==> 关键柱: {crit_label} (ID={critical_id}, 应力比 {critical_ratio:.4f})")

    # 成员字典
    members = {}
    eid = 0
    for k in range(nz):
        for j in range(ny + 1):
            for i in range(nx + 1):
                eid += 1
                members[f'C_{i}_{j}_{k}'] = ('column', nid(i, j, k), nid(i, j, k + 1), eid)
    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx):
                eid += 1
                members[f'BX_{i}_{j}_{k}'] = ('beam', nid(i, j, k), nid(i + 1, j, k), eid)
    for k in range(nz + 1):
        for j in range(ny):
            for i in range(nx + 1):
                eid += 1
                members[f'BY_{i}_{j}_{k}'] = ('beam', nid(i, j, k), nid(i, j + 1, k), eid)

    return {
        'critical_column': critical_id,
        'critical_ratio': critical_ratio,
        'node_coords': node_coords,
        'members': members,
        'column_forces': column_forces,
        'nx': nx, 'ny': ny, 'nz': nz,
        'span': L, 'height': H,
    }


# ============================================================================
#  第 2 部分: MuJoCo 物理仿真
# ============================================================================

def gen_mujoco_xml(fem: dict, crit_pos: tuple, use_anchors: bool = False) -> str:
    """从 FEM 结果生成 MJCF 模型 XML。
    use_anchors=False: 直接焊接, body 数最少 (柱→世界/柱, 梁→柱)
    use_anchors=True:  anchor 中间体模式, body 多但连接关系更清晰
    """
    nx, ny, nz = fem['nx'], fem['ny'], fem['nz']
    L, H = fem['span'], fem['height']

    def is_crit_col(i, j, k):
        return (i, j, k) == crit_pos

    def cx(i):
        return (i - nx / 2) * L

    def cy(j):
        return (j - ny / 2) * L

    def cz(k):
        return k * H

    xml_parts = []
    xml_parts.append('<?xml version="1.0"?>')
    xml_parts.append(f'<mujoco model="frame_{nx}x{ny}x{nz}">')
    xml_parts.append('  <option gravity="0 0 -9.81" timestep="0.004"'
                     ' iterations="100" tolerance="1e-8"/>')
    xml_parts.append('  <size nconmax="2000" njmax="2000"/>')
    grid_size = max(8, (nx + 2) * L / 2)
    xml_parts.append(f'  <visual><global offwidth="1400" offheight="900"/></visual>')
    xml_parts.append('  <asset>')
    xml_parts.append('    <texture name="grid" type="2d" builtin="checker"'
                     ' width="512" height="512" rgb1=".15 .15 .15" rgb2=".25 .25 .25"/>')
    xml_parts.append('    <material name="grid" texture="grid"'
                     ' texrepeat="1 1" texuniform="true"/>')
    xml_parts.append('  </asset>')
    xml_parts.append('  <worldbody>')
    xml_parts.append(f'    <geom name="ground" type="plane" size="{grid_size} {grid_size} 0.1" material="grid"/>')

    if not use_anchors:
        # 固定地锚 (无 joint → 固定在世界上)
        for j in range(ny + 1):
            for i in range(nx + 1):
                x, y = cx(i), cy(j)
                xml_parts.append(f'    <body name="G_{i}_{j}" pos="{x} {y} 0">')
                xml_parts.append(f'      <geom type="sphere" size="0.01" rgba="0 0 0 0"/>')
                xml_parts.append(f'    </body>')

    col_half_h = H / 2

    if use_anchors:
        # ── Anchor 模式: 每个节点一个 anchor 中间体 ──
        for k in range(nz + 1):
            for j in range(ny + 1):
                for i in range(nx + 1):
                    x, y, z = cx(i), cy(j), cz(k)
                    xml_parts.append(f'    <body name="A_{i}_{j}_{k}" pos="{x} {y} {z}">')
                    xml_parts.append(f'      <freejoint/>')
                    xml_parts.append(f'      <geom type="sphere" size="0.02" rgba="0 0 0 0"/>')
                    xml_parts.append(f'    </body>')
        # 柱
        for k in range(nz):
            for j in range(ny + 1):
                for i in range(nx + 1):
                    x, y, z = cx(i), cy(j), cz(k) + col_half_h
                    is_crit = is_crit_col(i, j, k)
                    r, g, b = (1, 0.2, 0.2) if is_crit else (0.7, 0.7, 0.7)
                    xml_parts.append(f'    <body name="C_{i}_{j}_{k}" pos="{x} {y} {z}">')
                    xml_parts.append(f'      <freejoint/>')
                    xml_parts.append(f'      <geom type="box" size="0.075 0.075 {col_half_h}"'
                                     f' rgba="{r} {g} {b} 1" contype="0" conaffinity="1"/>')
                    xml_parts.append(f'    </body>')
        # X 梁
        for k in range(nz + 1):
            for j in range(ny + 1):
                for i in range(nx):
                    x, y, z = cx(i) + L / 2, cy(j), cz(k)
                    xml_parts.append(f'    <body name="BX_{i}_{j}_{k}" pos="{x} {y} {z}">')
                    xml_parts.append(f'      <freejoint/>')
                    xml_parts.append(f'      <geom type="box" size="{L/2} 0.0375 0.075"'
                                     f' rgba="0.3 0.3 0.3 1" contype="0" conaffinity="1"/>')
                    xml_parts.append(f'    </body>')
        # Y 梁
        for k in range(nz + 1):
            for j in range(ny):
                for i in range(nx + 1):
                    x, y, z = cx(i), cy(j) + L / 2, cz(k)
                    xml_parts.append(f'    <body name="BY_{i}_{j}_{k}" pos="{x} {y} {z}">')
                    xml_parts.append(f'      <freejoint/>')
                    xml_parts.append(f'      <geom type="box" size="0.0375 {L/2} 0.075"'
                                     f' rgba="0.3 0.3 0.3 1" contype="0" conaffinity="1"/>')
                    xml_parts.append(f'    </body>')
    else:
        # ── 直接焊接模式: 无 anchor，柱/梁直接带 freejoint ──
        for k in range(nz):
            for j in range(ny + 1):
                for i in range(nx + 1):
                    x, y, z = cx(i), cy(j), cz(k) + col_half_h
                    is_crit = is_crit_col(i, j, k)
                    r, g, b = (1, 0.2, 0.2) if is_crit else (0.7, 0.7, 0.7)
                    xml_parts.append(f'    <body name="C_{i}_{j}_{k}" pos="{x} {y} {z}">')
                    xml_parts.append(f'      <freejoint/>')
                    xml_parts.append(f'      <geom type="box" size="0.075 0.075 {col_half_h}"'
                                     f' rgba="{r} {g} {b} 1" contype="0" conaffinity="1"/>')
                    xml_parts.append(f'    </body>')
        for k in range(nz + 1):
            for j in range(ny + 1):
                for i in range(nx):
                    x, y, z = cx(i) + L / 2, cy(j), cz(k)
                    xml_parts.append(f'    <body name="BX_{i}_{j}_{k}" pos="{x} {y} {z}">')
                    xml_parts.append(f'      <freejoint/>')
                    xml_parts.append(f'      <geom type="box" size="{L/2} 0.0375 0.075"'
                                     f' rgba="0.3 0.3 0.3 1" contype="0" conaffinity="1"/>')
                    xml_parts.append(f'    </body>')
        for k in range(nz + 1):
            for j in range(ny):
                for i in range(nx + 1):
                    x, y, z = cx(i), cy(j) + L / 2, cz(k)
                    xml_parts.append(f'    <body name="BY_{i}_{j}_{k}" pos="{x} {y} {z}">')
                    xml_parts.append(f'      <freejoint/>')
                    xml_parts.append(f'      <geom type="box" size="0.0375 {L/2} 0.075"'
                                     f' rgba="0.3 0.3 0.3 1" contype="0" conaffinity="1"/>')
                    xml_parts.append(f'    </body>')

    xml_parts.append('  </worldbody>')

    xml_parts.append('  <equality>')

    if use_anchors:
        for k in range(nz):
            for j in range(ny + 1):
                for i in range(nx + 1):
                    xml_parts.append(f'    <weld name="base_{i}_{j}_{k}"'
                                     f' body1="A_{i}_{j}_{k}" body2="C_{i}_{j}_{k}"'
                                     f' relpose="0 0 {H/2} 1 0 0 0"/>')
        for k in range(nz):
            for j in range(ny + 1):
                for i in range(nx + 1):
                    xml_parts.append(f'    <weld name="top_{i}_{j}_{k}"'
                                     f' body1="C_{i}_{j}_{k}" body2="A_{i}_{j}_{k+1}"'
                                     f' relpose="0 0 {H/2} 1 0 0 0"/>')
        for k in range(nz + 1):
            for j in range(ny + 1):
                for i in range(nx):
                    xml_parts.append(f'    <weld name="bx_{i}_{j}_{k}_i"'
                                     f' body1="BX_{i}_{j}_{k}" body2="A_{i}_{j}_{k}"'
                                     f' relpose="{-L/2} 0 0 1 0 0 0"/>')
                    xml_parts.append(f'    <weld name="bx_{i}_{j}_{k}_j"'
                                     f' body1="BX_{i}_{j}_{k}" body2="A_{i+1}_{j}_{k}"'
                                     f' relpose="{L/2} 0 0 1 0 0 0"/>')
        for k in range(nz + 1):
            for j in range(ny):
                for i in range(nx + 1):
                    xml_parts.append(f'    <weld name="by_{i}_{j}_{k}_i"'
                                     f' body1="BY_{i}_{j}_{k}" body2="A_{i}_{j}_{k}"'
                                     f' relpose="0 {-L/2} 0 1 0 0 0"/>')
                    xml_parts.append(f'    <weld name="by_{i}_{j}_{k}_j"'
                                     f' body1="BY_{i}_{j}_{k}" body2="A_{i}_{j+1}_{k}"'
                                     f' relpose="0 {L/2} 0 1 0 0 0"/>')
    else:
        for j in range(ny + 1):
            for i in range(nx + 1):
                x, y, z = cx(i), cy(j), col_half_h
                xml_parts.append(f'    <weld name="base_{i}_{j}_0"'
                                 f' body1="G_{i}_{j}" body2="C_{i}_{j}_0"'
                                 f' relpose="0 0 {col_half_h} 1 0 0 0"/>')
        for k in range(1, nz):
            for j in range(ny + 1):
                for i in range(nx + 1):
                    xml_parts.append(f'    <weld name="col_{i}_{j}_{k}"'
                                     f' body1="C_{i}_{j}_{k-1}" body2="C_{i}_{j}_{k}"'
                                     f' relpose="0 0 {H} 1 0 0 0"/>')
        for k in range(nz + 1):
            col_k = max(0, k - 1) if k > 0 else 0
            for j in range(ny + 1):
                for i in range(nx):
                    dx_i, dz_i = L / 2, cz(k) - (cz(col_k) + col_half_h)
                    xml_parts.append(f'    <weld name="bx_{i}_{j}_{k}_i"'
                                     f' body1="C_{i}_{j}_{col_k}" body2="BX_{i}_{j}_{k}"'
                                     f' relpose="{dx_i} 0 {dz_i} 1 0 0 0"/>')
                    dx_j, dz_j = -L / 2, cz(k) - (cz(col_k) + col_half_h)
                    xml_parts.append(f'    <weld name="bx_{i}_{j}_{k}_j"'
                                     f' body1="C_{i+1}_{j}_{col_k}" body2="BX_{i}_{j}_{k}"'
                                     f' relpose="{dx_j} 0 {dz_j} 1 0 0 0"/>')
        for k in range(nz + 1):
            col_k = max(0, k - 1) if k > 0 else 0
            for j in range(ny):
                for i in range(nx + 1):
                    dy_i, dz_i = L / 2, cz(k) - (cz(col_k) + col_half_h)
                    xml_parts.append(f'    <weld name="by_{i}_{j}_{k}_i"'
                                     f' body1="C_{i}_{j}_{col_k}" body2="BY_{i}_{j}_{k}"'
                                     f' relpose="0 {dy_i} {dz_i} 1 0 0 0"/>')
                    dy_j, dz_j = -L / 2, cz(k) - (cz(col_k) + col_half_h)
                    xml_parts.append(f'    <weld name="by_{i}_{j}_{k}_j"'
                                     f' body1="C_{i}_{j+1}_{col_k}" body2="BY_{i}_{j}_{k}"'
                                     f' relpose="0 {dy_j} {dz_j} 1 0 0 0"/>')

    xml_parts.append('  </equality>')
    xml_parts.append('</mujoco>')
    return '\n'.join(xml_parts)


def run_mujoco(fem: dict, enable_fracture: bool = False, show_gui: bool = True, use_anchors: bool = False):
    """生成 MuJoCo 模型并执行实时物理仿真。"""
    if not MUJOCO_AVAILABLE:
        print("[SKIP] pip install mujoco 后重试")
        return

    crit_col = fem['critical_column']
    nx, ny, nz = fem['nx'], fem['ny'], fem['nz']
    per_floor = (nx + 1) * (ny + 1)
    ck = (crit_col - 1) // per_floor
    cj = ((crit_col - 1) % per_floor) // (nx + 1)
    ci = (crit_col - 1) % (nx + 1)
    crit_pos = (ci, cj, ck)

    print(f"\n  生成 MuJoCo 模型 ({nx}x{ny}x{nz} 框架)...")
    xml = gen_mujoco_xml(fem, crit_pos, use_anchors=use_anchors)

    # 保存 XML
    xml_path = 'frame_model.xml'
    with open(xml_path, 'w') as f:
        f.write(xml)

    # 加载模型
    try:
        model = mujoco.MjModel.from_xml_string(xml)
    except Exception as e:
        print(f"[ERROR] MuJoCo 模型加载失败: {e}")
        print("  XML 已保存到 frame_model.xml 供调试")
        return

    data = mujoco.MjData(model)

    # 通过名称查找约束索引
    def eq_id(name: str) -> int:
        return mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_EQUALITY, name)

    print(f"\n  约束数量: {model.neq}")
    for i in range(model.neq):
        print(f"    {i}")

    if use_anchors:
        crit_names = [f'base_{ci}_{cj}_{ck}', f'top_{ci}_{cj}_{ck}']
    elif ck == 0:
        crit_names = [f'base_{ci}_{cj}_0']
    else:
        crit_names = [f'col_{ci}_{cj}_{ck}']

    crit_eq_ids = []
    for name in crit_names:
        idx = eq_id(name)
        if idx >= 0:
            crit_eq_ids.append(idx)
            print(f"\n  ==> 标记关键柱约束: {name} (idx={idx})")
        else:
            print(f"\n  [WARN] 未找到约束: {name}")

    # ── 构建约束监测列表 ──
    # 对每个 weld equality, 记录 (eq_idx, body1_id, body2_id, relpose_xyz)
    monitor_list = []
    for eq_idx in range(model.neq):
        if data.eq_active[eq_idx] == 0:
            continue
        # eq_obj1/2 存储 body ID (对 weld 约束)
        b1 = int(model.eq_obj1id[eq_idx]) if hasattr(model, 'eq_obj1id') else -1
        b2 = int(model.eq_obj2id[eq_idx])
        # relpose: eq_data 中前 7 个值 [x, y, z, qw, qx, qy, qz]
        relpose_xyz = np.array([model.eq_data[eq_idx][0],
                                model.eq_data[eq_idx][1],
                                model.eq_data[eq_idx][2]])
        monitor_list.append((eq_idx, b1, b2, relpose_xyz))

    FRACTURE_THRESHOLD = 0.20  # m — 相对位移超过此值则自动断裂

    demolish_triggered = [False]  # 使用 list 以便在回调中修改
    sim_done = [False]
    replay_flag = [False]
    speed_mult = [1.5]  # 播放速度倍率: 1.0=实时, >1=慢, <1=快

    def key_cb(key, mod):
        """MuJoCo viewer 按键回调"""
        # 速度控制: [ 减速, ] 加速
        if key == 91:  # GLFW [
            speed_mult[0] = min(5.0, round(speed_mult[0] + 0.5, 1))
            print(f"  [速度] {1/speed_mult[0]:.1f}x 实时 (倍率 {speed_mult[0]:.1f})")
            return True
        if key == 93:  # GLFW ]
            speed_mult[0] = max(0.1, round(speed_mult[0] - 0.5, 1))
            print(f"  [速度] {1/speed_mult[0]:.1f}x 实时 (倍率 {speed_mult[0]:.1f})")
            return True
        try:
            k = chr(key).lower()
        except (ValueError, OverflowError):
            return False
        if k == 'd' and not demolish_triggered[0] and not sim_done[0]:
            demolish_triggered[0] = True
            print("\n  ==> [用户触发] 拆除关键柱!")
            for eq_id in crit_eq_ids:
                data.eq_active[eq_id] = 0
                print(f"    禁用约束 idx={eq_id}")
            return True
        if k == 'r' and sim_done[0]:
            replay_flag[0] = True
            print("\n  ==> 重播...")
            return True
        return False

    # ── 仿真函数 (GUI/无GUI共用) ──
    def run_sim(step_fn):
        """step_fn(n) 每步调用, n=步数; 返回 True 继续, False 中断"""
        steady_steps = 250
        mode_str = "含自动断裂检测" if enable_fracture else "仅重力倒塌"
        collapse_steps = 2500
        n_fractured = 0

        print("\n  稳态阶段 (~1s)...")
        for i in range(steady_steps):
            mujoco.mj_step(model, data)
            if not step_fn(True):
                return
            if i % 50 == 0 and not show_gui:
                print(f"    稳定中... {i*model.opt.timestep:.2f}s")

        if not show_gui:
            print("  [OK] 已稳定")

        # 等待用户按键触发拆除
        print("\n  >> [D] 拆除  [ ] 速度  [ESC] 退出")
        while not demolish_triggered[0]:
            mujoco.mj_step(model, data)
            if not step_fn(True):
                return
            if show_gui:
                pass  # viewer loop 已在 step_fn 中同步
            else:
                time.sleep(0.01)  # 非 GUI 模式不空转 CPU

        # 倒塌仿真
        print(f"\n  倒塌仿真 ({mode_str}, 10s)...")
        for i in range(collapse_steps):
            mujoco.mj_step(model, data)

            if enable_fracture:
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

            if not step_fn(True):
                break
            if i % 250 == 0 and not show_gui:
                status = f"累计断裂{n_fractured}" if enable_fracture else ""
                print(f"    {i*model.opt.timestep:.1f}s / 10.0s  {status}")

        msg = f" (共 {n_fractured} 处自动断裂)" if enable_fracture else ""
        print(f"\n  [OK] 仿真完成{msg}")

    # ── 执行 ──
    if show_gui:
        try:
            with mujoco.viewer.launch_passive(model, data) as viewer:
                viewer.key_callback = key_cb
                replay_flag[0] = True

                while replay_flag[0]:
                    replay_flag[0] = False
                    sim_done[0] = False
                    demolish_triggered[0] = False
                    mujoco.mj_resetData(model, data)

                    def gui_step(_):
                        viewer.sync()
                        time.sleep(model.opt.timestep * speed_mult[0])
                        return viewer.is_running()

                    run_sim(gui_step)
                    sim_done[0] = True

                    print("\n  >> [R] 重播  [ ] 速度  [ESC] 退出")
                    while viewer.is_running() and not replay_flag[0]:
                        time.sleep(0.1)
        except ImportError:
            print("[WARN] mujoco.viewer 不可用，回退到无 GUI 模式")
            print("       pip install mujoco 确保版本完整")
            demolish_triggered[0] = True
            run_sim(lambda _: True)
    else:
        demolish_triggered[0] = True
        run_sim(lambda _: True)

    print(f"  XML 模型已保存至: {xml_path}")


# ============================================================================
#  主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='FEM-PE Hybrid Prototype')
    parser.add_argument('--physics', action='store_true',
                       help='运行 MuJoCo 物理仿真 (默认仅 FEM 分析)')
    parser.add_argument('--fracture', action='store_true',
                       help='开启自动断裂扩展 (需 --physics, 默认关闭)')
    parser.add_argument('--no-gui', action='store_true',
                       help='无 GUI 模式 (仅命令行输出，不打开 3D 窗口)')
    parser.add_argument('--mode', type=str, default='weld', choices=['weld', 'anchor'],
                       help='焊接模式: weld=直接焊接(默认), anchor=anchor中间体')
    parser.add_argument('--nx', type=int, default=2,
                       help='X 方向跨数 (默认 2)')
    parser.add_argument('--ny', type=int, default=2,
                       help='Y 方向跨数 (默认 2)')
    parser.add_argument('--nz', type=int, default=3,
                       help='层数 (默认 3)')
    args = parser.parse_args()

    print("=" * 50)
    print(f"  FEM-PE 混合原型验证  ({args.nx}x{args.ny}x{args.nz})")
    print("  OpenSeesPy (FEM) + MuJoCo (Physics)")
    print("=" * 50)

    print("\n[Phase 1] OpenSeesPy 结构分析")
    print("-" * 30)
    fem = build_and_analyze(nx=args.nx, ny=args.ny, nz=args.nz)

    if args.physics:
        print(f"\n[Phase 2] MuJoCo 物理仿真")
        print("-" * 30)
        run_mujoco(fem, enable_fracture=args.fracture,
                      show_gui=not args.no_gui,
                      use_anchors=(args.mode == 'anchor'))
    else:
        print(f"\n[Phase 2] 跳过 (加 --physics 运行仿真)")
        print("-" * 30)

    print("\n" + "=" * 50)
    print("  完成")
    print("=" * 50)


if __name__ == '__main__':
    main()
