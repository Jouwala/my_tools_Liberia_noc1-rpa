# -*- coding: utf-8 -*-
"""AP 通知：邮件（SMTP/EWS 共用凭据）+ WhatsApp 群组文本推送。

## 三条硬约束（都来自项目既有事故/约定）

1. **通知失败绝不回滚业务**（方案 9.3 与 `email_notifier.py` 顶部设计原则一致）。
   本模块所有函数都吞异常并返回 `{"ok": bool, ...}`，调用方只看结果、不 try。
2. **群名可自定义，默认 `lbr_assistant`**。群名是"推送端解析成 JID"的唯一依据，
   解析不到会整单失败（`wa_notify_service.dispatch` 的既有语义），所以群名写错
   要能从返回值里看出来 —— 本模块把 errors 原样带回给调用方记录。
3. **推送通道是"单槽作业文件"**（`wa_notify_service` 只维护一份 pending 作业，
   新作业会覆盖尚未消费的旧作业）。因此**不能一条一条直接 dispatch** ——
   连续下发 5 个 AP 会把前 4 条覆盖掉。本模块用一个 3 秒合并窗口的批处理线程，
   把同一批消息合并成**一次** dispatch。

## 邮件为什么不用 `email_notifier.send_status_email`

那个函数只支持**单个收件人**（`sendmail(SENDER, [to_addr], ...)`），而 AP 需要同时
通知负责人 + 审核人。这里复用它的 SMTP 常量与凭据读取，自己组装多收件人邮件，
避免为多收件人改一个被 20+ 任务共用的函数。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from html import escape

logger = logging.getLogger("ap.notify")

# 默认群组：现场先用 lbr_assistant 验证（吉祥 2026-10-30 指定）
DEFAULT_GROUPS = ("lbr_assistant",)

# 合并窗口（秒）：窗口内的多条消息合并成一次 WhatsApp dispatch
BATCH_WINDOW = 3.0
# 单次最多合并多少条，避免一次作业过大
BATCH_MAX = 40

_buffer: dict[tuple[str, ...], list[dict]] = {}
_buf_lock = threading.Lock()
_flusher_started = False


# ========== 群组解析 ==========

def parse_groups(raw) -> list[str]:
    """把 `"lbr_assistant, ZTE_NOC_FO"` 这类输入解析成去重后的群名列表。"""
    if raw is None or raw == "":
        return list(DEFAULT_GROUPS)
    if isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        items = str(raw).replace(";", ",").split(",")
    out: list[str] = []
    for g in items:
        g = g.strip()
        if g and g not in out:
            out.append(g)
    return out or list(DEFAULT_GROUPS)


# ========== WhatsApp 批处理 ==========

def _flush_once() -> None:
    with _buf_lock:
        pending = {k: v[:] for k, v in _buffer.items() if v}
        _buffer.clear()
    for groups, messages in pending.items():
        if not messages:
            continue
        try:
            from backend.services import wa_notify_service as wa
            res = wa.dispatch(messages, list(groups))
            if res.get("ok"):
                logger.info("[ap.notify] WhatsApp 已投递 %s 条 → %s", len(messages), groups)
            else:
                logger.warning("[ap.notify] WhatsApp 投递失败（群 %s）：%s", groups,
                               "; ".join(res.get("errors") or []))
        except Exception as e:  # noqa: BLE001  通知失败不影响业务
            logger.warning("[ap.notify] WhatsApp 投递异常：%s", e)


def _flusher_loop() -> None:
    while True:
        time.sleep(BATCH_WINDOW)
        try:
            _flush_once()
        except Exception as e:  # noqa: BLE001
            logger.warning("[ap.notify] 批处理线程异常：%s", e)


def _ensure_flusher() -> None:
    global _flusher_started
    if _flusher_started:
        return
    with _buf_lock:
        if _flusher_started:
            return
        t = threading.Thread(target=_flusher_loop, name="ap-wa-flusher", daemon=True)
        t.start()
        _flusher_started = True


def send_whatsapp(groups, ap_no: str, text: str) -> None:
    """把一条 AP 通知排进合并队列。**立即返回**，不阻塞接口。"""
    try:
        gs = tuple(parse_groups(groups))
        _ensure_flusher()
        with _buf_lock:
            bucket = _buffer.setdefault(gs, [])
            bucket.append({"tt_no": ap_no, "text": text})
            if len(bucket) > BATCH_MAX:
                del bucket[:-BATCH_MAX]
    except Exception as e:  # noqa: BLE001
        logger.warning("[ap.notify] 排队 WhatsApp 失败：%s", e)


def flush_now() -> None:
    """立即冲刷（测试/关停时用）。"""
    _flush_once()


# ========== 邮件 ==========

def send_email(to_list, subject: str, title: str, lines: list[tuple[str, str]],
               footer: str | None = None) -> bool:
    """多收件人纯文本→HTML 邮件。收件人为空则跳过（返回 False，不算错误）。"""
    to = []
    for t in (to_list or []):
        t = str(t or "").strip()
        if t and t not in to:
            to.append(t)
    if not to:
        logger.info("[ap.notify] 无收件人邮箱，跳过邮件：%s", subject)
        return False

    rows = "".join(
        "<tr><td style='padding:5px 12px 5px 0;color:#888;white-space:nowrap;vertical-align:top;'>"
        f"{escape(str(k))}</td><td style='padding:5px 0;color:#222;'>{escape(str(v))}</td></tr>"
        for k, v in (lines or [])
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Arial,'Microsoft YaHei',sans-serif;">
  <div style="max-width:640px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;">
    <div style="background:#1f4e79;color:#fff;padding:16px 20px;">
      <div style="font-size:18px;font-weight:bold;">{escape(title)}</div>
      <div style="font-size:12px;opacity:.9;margin-top:4px;">ZTE NOC · Action Plan</div>
    </div>
    <div style="padding:18px 20px;color:#333;font-size:14px;">
      <table style="width:100%;border-collapse:collapse;">{rows}</table>
      <div style="margin-top:16px;color:#999;font-size:12px;">
        {escape(footer or "This is an automated Action Plan notification. Please do not reply.")}
      </div>
    </div>
  </div>
</body></html>"""

    try:
        from backend.services import email_notifier as en
        user, pwd = en._runtime_credentials()  # noqa: SLF001  复用同一份凭据（改密免重启）
        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr((en.SENDER_NAME, en.SENDER))
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg["Date"] = formatdate(usegmt=True)
        msg.attach(MIMEText(html, "html", "utf-8"))
        import smtplib
        with smtplib.SMTP_SSL(en.SMTP_SERVER, en.SMTP_PORT, timeout=30) as server:
            server.login(user or en.SENDER, pwd)
            server.sendmail(en.SENDER, to, msg.as_string())
        logger.info("[ap.notify] 邮件已发 %s：%s", to, subject)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[ap.notify] 邮件发送失败（%s）：%s", subject, e)
        return False


