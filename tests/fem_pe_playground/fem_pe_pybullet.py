"""
FEM-PE Hybrid Prototype: OpenSeesPy + PyBullet
===============================================
三维一层一跨钢框架：OpenSeesPy 弹性分析 → 识别关键柱 → PyBullet 物理倒塌模拟。

依赖安装:
  pip install openseespy numpy
  pip install pybullet    # Windows 需 MSVC Build Tools

执行:
  python fem_pe_pybullet.py              # 仅 FEM 分析
  python fem_pe_pybullet.py --physics    # FEM + PyBullet 物理仿真

注: OpenSeesPy 需 Python 3.12+。推荐在项目 venv 中运行:
    .venv/Scripts/python tests/fem_pe_playground/fem_pe_pybullet.py --physics
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

# ── PyBullet (可选) ─────────────────────────────────────────────────────────
PYBULLET_AVAILABLE = False
try:
    import pybullet as p
    import pybullet_data
    PYBULLET_AVAILABLE = True
except ImportError:
    print("[WARN] PyBullet 未安装 — 仅执行 FEM 分析部分")
    print("       Windows 需 MSVC Build Tools: pip install pybullet\n")


# ============================================================================
#  第 1 部分: OpenSeesPy 结构建模与分析
# ============================================================================

def build_and_analyze() -> dict:
    """建立三维一层一跨钢框架，静力分析，识别关键柱，提取几何数据。"""
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)

    L, H = 4.0, 3.0
    coords_2d = [(-L/2, -L/2), (L/2, -L/2), (L/2, L/2), (-L/2, L/2)]

    E, G = 206e9, 79.3e9
    fy = 345e6

    # ── 柱截面: HW150×150 (GB/T 11263) ──
    # 腹板平行于 XZ 平面 → 强轴(=Y方向)抵抗 X 向弯曲
    A_col = 40.55e-4       # m²
    I_strong = 1660e-8     # m⁴ (绕强轴 = 局部 y = 全局 Y)
    I_weak  = 564e-8       # m⁴ (绕弱轴 = 局部 z = 全局 X)
    J_col = 1.0e-6         # m⁴ 扭转常数 (近似)
    # 全塑性模量 (简化: Wpl ≈ 1.12 × Wel)
    Wpl_strong = 1.12 * 221e-6   # m³ → 247.5 cm³
    Wpl_weak   = 1.12 * 75.1e-6  # m³ → 84.1 cm³
    Py = A_col * fy
    Mp_strong = Wpl_strong * fy   # 抵抗 My_global (绕全局 Y)
    Mp_weak   = Wpl_weak * fy     # 抵抗 Mx_global (绕全局 X)

    # ── 梁截面: HN150×75 (近似) ──
    Ab = 18.0e-4    # m² (≈ 18 cm²)
    Iyb = 67.9e-8   # m⁴ (弱轴, 绕局部 y)
    Izb = 955e-8    # m⁴ (强轴, 绕局部 z)
    Jb = 1.0e-7     # m⁴ (扭转常数近似)

    for i, (x, y) in enumerate(coords_2d, start=1):
        ops.node(i, x, y, 0.0)
        ops.node(i + 4, x, y, H)
    node_coords = {}
    for i, (x, y) in enumerate(coords_2d, start=1):
        node_coords[i] = (x, y, 0.0)
        node_coords[i + 4] = (x, y, H)

    for i in range(1, 5):
        ops.fix(i, 1, 1, 1, 1, 1, 1)

    # 柱: vecxz=(1,0,0)
    ops.geomTransf('Linear', 1, 1, 0, 0)
    for i in range(4):
        ops.element('elasticBeamColumn', i + 1, i + 1, i + 5,
                     A_col, E, G, J_col, I_strong, I_weak, 1)

    # 梁: vecxz=(0,0,1)
    ops.geomTransf('Linear', 2, 0, 0, 1)
    beam_map = {5: (5, 6), 6: (8, 7), 7: (5, 8), 8: (6, 7)}
    for eid, (ni, nj) in beam_map.items():
        ops.element('elasticBeamColumn', eid, ni, nj,
                     Ab, E, G, Jb, Iyb, Izb, 2)

    # 刚性隔板: equalDOF 耦合柱顶 UX/UY
    ops.equalDOF(5, 6, 1, 2)
    ops.equalDOF(5, 7, 1, 2)
    ops.equalDOF(5, 8, 1, 2)

    # 载荷: 10 kN 沿 X 作用于柱顶
    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)
    ops.load(5, 10e3, 0.0, 0.0, 0.0, 0.0, 0.0)

    ops.system('BandGeneral')
    ops.numberer('RCM')
    ops.constraints('Transformation')
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')

    if ops.analyze(1) != 0:
        print("[ERROR] OpenSees 静力分析不收敛")
        raise RuntimeError("Static analysis failed")

    print("[OK] 静力分析完成\n")

    critical_id, critical_ratio = -1, -1.0
    column_forces = []

    for col_id in range(1, 5):
        f = ops.eleForce(col_id)
        # eleForce → 全局坐标 [Fx,Fy,Fz, Mx,My,Mz] @i端
        # f[2]=Fz=轴向力, f[3]=Mx, f[4]=My
        P = f[2]
        Mx = f[3]
        My = f[4]
        ratio = abs(P) / Py + abs(Mx) / Mp_weak + abs(My) / Mp_strong
        column_forces.append({
            'id': col_id, 'P': P, 'Mx': Mx, 'My': My, 'ratio': ratio,
        })
        print(f"  柱{col_id}  |  P={P/1e3:>+7.1f} kN  "
              f"Mx={Mx/1e3:>+7.1f} kN-m  My={My/1e3:>+7.1f} kN-m  "
              f"ratio={ratio:.4f}")
        if ratio > critical_ratio:
            critical_id, critical_ratio = col_id, ratio

    print(f"\n  ==> 关键柱: 柱{critical_id}  (应力比 {critical_ratio:.4f})")

    members = {}
    for cid in range(1, 5):
        members[f'C{cid}'] = ('column', cid, cid + 4)
    for eid, (ni, nj) in beam_map.items():
        members[f'B{eid}'] = ('beam', ni, nj)

    return {
        'critical_column': critical_id,
        'critical_ratio': critical_ratio,
        'node_coords': node_coords,
        'members': members,
        'column_forces': column_forces,
        'span': L, 'height': H,
        'Mp_weak': Mp_weak, 'Mp_strong': Mp_strong, 'Py': Py,
    }


# ============================================================================
#  第 2 部分: PyBullet 物理仿真
# ============================================================================

def run_pybullet(fem: dict, enable_fracture: bool = False):
    """在 PyBullet 中建立物理模型并执行倒塌仿真。"""
    if not PYBULLET_AVAILABLE:
        print("[SKIP] PyBullet 未安装。安装: pip install pybullet")
        print("       (Windows 需 MSVC Build Tools)")
        return

    nc = fem['node_coords']
    members = fem['members']
    crit_col = fem['critical_column']
    L = fem['span']
    H = fem['height']

    print("\n" + "=" * 50)
    print("  PyBullet 物理倒塌仿真")
    print("=" * 50)

    # ── 2-A 启动 PyBullet GUI ──
    p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
    p.setGravity(0, 0, -9.81)
    p.setPhysicsEngineParameter(fixedTimeStep=1/240, numSolverIterations=100)
    p.setRealTimeSimulation(0)
    p.loadURDF("plane.urdf")

    # ── 2-B 创建构件 (box 近似) ──
    RHO = 7850                # kg/m3
    body_ids = {}
    constraints = {}

    def make_box(mid, mtype, ni, nj):
        xi, yi, zi = nc[ni]
        xj, yj, zj = nc[nj]
        cx, cy, cz = (xi + xj) / 2, (yi + yj) / 2, (zi + zj) / 2
        dx, dy, dz = xj - xi, yj - yi, zj - zi

        if mtype == 'column':
            hx, hy, hz = 0.075, 0.075, abs(dz) / 2
        elif abs(dx) >= abs(dy):
            hx, hy, hz = abs(dx) / 2, 0.0375, 0.075
        else:
            hx, hy, hz = 0.0375, abs(dy) / 2, 0.075

        mass = (hx*2) * (hy*2) * (hz*2) * RHO
        col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[hx, hy, hz])
        vis = p.createVisualShape(p.GEOM_BOX, halfExtents=[hx, hy, hz])

        is_crit = (mid == f'C{crit_col}')
        color = ([1, 0.2, 0.2, 1] if is_crit else
                 [0.7, 0.7, 0.7, 1] if mtype == 'column' else
                 [0.3, 0.3, 0.3, 1])
        p.setVisualShapeData(vis, -1, color)

        bid = p.createMultiBody(mass, col, vis, [cx, cy, cz])
        p.changeVisualShape(bid, -1, rgbaColor=color)
        return bid

    for mid, (mt, ni, nj) in members.items():
        bid = make_box(mid, mt, ni, nj)
        if bid is not None:
            body_ids[mid] = bid

    # ── 2-C 锚点 & 连接块 ──
    anchors = {}
    for cid in range(1, 5):
        x, y, z = nc[cid]
        c = p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.01]*3)
        v = p.createVisualShape(p.GEOM_BOX, halfExtents=[0.01]*3, rgbaColor=[0,0,0,0])
        anchors[cid] = p.createMultiBody(0, c, v, [x, y, z])

    jblocks = {}
    for nid in range(5, 9):
        x, y, z = nc[nid]
        c = p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.05]*3)
        v = p.createVisualShape(p.GEOM_BOX, halfExtents=[0.05]*3, rgbaColor=[0.5,0.5,0.5,0.3])
        jblocks[nid] = p.createMultiBody(0.001, c, v, [x, y, z])

    # 柱底约束
    for cid in range(1, 5):
        mid = f'C{cid}'
        if mid not in body_ids:
            continue
        bx, by, bz = nc[cid]
        tx, ty, tz = nc[cid + 4]
        cx = (bx + tx) / 2
        cy = (by + ty) / 2
        cz = (bz + tz) / 2
        constraints[f'base_{cid}'] = p.createConstraint(
            anchors[cid], -1, body_ids[mid], -1,
            p.JOINT_FIXED, [0, 0, 0],
            [0, 0, 0],
            [bx - cx, by - cy, bz - cz])
        constraints[f'top_{cid}'] = p.createConstraint(
            body_ids[mid], -1, jblocks[cid + 4], -1,
            p.JOINT_FIXED, [0, 0, 0],
            [0, 0, H/2],
            [0, 0, 0])

    # 梁端约束
    beam_ends = {'B5': (5, 6), 'B6': (8, 7), 'B7': (5, 8), 'B8': (6, 7)}
    for bid, (ni, nj) in beam_ends.items():
        if bid not in body_ids:
            continue
        xn1, yn1, _ = nc[ni]
        xn2, yn2, _ = nc[nj]
        for side, n in [('i', ni), ('j', nj)]:
            if abs(xn1 - xn2) >= abs(yn1 - yn2):
                pos = [-L/2 if side == 'i' else L/2, 0, 0]
            else:
                pos = [0, -L/2 if side == 'i' else L/2, 0]
            constraints[f'{bid}_{side}'] = p.createConstraint(
                body_ids[bid], -1, jblocks[n], -1,
                p.JOINT_FIXED, [0, 0, 0],
                pos, [0, 0, 0])

    print(f"  构件: {len(body_ids)} | 约束: {len(constraints)}")

    # ── 2-D 稳态 ──
    print("\n  稳态阶段 (~1s)...")
    for _ in range(240):
        p.stepSimulation()
        time.sleep(1/240)
    print("  [OK] 已稳定")

    # ── 2-E 破坏触发 ──
    print(f"\n  ==> 拆除关键柱 C{crit_col}")
    for key in [f'base_{crit_col}', f'top_{crit_col}']:
        if key in constraints:
            p.removeConstraint(constraints[key])
            print(f"    移除 {key}")
            del constraints[key]

    # ── 2-F 倒塌仿真 ──
    mode_str = "含自动断裂检测" if enable_fracture else "仅重力倒塌"
    print(f"\n  倒塌仿真 ({mode_str}, 10s)...")
    n_fractured = 0
    for step in range(2400):
        p.stepSimulation()

        if enable_fracture:
            for key, cid in list(constraints.items()):
                try:
                    state = p.getConstraintState(cid)
                    if state and len(state) > 0:
                        force_mag = np.linalg.norm(state[:3]) if len(state) >= 3 else 0
                        if force_mag > 500000:
                            p.removeConstraint(cid)
                            del constraints[key]
                            n_fractured += 1
                            print(f"    断裂约束 {key} (反力={force_mag/1e3:.0f}kN)")
                except Exception:
                    pass

        if step % 240 == 0:
            status = f"累计断裂{n_fractured}" if enable_fracture else ""
            print(f"    {step/240:.1f}s / 10.0s  {status}")
        time.sleep(1/240)

    msg = f" (共 {n_fractured} 处自动断裂)" if enable_fracture else ""
    print(f"\n  [OK] 仿真完成{msg}")
    print("  关闭窗口退出。")
    try:
        while True:
            p.stepSimulation()
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        p.disconnect()


# ============================================================================
#  主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='FEM-PE Hybrid Prototype (PyBullet)')
    parser.add_argument('--physics', action='store_true',
                       help='运行 PyBullet 物理仿真 (默认仅 FEM 分析)')
    parser.add_argument('--fracture', action='store_true',
                       help='开启自动断裂扩展 (需 --physics, 默认关闭)')
    args = parser.parse_args()

    print("=" * 50)
    print("  FEM-PE 混合原型验证 (PyBullet)")
    print("  OpenSeesPy (FEM) + PyBullet (Physics)")
    print("=" * 50)

    print("\n[Phase 1] OpenSeesPy 结构分析")
    print("-" * 30)
    fem = build_and_analyze()

    if args.physics:
        print(f"\n[Phase 2] PyBullet 物理仿真")
        print("-" * 30)
        run_pybullet(fem, enable_fracture=args.fracture)
    else:
        print(f"\n[Phase 2] 跳过 (加 --physics 运行仿真)")
        print("-" * 30)

    print("\n" + "=" * 50)
    print("  完成")
    print("=" * 50)


if __name__ == '__main__':
    main()
