#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
task_health_alert.py — 任务调度健康异常告警（翻转去重，防刷屏）
================================================================

背景（2026-09-18 事故）：`olib_soc_kpi_daily_sync` / `olib_soc_vmax_report` /
`vmax_multi_data_sync` 上线时漏登记 `worker_watchdog.GROUP_TASK_MAP`，分组模式下
没有任何 worker 认领 → 队列 pending 永久滞留，陈旧 pending 又占住该任务的单飞
名额，把之后每一次调度全部挡掉，看板悄悄停了两天。期间 `db_freshness_check`
每小时其实都算出了正确结论（它在 `[TASK-HEALTH]` / `[STALE]` 里明确打印了
「任务已注册但不在分组清单」「队列滞留」「24h 无执行记录」），但这些文字只躺在
worker 日志和任务历史里 —— **没有任何人盯，等于没有监控**。

本模块把「巡检算出来了」和「有人被叫醒」连起来，同时严格防刷屏：

  * 只对调度系统自身的健康异常告警（分组缺失 / 静默停摆 / 队列滞留 / 成功逾期 /
    依赖不可用导致的逾期），不对普通「数据滞后」告警（网络抖动就会刷屏，且那类问题
    任务失败告警已覆盖）。
  * 依赖类逾期（`overdue_dependency`）单独成类：任务在跑、只是外部依赖（EWS/邮件网关、
    网络）不可用。既不像普通「数据滞后」那样被忽略（那会让聚合信号彻底消失），
    也不逐条刷屏 —— 所有受影响任务汇总在同一条通知里。
  * 以 `kind:task_id` 为键做**翻转去重**：一条异常第一次出现才通知，持续期间静默；
    消失时通知一次「已恢复」。与 email_recovery 的 EWS 降级静默是同一套思路。
  * 长期不处理不会永远沉默：持续超过 `RENOTIFY_HOURS`（默认 24h）再提一次，
    并带上「已持续多久 / 第几次提醒」。
  * 通知发送失败**不记为已通知**，下一轮巡检自动重试（否则一次 SMTP 抖动就把
    这条异常永久吞掉）。
  * 状态落盘 `TMP/task_health_alert_state.json`，跨进程/重启保持（与
    email_recovery 的状态文件同一位置约定）。
  * 本模块任何异常都不得影响巡检任务本身：调用方只记日志。

用法（由 db_freshness_check 在任务健康检查之后调用）：

    from backend.services.task_health_alert import evaluate_and_notify
    alert = evaluate_and_notify(findings)

紧急关闭（维护窗口）：设环境变量 `TASK_HEALTH_ALERT_ENABLED=0`。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

MY_APP_DIR = Path(__file__).resolve().parents[2]     # Task/my_app
STATE_FILE = MY_APP_DIR / "TMP" / "task_health_alert_state.json"

# 持续未恢复的重提间隔（小时）。巡检每小时一次，取 24 意味着同一条异常每天最多再提一次。
try:
    RENOTIFY_HOURS = max(1.0, float(os.environ.get("TASK_HEALTH_ALERT_RENOTIFY_HOURS", "24")))
except (TypeError, ValueError):
    RENOTIFY_HOURS = 24.0

# 单条消息最多列出的条目数（其余折叠，避免几十条异常时消息被截断/看不懂）
MAX_ITEMS = 15

