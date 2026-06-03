# 汽轮机厂房 — 技术文件

> 最后更新: 2026-06-02

---

## 一、项目概况

| 项目 | 内容 |
|------|------|
| 结构形式 | 24榀×3轴钢筋混凝土+钢屋架框架 |
| 平面尺寸 | 184m(长) × 33m(宽) × 27m(脊高) |
| 柱网 | 24榀@8m，A/B/C三轴 |
| 建模工具 | Blender 4.2.8 LTS Python API |
| 模型类型 | 白模（示意级精度） |
| 构件总数 | 480 |

---

## 二、建模要求

### 2.1 轴线定位

```
      北 C轴 y=33
      ┌──────────────────────┐
      │  BC跨 9m             │  平混凝土梁@25m + 平屋面
      │  楼板@8m, @15m       │
      ├──────────────────────┤
      │  B轴 y=24            │
      │                      │
      │  AB跨 24m            │  钢屋架双坡 25m→27m→25m
      │                      │
      ├──────────────────────┤
      南 A轴 y=0
      │←─ 23×8m = 184m ────→│
      东(x=0)          西(x=184)
```

### 2.2 结构参数

```json
{
  "frame_count": 24,
  "column_spacing": 8.0,
  "bay_ab": 24.0,
  "bay_bc": 9.0,
  "column_height": 25.0,
  "roof_ridge_height": 27.0,
  "column_size": 0.8,
  "beam_width": 0.4,
  "beam_height": 0.8,
  "truss_member_size": 0.15,
  "slab_thickness": 0.2,
  "wall_thickness": 0.2,
  "bc_floors": [8.0, 15.0]
}
```

### 2.3 构件清单（8步建模）

| 步骤 | 构件类型 | 数量 | 命名规则 |
|------|---------|------|---------|
| 1 | 柱子 | 72 | `Col_{A/B/C}{1..24}` |
| 2 | 柱顶通长纵梁 | 69 | `LongBeam_{A/B/C}_{1..23}` |
| 3 | AB跨钢屋架 | 24榀×6件 | `Truss_{1..24}_{bottom/topL/topR/vertical/web1/web3}` |
| 4 | BC跨平梁 | 24 | `Beam_BC_{1..24}` |
| 5 | BC跨楼板 | 46 | `Floor_BC_{1..23}_z{8/15}` |
| 6 | 屋面板 | 69 | `Roof_AB_{1..23}_{S/N}` `Roof_BC_{1..23}` |
| 7 | 纵墙板 | 46 | `Wall_{A/C}_{1..23}` |
| 8 | 端部山墙+抗风柱 | 8 | `Gable_{East/West}_{AB/BC}_lower`, `Gable_{East/West}_AB_tri`, `WindCol_{East/West}_{1/2}` |

### 2.4 命名约定

```
格式: {类型}_{位置}_{序号}

类型         位置          序号范围      说明
──────────────────────────────────────────────
Col          A/B/C         1~24         柱子
LongBeam     A/B/C         1~23         纵梁(区隔编号)
Truss        (无)          1~24         钢屋架(下弦/上弦L/R/竖杆/斜杆)
Beam_BC      (无)          1~24         BC跨横向梁
Floor_BC     (无)          1~23_z{8/15} BC跨楼板
Roof_AB      (无)          1~23_{S/N}   AB跨屋面板(南/北坡)
Roof_BC      (无)          1~23         BC跨平屋面板
Wall         A/C           1~23         纵墙板
Gable        East/West     AB/BC_lower  端部山墙下半
Gable        East/West     AB_tri       端部山墙三角
WindCol      East/West     1/2          抗风柱
```

**序号方向**：X=0(东端)为1号，向西递增至24号。区隔编号跟随其左侧(较小X)榀号。

---

## 三、拆除工序

### 3.1 工序总览

