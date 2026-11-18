# -*- coding: utf-8 -*-
"""EWS 邮件通道不可用时，把「纯发信」任务延后（不执行、不告警），恢复后交给补发通道。

## 为什么要有这一层（2026-11-18）

``email_recovery`` 已经负责两件事：每 10 分钟真实探测 EWS；恢复后按任务时效窗口
补发失败链。但它只在任务**失败之后**才介入 —— 通道降级期间，每个到点的邮件任务
仍会完整跑一遍：生成报表 → 建 EWS 会话 → 等超时（实测单次可达数分钟）→ 记失败
→ 发失败告警。2026-11-18 的 server_down 期间实测 ``liberia_email_1h`` 24 小时内
失败 14 次、``mailbox_cleanup`` 2 天失败 17 次。

更贵的是**故障域**：邮件任务集中在 Worker ``m`` 组串行（见 ``worker_watchdog.py``），
这些注定失败的运行会把 m 组占满，拖慢同组真正能跑的 WhatsApp / 截图等任务。

本模块把「通道已确认不可用」这一事实**前移到执行前**，复用 ``email_recovery``
落盘的探测状态（唯一真相源，不另做探测）：

  - 只对注册表标了 ``defer_on_ews_down=True`` 的任务生效。纯发信任务才标；
    带数据同步（fw_kpi_sync / ume_in_osg_report）或 WhatsApp 副通道
    （sp_email_details / sp_online_report_send）的任务**不标** —— 延后它们会连
    同步和群发一起停掉，见 ``task_registry.EWS_DEFERRABLE_IDS`` 的注释。
  - 只对**定时触发**生效。手动触发照常执行：人可能刚改完密码，需要立刻验证。
  - 探测状态必须足够新（``EWS_DEFER_MAX_PROBE_AGE_MIN``，默认 30 分钟，约 3 个
    探测周期）。状态缺失 / 过期一律 **fail-open**（照常执行）—— 宁可按原样跑一次，
    也不凭旧结论静默跳过。
  - 延后写成一条 ``trigger_type="deferred"`` 的失败记录，error 带 ``EWS_DEFERRED``
    标记：``email_recovery`` 的失败链、时效窗口、补发档位（hourly / eight_hour /
    daily）**原样复用**，通道恢复后自动补发；已过窗口的照旧丢弃。
  - ``EWS_DEFER_ON_DOWN=0`` 可整体关闭本门禁（回滚开关，无需改代码）。

延后记录刻意不触发失败告警：通道不可用属于「依赖不可用」，不是任务故障；
``email_recovery`` 已有「故障翻转 + 持续故障升级」通知，不在这里重复刷屏。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("ews_deferral")

# 与 email_recovery.EWS_FAIL_KEYS 共用：该标记让延后记录进入补发失败链，
# 由 email_recovery 在通道恢复后按时效窗口补发。
DEFERRED_MARKER = "EWS_DEFERRED"

# 探测状态的最大可接受年龄（分钟）。约 3 个探测周期（email_recovery 每 10 分钟一次）；
# 超过即视为「不知道通道现在什么状态」，fail-open。
_MAX_PROBE_AGE_MIN = float(os.environ.get("EWS_DEFER_MAX_PROBE_AGE_MIN", "30"))


def _read_probe() -> dict | None:
    """读取 email_recovery 落盘的 EWS 探测状态；读不到返回 None（fail-open）。

    刻意不在这里另起一份探测/状态文件：``email_recovery`` 每 10 分钟做一次真实
    SOAP 探测并落盘，重复探测会让 EWS 多背一倍请求，且两份状态必然分叉。
    """
    try:
        from backend.services import email_recovery as er

        path = er.RECOVERY_STATE_FILE
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        probe = raw.get(er.EWS_STATE_KEY) if isinstance(raw, dict) else None
        return probe if isinstance(probe, dict) else None
    except Exception as e:  # noqa: BLE001
        # 状态文件损坏 / 半截写入：按「未确认降级」处理，任务照常执行。
        logger.warning("读取 EWS 探测状态失败，本轮不延后任何任务: %s", e)
        return None


def _probe_age_minutes(probe: dict) -> float | None:
    """探测时间距今多少分钟；时间缺失/不可解析返回 None（按过期处理）。"""
    try:
        probed_at = datetime.fromisoformat(str(probe.get("last_probe_at")))
    except (TypeError, ValueError):
        return None
    return (datetime.now() - probed_at).total_seconds() / 60.0


def _deferred_result(probe: dict) -> dict:
    """构造一条与任务返回值同形的「已延后」结果（success=False，带标记）。"""
    kind = str(probe.get("kind") or "server_down")
    probed_at = str(probe.get("last_probe_at") or "")
    detail = " ".join(str(probe.get("detail") or "").split())[:240]
    error = (
        f"{DEFERRED_MARKER}: 邮箱通道未恢复（{kind}，最后探测 {probed_at}"
        + (f"：{detail}" if detail else "")
        + "）—— 本轮不执行；通道恢复后由 email_recovery 按时效窗口自动补发，过期则丢弃"
    )
    return {
        "success": False,
        "deferred": True,
        "error": error,
        "ews_kind": kind,
        "ews_last_probe_at": probed_at,
        "message": "邮箱通道未恢复，本轮已延后（未执行、不告警）",
    }


def maybe_defer(task: dict, trigger: str) -> dict | None:
    """该任务本轮是否应延后；需要延后时返回结果 dict，否则 None。

    ``task`` 是 ``task_runner._task_registry`` 里的任务字典，``trigger`` 是本次
    触发方式（manual / scheduled / ...）。
    """
    if os.environ.get("EWS_DEFER_ON_DOWN", "1").strip() == "0":
        return None
    if (trigger or "") != "scheduled":
        return None
    if not task.get("defer_on_ews_down"):
        return None

    probe = _read_probe()
    if not probe or str(probe.get("status") or "") != "down":
        return None

    age = _probe_age_minutes(probe)
    if age is None or age > _MAX_PROBE_AGE_MIN:
        # 状态过期（例如 email_recovery 自身被 m 组堵住）：不凭旧结论跳过，
        # 照常执行，由真实发送结果决定成败。
        logger.info(
            "[%s] EWS 探测状态过期（%s），本轮不延后",
            task.get("task_id"), "时间缺失" if age is None else f"{age:.0f} 分钟前",
        )
        return None

    result = _deferred_result(probe)
    logger.warning(
        "[%s] 邮箱通道不可用（%s，探测于 %s），本轮延后不执行；恢复后由 email_recovery 补发",
        task.get("task_id"), result["ews_kind"], result["ews_last_probe_at"],
    )
    return result
