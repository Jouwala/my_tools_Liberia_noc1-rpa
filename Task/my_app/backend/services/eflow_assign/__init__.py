# -*- coding: utf-8 -*-
"""eFlow 自动派单共用包。

| 模块 | 职责 |
| --- | --- |
| `assign_config.py` | 共用配置底座（时间边界、目标组、演练开关、群组、站点近似匹配） |
| `eflow_assign_client.py` | 共用 HTTP 客户端（查实时告警、解析用户组/站点、调派单接口） |
| `assign_engine.py` | 共用派单引擎（派单判定、关联判定、合并分组、重试回查、消息渲染） |

业务线各自实现：
- `backend/services/eflow_fiber/` —— Fiber Break（4758）
- `backend/services/eflow_5g/` —— 5G 站点告警（200201001 等 9 位码）

⚠ 业务线模块只声明**自己的差异**（告警码、restype、字段形态、消息抬头），
判定口径一律走共用底座，避免两份真相源。
"""