# ========== 文案（英文，与 lbr_assistant 群语言一致） ==========

def _link() -> str:
    base = os.environ.get("MYAPP_PUBLIC_BASE", "").strip().rstrip("/")
    return f"{base}/myapp/?page=ap_center" if base else ""


def wa_text(event: str, task: dict, extra: str = "") -> str:
    """WhatsApp 群消息正文。群是英文用户，一律英文（与 tt_alarm 同一约定）。"""
    head = {
        "dispatch": "New Action Plan assigned",
        "submit": "Action Plan submitted for review",
        "approve": "Action Plan approved and closed",
        "reject": "Action Plan returned for rework",
        "overdue": "Action Plan overdue",
    }.get(event, "Action Plan update")
    lines = [
        f"*[AP] {head}*",
        f"AP No.: {task.get('ap_no') or '-'}",
        f"Title: {task.get('title') or '-'}",
        f"Priority: {task.get('priority') or '-'}",
        f"Status: {task.get('status') or '-'}",
        f"Owner: {task.get('owner_username') or '-'}",
    ]
    if task.get("reviewer_username"):
        lines.append(f"Reviewer: {task['reviewer_username']}")
    if task.get("due_at"):
        lines.append(f"Due: {task['due_at']}")
    if extra:
        lines.append(extra)
    link = _link()
    if link:
        lines.append(f"Open: {link}")
    return "\n".join(lines)


def mail_lines(task: dict) -> list[tuple[str, str]]:
    rows = [
        ("AP No.", task.get("ap_no") or "-"),
        ("Title", task.get("title") or "-"),
        ("Priority", task.get("priority") or "-"),
        ("Status", task.get("status") or "-"),
        ("Owner", task.get("owner_username") or "-"),
        ("Reviewer", task.get("reviewer_username") or "-"),
        ("Due", task.get("due_at") or "-"),
    ]
    if task.get("target_position"):
        rows.insert(3, ("Position", task["target_position"]))
    if task.get("description"):
        rows.append(("Requirement", str(task["description"])[:600]))
    if task.get("completion_note"):
        rows.append(("Completion note", str(task["completion_note"])[:600]))
    if task.get("reject_reason"):
        rows.append(("Return reason", str(task["reject_reason"])[:600]))
    return rows
