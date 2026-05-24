# Frame Generator — 实例库

本目录包含使用 FrameGenerator CAIAO Server 的示例。

## 文件说明

| 文件 | 说明 |
|------|------|
| `demo_generate_analyze.py` | 完整流程：生成框架 → 分析 → 输出结果 |
| `demo_3d_export.py` | 生成 3D 框架数据，可用于 Unity/可视化 |

## 使用方法

```bash
# 确保 gateway 在运行
cd ../../gateway
python main.py

# 然后在另一个终端运行 demo
cd ../demos/frame_generator
python demo_generate_analyze.py
```

## 注意

Demo 直接调用 core.py 中的 FrameGenerator，不依赖 MCP 服务器进程。
这样便于独立测试和调试生成逻辑。
