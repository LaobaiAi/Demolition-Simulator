# 汽轮机厂房 (Steam Turbine Building)

汽轮机主厂房3D建模与施工动画项目。

## 厂房结构

```
            北 (C轴)
    ┌──────────────────────────────┐
    │       除氧煤仓间 (12m)        │  BC跨 - 混凝土框架多层
    │   标高: 6m / 12m / 18m       │
    ├──────────────────────────────┤
    │                              │  B轴 - 吊车梁 轨顶18m
    │       汽机房 (30m)           │  AB跨 - 钢屋架双坡屋面
    │   标高: 25m (柱顶)           │
    │   [汽轮机基座×2]             │
    ├──────────────────────────────┤
            南 (A轴)
    |←──────── 12×8m = 96m ──────→|
```

## 目录结构

```
steam_turbine_building/
├── README.md
├── data/
│   └── config.json              # 项目配置（尺寸、施工策略等）
├── output/
│   └── blend/                   # Blender输出文件
│       ├── scene_base.blend     # 基础模型
│       ├── scene_animated.blend # 施工动画
│       └── scene_final.blend    # 最终场景
└── scripts/
    ├── main.py                  # 入口脚本
    └── build_steam_turbine.py   # 建模与动画
```

## 用法

```bash
# 构建基础模型
blender --background --python projects/steam_turbine_building/scripts/main.py

# 生成施工动画（待实现）
blender --background projects/steam_turbine_building/output/blend/scene_base.blend \
    --python projects/steam_turbine_building/scripts/main.py -- --animate
```

## 配置说明

编辑 `data/config.json` 调整厂房参数：

- `turbine_hall_span`: 汽机房跨度 (默认30m)
- `auxiliary_bay_span`: 除氧煤仓间跨度 (默认12m)
- `column_spacing`: 柱距 (默认8m)
- `columns_longitudinal`: 纵向柱数 (默认12)
- `turbine_hall_height`: 汽机房柱高 (默认25m)
- `crane_rail_height`: 吊车轨顶标高 (默认18m)
- `construction_strategy`: 施工顺序与动画参数