| 步骤 | 内容 | 速度 | 子步数 | 构件 |
|------|------|------|--------|------|
| 0 | 西端BC跨山墙 | 正常 | 1 | Gable_West_BC_lower |
| 1 | BC跨 Bay23→21 自上而下 | 正常 | 12 | Roof_BC → Beam_BC → Floor@15 → Floor@8 |
| 2 | AB屋面板 Bay23→21 | 正常 | 6 | Roof_AB_S + Roof_AB_N |
| 3 | 钢屋架 24→22 | 正常 | 18 | Truss_24/23/22 (每榀6件) |
| 4 | A轴纵墙板 23→21 | 正常 | 3 | Wall_A_23/22/21 |
| 5 | 西端AB跨山墙 | 正常 | 2 | Gable_West_AB_lower + _tri |
| 6 | 西端抗风柱 | 正常 | 2 | WindCol_West_1 + _2 |
| **7** | **AB屋面板 Bay20→1** | **加速** | **40** | Roof_AB_S + Roof_AB_N |
| **8** | **A轴纵墙板 20→1** | **加速** | **20** | Wall_A_20→1 |
| **9** | **钢屋架 21→1** | **加速** | **126** | Truss_21→1 (每榀6件) |
| **10** | **东端AB跨山墙** | **加速** | **2** | Gable_East_AB_lower + _tri |
| **11** | **东端抗风柱** | **加速** | **2** | WindCol_East_1 + _2 |
| 12 | A轴全部柱子 24→1 | 正常 | 24 | Col_A_24→1 |
| 13 | 批量:除C柱外全部 西→东 | 加速 | ~10组 | 所有剩余构件(排除Col_C_*) |
| 14 | C轴柱子 24→1 | 正常 | 24 | Col_C_24→1 |

### 3.2 详细工序

#### 步骤0: 西端BC跨山墙
```
Frame 0:  Gable_West_BC_lower
```

#### 步骤1: BC跨 Bay23→21 自上而下
```
Bay 23 (x=176~184):
  Frame 48:   Roof_BC_23
  Frame 96:   Beam_BC_23 + Beam_BC_24
  Frame 144:  Floor_BC_23_z15
  Frame 192:  Floor_BC_23_z8

Bay 22 (x=168~176):
  Frame 240:  Roof_BC_22
  Frame 288:  Beam_BC_22
  Frame 336:  Floor_BC_22_z15
  Frame 384:  Floor_BC_22_z8

Bay 21 (x=160~168):
  Frame 432:  Roof_BC_21
  Frame 480:  Beam_BC_21
  Frame 528:  Floor_BC_21_z15
  Frame 576:  Floor_BC_21_z8
```

#### 步骤2-6: AB跨西端 (正常速度)
```
步骤2: AB屋面板 Bay23→21
步骤3: 钢屋架 Truss_24→23→22
步骤4: A轴墙板 Wall_A_23→22→21
步骤5: 西端AB山墙 Gable_West_AB_lower + _tri
步骤6: 西端抗风柱 WindCol_West_1 + WindCol_West_2
```

#### 步骤7-11: AB跨 Bay20→1 (加速播放)
```
步骤7: AB屋面板 20→1  (spacing=12帧)
步骤8: A轴墙板 20→1
步骤9: 钢屋架 21→1
步骤10: 东端AB山墙
步骤11: 东端抗风柱
```

#### 步骤12-14: 收尾
```
步骤12: A轴柱子 Col_A_24→1 (西→东)
步骤13: 批量拆除除C柱外所有剩余构件 (西→东, 加速)
步骤14: C轴柱子 Col_C_24→1 (西→东, 最后)
```

### 3.3 拆梁规则

BC跨平梁(Beam_BC)位于每榀轴线上。当拆除某跨时：
- 首跨(bay23)：拆除左梁(bay号) + 右梁(bay号+1)
- 后续跨：仅拆左梁（右梁已被前跨拆除）

---

## 四、动画参数

| 参数 | 正常速度 | 加速 |
|------|---------|------|
| 帧间隔(spacing) | 48帧(2秒) | 12帧(0.5秒) |
| 过渡帧(transition) | 12帧 | 6帧 |
| 帧率 | 24fps | 24fps |
| 效果 | 变橙→缩小→下坠→隐藏 | 同左 |

