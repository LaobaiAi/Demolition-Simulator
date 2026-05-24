# 结构求解器

_文档待完善_

## 当前求解器

| 求解器 | 类型 | 延迟 | 精度 | 状态 |
|--------|------|------|------|------|
| anaStruct | 快速线性分析 | 低 | 中 | ✅ 默认启用 |
| OpenSees | 高精度非线性 | 高 | 高 | ✅ 按需启动 |
| PyNite | 快速分析（备选） | 低 | 中 | ⏳ 懒加载 |
| FAPP | 快速分析（备选） | 低 | 中 | ⏳ 懒加载 |

## 多求解器共识

Gateway 提供 `/verify/multi` 端点，并发调用多个求解器：
- 按维度（X/Y/Z）分组对比
- 自动检测异常值（偏离 >30% 标记为 outlier）
- 输出 consensus by dimension 结果

## 关键文件

- `gateway/main.py` — `/verify` 和 `/verify/multi` 端点
- `caiao_servers/anastruct_server/server.py`
- `caiao_servers/opensees_server/server.py`