# 各异常类别的中文标签与处置动作（写进通知正文，让收到的人知道下一步做什么）
KIND_META = {
    "group_missing": (
        "未登记 worker 分组",
        ["① 把任务加入 backend/worker_watchdog.py 的 GROUP_TASK_MAP 合适分组",
         "② 管理员终端执行：python restart_workers.py --mode watchdog --force --reason \"...\"",
         "③ 陈旧 pending 会被 worker 在 6h 后自动置失败、释放单飞名额（无需手工清库）"],
    ),
    "silent": (
        "24h 无执行记录",
        ["① 任务管理页看该任务历史与下次运行时间",
         "② 查 db/app.db 的 task_queue 是否有滞留 pending（单飞保护会挡后续调度）",
         "③ 确认任务在 GROUP_TASK_MAP 分组清单内，log/worker_runtime_*.log 搜任务名"],
    ),
    "stuck": (
        "队列滞留 pending/running",
        ["① pending 长期无人认领 = 任务不在任何 worker 分组（见上一条处置）",
         "② running 超 30min = worker 崩溃留下的僵尸记录，worker 周期回收会自动补写失败并交 auto_retry",
         "③ 需要立刻恢复：管理员终端 python restart_workers.py --mode watchdog --force"],
    ),
    "overdue": (
        "成功逾期（超一个调度周期无成功）",
        ["① 任务管理页看最近失败原因（含 Worker 进程中断类僵尸失败）",
         "② 确认 auto_retry_failed 每 10 分钟在跑",
         "③ 未自动恢复时手动触发一次回补数据"],
    ),
    # 2026-09-18 新增：把「因外部依赖（EWS/邮件网关、网络）不可用而逾期」从上面
    # 一类里分出来。原实现为了去重把这些任务**整体剔除**出告警，结果 2026-09-15
    # 起的 65 小时里 14 个报表任务全部逾期，task-health 一条告警都没发，只剩
    # task_runner 每任务刷原始异常（"RateLimitError: Max timeout reached"，
    # 看着像服务端限流，指不出真正原因是密码失效）。现在按 task_id 逐条列出，
    # 但**汇总在同一条通知里**发送，既不丢信号也不刷屏。
    "overdue_dependency": (
        "逾期（外部依赖不可用，非任务停摆）",
        ["① 看 email_recovery 的 EWS 状态通知：故障分 server_down / auth_error / cred_mismatch",
         "② auth_error / cred_mismatch 不会自行恢复：到「设置 → Exchange/OWA Mailbox」核对账号密码是否被改/被锁",
         "③ server_down 只能等 Orange 侧恢复；恢复后 email_recovery 当轮自动补发时效内的失败邮件",
         "④ 若长期不恢复，检查该任务是否应改为不依赖 EWS 的通道"],
    ),
}


def _now() -> datetime:
    return datetime.now()


def enabled() -> bool:
    """告警总开关（维护窗口可设 TASK_HEALTH_ALERT_ENABLED=0 临时静音）。"""
    return os.environ.get("TASK_HEALTH_ALERT_ENABLED", "1").strip() not in ("0", "false", "False")


def _load_state(path: Path) -> dict:
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("alerts"), dict):
                return raw
    except Exception as e:  # noqa: BLE001
        logger.warning("[task_health_alert] 状态文件读取失败（按空状态继续）: %s", e)
    return {"version": 1, "alerts": {}}


