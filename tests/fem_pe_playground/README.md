# FEM-PE 混合原型

OpenSeesPy（有限元分析）+ 物理引擎（MuJoCo / PyBullet）的管线验证。

一层一跨钢框架：弹性分析 → 识别关键柱 → 物理引擎倒塌模拟。

## 快速开始

```bash
# 项目根目录，使用 venv
.venv/Scripts/python tests/fem_pe_playground/fem_pe_prototype.py            # 仅 FEM
.venv/Scripts/python tests/fem_pe_playground/fem_pe_prototype.py --physics  # FEM + MuJoCo
```

## 依赖

| 依赖 | 已安装 | 说明 |
|:---|:---:|:---|
| openseespy | ✅ venv | Python 3.12+ |
| mujoco 3.9.0 | ✅ venv | 即装即用 |
| numpy | ✅ venv | — |
| pybullet | ❌ 可选 | Windows 需 MSVC Build Tools |

## 命令行参数

| 参数 | 作用 | 默认 |
|:---|:---|:---:|
| `--physics` | 执行物理引擎仿真（不加则仅做 FEM 分析）| 关闭 |
| `--fracture` | 开启自动断裂扩展（需配合 `--physics`）| 关闭 |
| `--no-gui` | 无 GUI 模式（不打开 3D 窗口，仅命令行输出）| GUI 打开 |

### 四种运行模式

| 命令 | Phase 1 | Phase 2 | 倒塌行为 |
|:---|:---:|:---:|:---|
| 无参数 | FEM 分析 | 跳过 | — |
| `--physics` | FEM 分析 | MuJoCo 仿真 | 关键柱拆除后，剩余连接焊死不崩 |
| `--physics --fracture` | FEM 分析 | MuJoCo 仿真 | 关键柱拆除后，大变形处自动断连 |
| `--physics --fracture`（PyBullet）| FEM 分析 | PyBullet 仿真 | 同上，用约束反力判定断裂 |

### 断裂模式 vs 非断裂模式

```
--physics 不开 fracture：
  拆除 C1 → 剩余焊死 → 整体倒塌
  模拟：连接节点足够强，不破坏

--physics --fracture：
  拆除 C1 → 结构大变形 → 约束位移超阈值 → 自动断开 → 连锁断裂
  模拟：连接在大变形下逐级失效
```

## 文件说明

| 文件 | 说明 |
|:---|:---|
| `fem_pe_prototype.py` | MuJoCo 版：Phase 1 FEM + Phase 2 MuJoCo |
| `fem_pe_pybullet.py` | PyBullet 版：Phase 1 FEM + Phase 2 PyBullet |
| `frame_model.xml` | 运行时自动生成的 MuJoCo 模型 |
| `README.md` | 本文件 |

## 输出示例

### FEM 分析（两版本共用）

```
  柱1  |  P=   -0.3 kN  Mx=   +0.0 kN-m  My=   -6.9 kN-m  ratio=0.0812
  柱2  |  P=   +0.3 kN  Mx=   -0.0 kN-m  My=   -6.9 kN-m  ratio=0.0812
  柱3  |  P=   +0.3 kN  Mx=   -0.0 kN-m  My=   -6.9 kN-m  ratio=0.0812
  柱4  |  P=   -0.3 kN  Mx=   +0.0 kN-m  My=   -6.9 kN-m  ratio=0.0812
  ==> 关键柱: 柱1  (应力比 0.0812)
```

### MuJoCo 物理仿真（带断裂）

```
  倒塌仿真 (含自动断裂检测, 5s)...
    断裂 eq_idx=1 (偏差=1.502m)
    断裂 eq_idx=2 (偏差=1.502m)
    ...
    0.0s / 5.0s  累计断裂14
    1.0s / 5.0s  累计断裂14
    ...
  [OK] 仿真完成 (共 14 处自动断裂)
```

## 键盘操作（GUI 模式）

| 按键 | 功能 |
|:---|:---|
| `D` | 拆除关键柱（稳态后按） |
| `[` / `]` | 减速 / 加速播放 |
| `R` | 重播（倒塌完成后按） |
| `ESC` | 退出 |

## 注意事项

- 需在项目 `.venv` 下运行（Python 3.12 + openseespy）
- MuJoCo 版即装即用；PyBullet 版需 MSVC Build Tools 编译
- 力学审查详见 `docs/力学审查.md`