| 总体 | 值 |
|------|-----|
| 总步骤 | 138步 |
| 动画构件 | 739个 |
| 总帧数 | ~4608帧 |
| 总时长 | ~192秒 (3分12秒) |

---

## 五、镜头方案

参照 `frame_demolition` 项目：

| 参数 | 值 |
|------|-----|
| 计算方式 | 场景包围盒对角线 × 倍数 |
| 相机距离 | diagonal × 0.85 |
| 相机高度 | diagonal × 0.35 |
| 镜头 | 20mm广角 |
| 视角 | 东南俯瞰 |
| 约束 | TRACK_TO → CameraTarget |
| 跟随 | CameraTarget X 从西(184)→东(0)→中(92) 关键帧平移 |
| 相机X | 与Target同步偏移 |

---

## 六、文件结构

```
projects/steam_turbine_building/
├── TECHNICAL_MANUAL.md          # 本文档
├── README.md                    # 项目说明
├── data/
│   └── config.json              # 建模参数
├── output/
│   └── blend/
│       ├── scene_base.blend     # 白模基础模型 (480构件)
│       ├── scene_animated.blend # 拆除动画 (739构件动画)
│       ├── preview_white_model.png
│       └── debug_*.png
└── scripts/
    ├── main.py                  # 入口
    ├── build_steam_turbine.py   # 建模 (8步构建)
    └── animate_demolition.py   # 拆除动画 (14步工序)
```

---

## 七、已知问题及解决

### 7.1 构件尺寸缩水

**现象**: 模型呈爆炸图，构件彼此不接触。

**根因**: `primitive_cube_add(size=1)` 创建边长=1的立方体。`obj.scale=(a,b,c)` 直接等于目标尺寸。但 `column/beam/slab` 等 helper 函数传入了 `target_size/2`。

**解决**: 所有 helper 函数的 scale 参数改为目标尺寸：
```python
# ❌ column: box(loc, (s/2, s/2, h/2))  → 尺寸只有目标一半
# ✅ column: box(loc, (s, s, h))         → 正确
```

### 7.2 墙板悬空

**现象**: 墙板底面在12.5m高度(z最高37.5m)。

**根因**: `slab(cx, ay, ch/2, ...)` 中 `cz=ch/2` 被当作底面，实际应传 `cz=0`。

### 7.3 AB屋面板脱节

**现象**: AB跨屋面板平放在z=25m，钢屋架上弦在z=27m。

**解决**: 新增 `sloped_roof` 函数，绕X轴旋转贴合坡度。

### 7.4 端部未封堵

**解决**: 东西两端各加AB跨矩形墙 + BC跨矩形墙 + AB跨三角山墙 + 2根抗风柱。

---

## 八、Blender API 备忘

| 要点 | 说明 |
|------|------|
| `primitive_cube_add(size=1)` | 边长=1，`obj.scale=(a,b,c)` 后实际尺寸=a×b×c |
| `matrix_world @ v.co` | 获取顶点世界坐标，验证模型必须用 |
| `rotation_euler` 顺序 | 默认XYZ |
| `primitive_cylinder_add` | depth=总长，沿Z轴创建；用axis-angle旋转到目标方向 |
| `mesh.from_pydata` | 自定义三角面(山墙三角) |
| Workbench渲染 | 白模输出，不依赖GPU |
| CONSTANT插值 | hide_viewport/color 用瞬间切换 |

---

## 九、运行命令

```bash
# 构建白模
blender --background --python projects/steam_turbine_building/scripts/build_steam_turbine.py

# 生成拆除动画
blender --background projects/steam_turbine_building/output/blend/scene_base.blend \
    --python projects/steam_turbine_building/scripts/animate_demolition.py

# 预览渲染
blender --background projects/steam_turbine_building/output/blend/scene_animated.blend \
    --python scripts/render.py
```
