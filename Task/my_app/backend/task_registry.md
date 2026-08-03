# task_registry.py — 定时任务注册表

> P2#8 重构（2026-08-03）：从 `main.py::_register_all_tasks`（336 行、22 个任务）拆分出的数据驱动任务定义模块。

## 设计说明

- **定义与注册分离**：本模块维护声明式任务清单 `TASK_SPECS`，`register_all_tasks(task_runner)` 统一注册。
- **懒加载**：业务函数通过 `_lazy_loader(module_path, func_name)` 在调用时才 import，避免启动期加载重型服务（UME 登录、playwright、exchangelib 等），保持后端快速启动。
- **新增任务**：只需在 `TASK_SPECS` 追加一条记录，无需改动注册逻辑。

## 任务记录字段

每条 spec 二选一提供可执行体：

- `func`：可直接调用的函数（需要特殊包装的任务，如 eFlow 同步、告警摘要）；
- `loader`：`(module_path, func_name)` 元组，注册时自动生成懒加载包装。

其余字段：`task_id` / `name` / `name_en` / `description` / `description_en` / `default_cron` / `category`，与 `backend/services/task_runner.py::register_task` 参数一一对应。

## 对外接口

| 对象 | 说明 |
| --- | --- |
| `TASK_SPECS` | 22 条声明式任务清单 |
| `register_all_tasks(task_runner) -> int` | 遍历注册全部任务，返回数量 |
| `sync_history` | eFlow 同步历史列表（`main.py` 的 `/api/eflow/status` 共享同一对象） |

## 依赖

仅 Python 标准库（importlib / logging）；业务依赖随各任务懒加载，
整体依赖见 `backend/requirements.txt`。
