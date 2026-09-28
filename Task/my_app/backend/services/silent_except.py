# -*- coding: utf-8 -*-
"""统一的"显式吞异常"入口。

## 为什么要有这个模块

本仓库面对的是 UME / eFlow / WhatsApp 网页端 / GSC 门户等**不稳定上游**，
AGENTS.md 原则 5 明确要求显式处理"上游返回半截数据"。因此"捕获异常后降级继续"
**本身是正确设计，不是坏味道** —— 全仓库 `[SILENT-EXCEPT]` 有 320 处，其中绝大多数
是刻意的容错，一刀切删掉只会让采集链路大面积硬失败。

真正的问题是**吞了之后没有上下文**：出问题时只看到"某处被吞了"，无法回答
"哪个任务、哪个数据源、哪个站点"。本模块把这个隐式行为变成显式契约：

    from backend.services.silent_except import swallow

    with swallow("站点丢包数据", task_id="ran_ume_pm", source="lte_pl"):
        rows = fetch_packet_loss(site_id)      # 失败则 rows 保持原值，并留下带上下文的日志

## 用法约定（配合 tests/test_engineering_guards.py 的守卫）

- **可降级**的采集分支：用 `swallow(...)`，不要写裸 `except Exception: pass`。
- **不可降级**（数据会算错、写坏库、鉴权失败）：**不要吞**，让它抛出去，
  由 main.py 的全局异常处理器兜底并带上 request_id。
- 判定标准是 AGENTS.md 原则 6："取不到数据显示 `—`，不得显示成 `0`"。
  如果吞掉异常会让上层把"取不到"当成 0/空，那就不该吞，或者必须让上层能区分。

## 与既有 320 处的收敛策略

**不做全量替换**（那是 320 次独立判断、跨 60+ 文件，回归风险远大于收益）。
策略是"改到哪个改哪个"：只有在**动到某段代码**且那段属于"吞掉会导致假 0"时，
才顺手换成 `swallow()`。这与 AGENTS.md 原则 2 对超限文件的处理方式一致。
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

logger = logging.getLogger("silent_except")

__all__ = ["swallow", "SafeResult"]


class SafeResult:
    """`swallow` 内可写的结果容器：把"失败了没有"显式暴露给调用方。

    这样上层能区分"真的没有数据"和"取数失败" —— 前者显示 `—` 是正常的，
    后者应该提示错误而不是静默当作空。
    """

    __slots__ = ("value", "failed", "exc")

    def __init__(self, value: Any = None) -> None:
        self.value = value
        self.failed = False
        self.exc: Optional[BaseException] = None

    def __bool__(self) -> bool:
        return not self.failed

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"SafeResult(value={self.value!r}, failed={self.failed}, exc={self.exc!r})"


@contextmanager
def swallow(
    scope: str,
    *,
    task_id: str = "",
    source: str = "",
    result: Optional[SafeResult] = None,
    level: int = logging.WARNING,
) -> Iterator[Optional[SafeResult]]:
    """显式吞掉异常，但**记录完整上下文**。

    参数
    ----
    scope   : 人话描述"在做什么"，如 `"站点丢包数据"`、`"WhatsApp QR 刷新"`。
              必填 —— 它就是让日志可检索的那个键。
    task_id : 任务 ID（见 backend/task_registry.py 的 TASK_SPECS）。
    source  : 数据源/上游名，如 `"lte_pl"`、`"ume"`、`"eflow"`。
    result  : 传入 SafeResult 实例可在块内标记失败，供上层判断。
    level   : 日志级别，默认 WARNING。

    注意：**只捕 Exception，不捕 BaseException** —— KeyboardInterrupt /
    SystemExit 必须能穿透，否则 worker 收不到停止信号（见 worker.py 的信号处理）。
    """
    try:
        yield result
    except Exception as exc:  # noqa: BLE001 —— 本模块的职责就是收敛这种捕获
        if result is not None:
            result.failed = True
            result.exc = exc
        logger.log(
            level,
            "[SWALLOWED] scope=%s task=%s source=%s -> %s: %s",
            scope, task_id or "-", source or "-", type(exc).__name__, exc,
            exc_info=True,
        )
