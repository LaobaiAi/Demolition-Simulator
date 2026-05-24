# Unity 3D 集成

_文档待完善_

## 架构

```
Unity Editor (SimulationController.cs)
    │ TCP :5005
    ▼
Unity Simulator CAIAO Server (caiao_servers/unity_simulator/)
    │ stdio
    ▼
Gateway → WebRTC Signaling → Frontend (unity-video-panel.tsx)
```

## 组件

- `SimulationController.cs` — TCP 监听 :5005，物理拆除模拟
- `FrameBuilder.cs` — 程序化框架建模
- `WebRTCStreamer.cs` — 相机画面 WebRTC 推流
- `WebRTCSignaling.cs` — SDP 信令桥接到 Gateway

## 一键启动

`XuanwuAI Launcher.bat` → 选项 2 或 3 启动 Unity Editor。

Unity Editor → Tools → XuanwuAI → Setup Scene 自动创建场景。