def _save_state(path: Path, state: dict) -> None:
    """原子写（临时文件 + replace）：巡检与手工执行可能并发，避免半截 JSON。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as e:  # noqa: BLE001
        logger.warning("[task_health_alert] 状态文件写入失败（本轮判定仍生效）: %s", e)


def _pretty_since(iso) -> str:
    """ISO 时间 -> “MM-DD HH:MM”（通知里保持同一格式，别一半带 T 一半不带）。"""
    s = str(iso or "")
    if len(s) >= 16 and "T" in s:
        return s[5:16].replace("T", " ")
    return s[:16]


def _flatten(findings: dict) -> dict:
    """{kind: [task_id,...]} -> {key: (kind, task_id, extra)}，key = kind:task_id。"""
    out = {}
    for kind, items in (findings or {}).items():
        if kind not in KIND_META:
            continue
        for it in (items or []):
            if isinstance(it, dict):
                task = str(it.get("task_id") or it.get("id") or it)
                extra = str(it.get("detail") or "")
            else:
                task, extra = str(it), ""
            out[f"{kind}:{task}"] = (kind, task, extra)
    return out


def _render_lines(entries: list, prefix: str = "") -> list:
    lines = []
    for kind, task, extra, since in entries[:MAX_ITEMS]:
        label = KIND_META.get(kind, (kind, []))[0]
        tail = f"（自 {since}）" if since else ""
        lines.append(f"- [{label}] {task}{tail}{(' ' + extra) if extra else ''}")
    if len(entries) > MAX_ITEMS:
        lines.append(f"- ……其余 {len(entries) - MAX_ITEMS} 条详见巡检日志（[TASK-HEALTH]）")
    return [prefix] + lines if prefix else lines


def _guidance_lines(kinds: set) -> list:
    lines = []
    for kind in sorted(kinds):
        label, steps = KIND_META[kind]
        lines.append(f"〔{label}〕处置：")
        lines.extend(f"  {s}" for s in steps)
    return lines


def _default_senders():
    """返回 (send_text, send_mail)；延迟 import，导入失败时降级为只记日志。"""
    def send_text(text: str) -> bool:
        try:
            from backend.services.weixin_notifier import send_weixin_message
            res = send_weixin_message(text)
            if not res.get("success"):
                logger.warning("[task_health_alert] 微信通知失败: %s", res.get("error"))
                return False
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[task_health_alert] 微信通知异常: %s", e)
            return False

    def send_mail(subject: str, title: str, message: str, ts: str, ok: bool) -> bool:
        try:
            from backend.services.email_notifier import send_status_email
            return bool(send_status_email(
                subject=subject, title=title, message=message, ts=ts, ok=ok,
                source="Task Health",
                footer="本邮件只在任务调度健康状态翻转时发送，同一异常持续期间不会刷屏。请勿直接回复。",
            ))
        except Exception as e:  # noqa: BLE001
            logger.warning("[task_health_alert] 邮件通知异常: %s", e)
            return False

    return send_text, send_mail


def evaluate_and_notify(findings: dict, now: datetime | None = None,
                        state_path: Path | None = None, senders=None) -> dict:
    """按翻转去重的原则决定是否告警，并维护状态文件。

    Args:
        findings: {kind: [task_id | dict(task_id,detail), ...]}，kind 限 KIND_META 五类
        now: 注入时间（测试用）
        state_path: 注入状态文件（测试用）
        senders: 注入 (send_text, send_mail)（测试用）

    Returns:
        摘要 dict（new/resolved/renotify/pending_notify/notified/skipped 等），
        供巡检结果落库排查；不抛异常。
    """
    now = now or _now()
    path = Path(state_path) if state_path else STATE_FILE
    summary = {"evaluated": True, "new": 0, "resolved": 0, "renotified": 0,
               "pending_notify": 0, "notified": False, "skipped": ""}
    if not enabled():
        summary["skipped"] = "disabled_by_env"
        return summary

    try:
        state = _load_state(path)
        alerts = state["alerts"]
        current = _flatten(findings)

        to_report = []            # 本轮要列进通知的 (key, kind, task, extra, since, why)
        for key, (kind, task, extra) in sorted(current.items()):
            rec = alerts.get(key)
            if rec is None:
                alerts[key] = {"kind": kind, "task_id": task, "extra": extra,
                               "first_seen": now.isoformat(timespec="seconds"),
                               "last_seen": now.isoformat(timespec="seconds"),
                               "notified_at": None, "times_notified": 0}
                to_report.append((key, kind, task, extra, now.strftime("%m-%d %H:%M"), "new"))
                summary["new"] += 1
                continue
            rec["last_seen"] = now.isoformat(timespec="seconds")
            rec["extra"] = extra or rec.get("extra", "")
            notified_at = rec.get("notified_at")
            if not notified_at:
                # 上一轮判定要通知但没发出去（SMTP/网络抖动）→ 本轮继续重试
                to_report.append((key, kind, task, extra, _pretty_since(rec.get("first_seen")), "retry"))
                summary["pending_notify"] += 1
            else:
                try:
                    silent_for = now - datetime.fromisoformat(str(rec.get("first_seen")))
                    since_notify = now - datetime.fromisoformat(notified_at)
                except Exception:  # noqa: BLE001
                    continue
                if since_notify >= timedelta(hours=RENOTIFY_HOURS):
                    to_report.append((key, kind, task, extra,
                                      f"{silent_for.total_seconds() / 3600:.0f}h 前起，"
                                      f"第 {int(rec.get('times_notified') or 0) + 1} 次提醒", "renotify"))
                    summary["renotified"] += 1

        resolved = []
        for key in sorted(set(alerts) - set(current)):
            rec = alerts.pop(key)
            if rec.get("notified_at"):
                resolved.append((key, rec.get("kind"), rec.get("task_id"), rec.get("extra"),
                                 _pretty_since(rec.get("first_seen"))))
        summary["resolved"] = len(resolved)

        if not to_report and not resolved:
            _save_state(path, state)
            summary["skipped"] = "no_change"
            return summary

        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        new_items = [(k, t, e, s) for (key, k, t, e, s, why) in to_report]
        parts = []
        if new_items:
            parts.append(f"未恢复异常 {len(new_items)} 项：")
            parts.extend(_render_lines(new_items))
        if resolved:
            parts.append(f"已恢复 {len(resolved)} 项：")
            parts.extend(_render_lines([(k, t, e, s) for (_key, k, t, e, s) in resolved]))
        # 处置指引只在“还有未恢复异常”时附：纯恢复通知里再贴一遍处置步骤会让人怀疑
        # 是不是还没好（2026-09-18 自查文案时发现）。
        if new_items:
            kinds = {x[1] for x in to_report}
            parts.append("")
            parts.extend(_guidance_lines(kinds))
        message = "\n".join(parts)

        title = ("任务调度健康：异常已恢复" if not new_items else
                 f"任务调度健康：{len(new_items)} 项异常待处理")
        subject = f"[任务健康] {title}"
        if senders is None:
            senders = _default_senders()
        send_text, send_mail = senders
        # 微信与邮件任一送达即算已通知；两条都失败则保持"未通知"，下一轮重试。
        ok_text = bool(send_text(f"{subject}\n时间：{ts}\n{message}"))
        ok_mail = bool(send_mail(subject, title, message, ts, ok=not new_items))
        delivered = ok_text or ok_mail
        summary["notified"] = delivered
        if delivered:
            iso = now.isoformat(timespec="seconds")
            for key, _k, _t, _e, _s, why in to_report:
                rec = alerts.get(key)
                if rec is None:
                    continue
                rec["notified_at"] = iso
                rec["times_notified"] = int(rec.get("times_notified") or 0) + 1

        _save_state(path, state)
        logger.info("[task_health_alert] 新增=%d 重试=%d 重提=%d 恢复=%d 通知=%s",
                    summary["new"], summary["pending_notify"], summary["renotified"],
                    summary["resolved"], delivered)
        return summary
    except Exception as e:  # noqa: BLE001
        logger.warning("[task_health_alert] 评估/通知异常（不影响巡检结果）: %s", e)
        return {"evaluated": False, "error": f"{type(e).__name__}: {e}",
                "new": 0, "resolved": 0, "renotified": 0, "pending_notify": 0,
                "notified": False, "skipped": "exception"}


if __name__ == "__main__":  # 手工演练：只打印将发送的内容，不真的发
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    captured = []

    def _cap_text(text):
        captured.append(("wx", text))
        return True

    def _cap_mail(subject, title, message, ts, ok):
        captured.append(("mail", f"{subject} | ok={ok}\n{message}"))
        return True

    state = Path("TMP/_task_health_alert_selftest.json")
    demo = {"group_missing": ["demo_task"], "silent": ["demo_task2"]}
    print("--- 第一轮（全部新增）")
    print(evaluate_and_notify(demo, state_path=state, senders=(_cap_text, _cap_mail)))
    print("--- 第二轮（无变化，应静默）")
    print(evaluate_and_notify(demo, state_path=state, senders=(_cap_text, _cap_mail)))
    print("--- 第三轮（全部消失，应只发恢复）")
    print(evaluate_and_notify({}, state_path=state, senders=(_cap_text, _cap_mail)))
    for kind, payload in captured:
        print(f"---- {kind} ----\n{payload}")
    state.unlink(missing_ok=True)
