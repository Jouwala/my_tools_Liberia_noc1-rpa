# Phase 4 Service 大文件拆分说明

> 架构优化计划 Phase 4：将超过 1500 行的 Service 大文件按职责拆分为单一职责模块。
> 拆分原则：**对外契约零变化** —— 旧导入路径通过 PEP 562 模块级 `__getattr__` 惰性重导出保持兼容，task_registry 任务注册与外部脚本无需任何改动。

## 拆分总览

| 原文件 | 拆分后 | 职责 |
|---|---|---|
| `task_runner.py` (1248行) | `task_runner.py` (714行) | 任务注册/执行/调度 + 队列投递 |
| | `task_stats.py` (207行) | 任务统计/失败分析/执行历史（查 task_execution_log） |
| | `task_introspect.py` (390行) | 任务内省：TASK_IO 输入输出清单、调用链 AST 分析 |
| `eflow_api_client.py` (2739行) | `eflow_api_client.py` (786行) | HTTP/SSL 基础、登录会话、重试、导出任务基础设施、共享常量 |
| | `eflow_alarm_service.py` (631行) | 实时/历史告警抓取、清洗、入库（eflow.db + app.db） |
| | `eflow_data_mapper.py` (1495行) | TT/WO/CR/PM/Site/Person 抓取管线、入库、Excel/FTP、报表生成 |
| `ms_sla_service.py` (2787行) | `ms_sla_service.py` (246行) | 共享常量/路径配置 + `run_full_sync` 编排入口 |
| | `ms_sla_sync.py` (930行) | RAN UME SLA 指标抓取、xlsx 解析、SQLite 入库、FTP/远程 API 分发 |
| | `ms_sla_report.py` (1650行) | Contract KPIs & WOs Achievement 报表更新、格式化、HTML/PNG 导出、FTP 上传 |
| `report/mail_126.py` (1049行) | 不拆分（低于 1500 行阈值） | Orange Site Down 小时报 Excel/图片生成与 126 邮件发送 |

## 依赖方向（无循环）

```
task_runner ──> task_stats ──> backend.database
     └────────> task_introspect（纯 AST 静态分析，无运行时依赖）

eflow_alarm_service ──┐
                      ├──> eflow_api_client（常量 + HTTP + 会话访问器）
eflow_data_mapper ────┘
eflow_api_client ─ · ─> 子模块（仅 __getattr__ 惰性重导出，不在顶层导入）

ms_sla_sync ────┐
                ├──> ms_sla_service（路径/FTP/UME 常量 + _db_writer）
ms_sla_report ──┘
ms_sla_service ─ · ─> 子模块（仅 __getattr__ 惰性重导出 + run_full_sync 函数内导入）
```

## 兼容层机制（PEP 562）

原模块尾部保留 `_PHASE4_SPLITS` 映射表 + 模块级 `__getattr__`：

```python
from backend.services.eflow_api_client import fetch_all_data   # 仍可用（惰性解析到 eflow_data_mapper）
from backend.services.ms_sla_service import run_ms_sla_sync    # 仍可用（惰性解析到 ms_sla_sync）
```

注意：`__getattr__` 只对**跨模块属性访问**生效。原模块内部（如 `if __name__ == "__main__"` 块）
引用已迁移函数时需显式 `from ... import ...`（已在各文件入口块补齐）。

## 会话状态跨模块访问（eflow 专用）

`_session_cookie` / `_forgery_token` 为 eflow_api_client 模块级可变状态，子模块不得直接 import 绑定
（会绑定过期值）。统一通过访问器读取：

- `ensure_login()`：确保已登录（子模块入口调用）
- `get_session_headers()`：返回当前 `(cookie, forgery_token)` 元组

## 运行方式（不变）

```powershell
# eFlow
python -m backend.services.eflow_api_client active_alarm|history_alarm|alarm|report [upload]|all
# MS SLA
python -m backend.services.ms_sla_service full|sync|report
```

## 变更历史

- 2026-08-06：Phase 4 拆分完成，全部旧导入路径回归验证通过。
