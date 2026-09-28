"""
任务失败 -> 126 邮箱 通知服务
================================
任务管理（task_runner）检测到任务失败时，通过 126 邮箱（xin83min@126.com）
发送失败告警邮件。凭据来自 credential_store（mail_126 组），支持页面改密后免重启生效。

设计原则（与 weixin_notifier 对齐）：
- 通知失败仅记录日志，绝不影响任务本身的结果记录。
- 同一任务在冷却窗口内只通知一次，避免定时任务反复失败时刷屏邮件。
"""
import smtplib
import time
import logging
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from html import escape

logger = logging.getLogger("email_notifier")

# ========== 配置 ==========
SMTP_SERVER = "smtp.126.com"
SMTP_PORT = 465
SENDER = "xin83min@126.com"
SENDER_NAME = "ZTE NOC 任务监控"
# 任务失败告警收件人（用户指定）
DEFAULT_RECEIVER = "xin83min@126.com"

# 冷却窗口（秒）：窗口内重复失败只通知一次，避免刷屏
COOLDOWN_SECONDS = 30 * 60

_lock = threading.Lock()
_last_notify: dict[str, float] = {}


def _runtime_credentials():
    """运行时获取 126 凭据（环境变量 > DB > credential_store 默认值）。

    不传默认值：`mail_126` 凭据组已带默认用户名/授权码（credential_store.py）。
    2026-09-27 前这里传了硬编码授权码字面量，属重复真相源且已入库。
    """
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        from credential_store import get_credential
    return get_credential("mail_126")


def _build_html(task_id: str, task_name: str, error: str,
                traceback_text, ts: str) -> str:
    """构造失败告警邮件 HTML 正文。错误与堆栈均做 HTML 转义，避免注入/乱码。"""
    err_esc = escape(str(error)[:2000])
    tb_block = ""
    if traceback_text:
        tb_lines = [ln for ln in str(traceback_text).splitlines() if ln.strip()]
        snippet = escape("\n".join(tb_lines[:20])[:4000])
        if snippet:
            tb_block = (
                "<h3 style='margin:14px 0 6px;color:#b00;'>异常堆栈（前 20 行）</h3>"
                "<pre style='white-space:pre-wrap;word-break:break-all;"
                "background:#fff4f4;border:1px solid #f3c2c2;border-radius:6px;"
                "padding:10px;font-size:12px;color:#7a1a1a;'>"
                f"{snippet}</pre>"
            )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Arial,'Microsoft YaHei',sans-serif;">
  <div style="max-width:640px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">
    <div style="background:#c0392b;color:#fff;padding:16px 20px;">
      <div style="font-size:18px;font-weight:bold;">⚠️ 任务执行失败告警</div>
      <div style="font-size:12px;opacity:.9;margin-top:4px;">ZTE NOC · Task Manager</div>
    </div>
    <div style="padding:20px;color:#333;font-size:14px;line-height:1.7;">
      <table style="width:100%;border-collapse:collapse;">
        <tr><td style="padding:6px 0;color:#888;width:96px;vertical-align:top;">任务名称</td>
            <td style="padding:6px 0;font-weight:bold;">{escape(str(task_name))}</td></tr>
        <tr><td style="padding:6px 0;color:#888;vertical-align:top;">任务 ID</td>
            <td style="padding:6px 0;font-family:monospace;">{escape(str(task_id))}</td></tr>
        <tr><td style="padding:6px 0;color:#888;vertical-align:top;">失败时间</td>
            <td style="padding:6px 0;">{escape(ts)}</td></tr>
      </table>
      <h3 style="margin:14px 0 6px;color:#b00;">错误信息</h3>
      <div style="background:#fff4f4;border:1px solid #f3c2c2;border-radius:6px;padding:10px;
                  white-space:pre-wrap;word-break:break-all;color:#7a1a1a;font-size:13px;">{err_esc}</div>
      {tb_block}
      <div style="margin-top:18px;color:#999;font-size:12px;">
        本邮件由任务管理系统自动发送，请勿直接回复。
      </div>
    </div>
  </div>
</body></html>"""


def notify_task_failure(task_id: str, task_name: str, error: str,
                        traceback_text: str | None = None,
                        receiver: str | None = None) -> bool:
    """任务失败时发送 126 邮箱告警邮件。

    Args:
        task_id: 任务 ID
        task_name: 任务显示名
        error: 错误信息字符串
        traceback_text: 可选，完整异常堆栈
        receiver: 可选，覆盖收件人；默认 xin83min@126.com

    Returns:
        True 表示已成功投递（或冷却跳过视为已处理），False 表示发送失败。
        通知失败仅记录日志，不抛出异常、不影响任务流程。
    """
    # 冷却去重：窗口内重复失败只通知一次
    now = time.time()
    with _lock:
        last = _last_notify.get(task_id)
        if last and (now - last) < COOLDOWN_SECONDS:
            logger.info(f"[{task_id}] 失败邮件通知冷却中，跳过（距上次 {int(now - last)}s）")
            return True
        _last_notify[task_id] = now

    to_addr = (receiver or DEFAULT_RECEIVER).strip()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    subject = f"[任务失败告警] {task_name} ({task_id})"
    html = _build_html(task_id, task_name, error, traceback_text, ts)

    try:
        user, pwd = _runtime_credentials()
        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr((SENDER_NAME, SENDER))
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Date"] = formatdate(usegmt=True)
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.login(user or SENDER, pwd)
            server.sendmail(SENDER, [to_addr], msg.as_string())

        logger.info(f"[{task_id}] 失败告警邮件已发送至 {to_addr}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[{task_id}] 失败告警邮件发送失败: {e}")
        return False


def send_status_email(subject: str, title: str, message: str, ts: str,
                      ok: bool = False, source: str = "状态通知",
                      meta_rows: list | None = None,
                      footer: str | None = None,
                      receiver: str | None = None) -> bool:
    """通用的“状态翻转”通知邮件（非“任务执行失败”模板）。

    与 notify_task_failure 共用 SMTP 通道与凭据，但语义不同：用于「某项健康
    状态从正常→异常 / 从异常→恢复」这类事件（如 task_health_alert）。本函数
    不带冷却：去重由调用方的状态文件负责，在这里加冷却会吞掉“已恢复”那条。

    Args:
        subject: 邮件主题
        title: 正文大标题
        message: 正文说明（纯文本，内部做 HTML 转义并保留换行）
        ts: 时间字符串
        ok: True=恢复（绿色），False=异常（红色）
        source: 头部副标题里的来源标识（如 "Task Health"）
        meta_rows: 额外表格行 [(标签, 值), ...]
        footer: 页脚说明（默认自动发送提示）
    """
    to_addr = (receiver or DEFAULT_RECEIVER).strip()
    accent = "#1F8A4C" if ok else "#c0392b"
    msg_esc = escape(str(message))
    rows_html = "".join(
        "<tr><td style='padding:6px 0;color:#888;width:96px;vertical-align:top;'>"
        f"{escape(str(k))}</td>"
        "<td style='padding:6px 0;font-weight:bold;'>"
        f"{escape(str(v))}</td></tr>"
        for k, v in (meta_rows or [])
    )
    table_html = (
        "<table style='width:100%;border-collapse:collapse;'>"
        "<tr><td style='padding:6px 0;color:#888;width:96px;vertical-align:top;'>发生时间</td>"
        f"<td style='padding:6px 0;'>{escape(str(ts))}</td></tr>{rows_html}</table>"
        if (meta_rows or ts) else ""
    )
    foot = footer or "本邮件由任务监控自动发送，仅在状态翻转时通知，请勿直接回复。"
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Arial,'Microsoft YaHei',sans-serif;">
  <div style="max-width:640px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">
    <div style="background:{accent};color:#fff;padding:16px 20px;">
      <div style="font-size:18px;font-weight:bold;">{escape(str(title))}</div>
      <div style="font-size:12px;opacity:.9;margin-top:4px;">ZTE NOC · Task Manager · {escape(str(source))}</div>
    </div>
    <div style="padding:20px;color:#333;font-size:14px;line-height:1.7;">
      {table_html}
      <h3 style="margin:14px 0 6px;color:{accent};">状态说明</h3>
      <div style="background:#f7f7f7;border:1px solid #e3e3e3;border-radius:6px;padding:10px;
                  white-space:pre-wrap;word-break:break-all;color:#333;font-size:13px;">{msg_esc}</div>
      <div style="margin-top:18px;color:#999;font-size:12px;">
        {escape(str(foot))}
      </div>
    </div>
  </div>
</body></html>"""

    try:
        user, pwd = _runtime_credentials()
        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr((SENDER_NAME, SENDER))
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Date"] = formatdate(usegmt=True)
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.login(user or SENDER, pwd)
            server.sendmail(SENDER, [to_addr], msg.as_string())

        logger.info(f"[{source}] 状态通知邮件已发送至 {to_addr}: {title}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[{source}] 状态通知邮件发送失败: {e}")
        return False


def send_ews_status_email(subject: str, title: str, message: str, ts: str,
                          ok: bool = False, receiver: str | None = None) -> bool:
    """发送 EWS 状态翻转通知邮件（降级 / 恢复）。

    与 notify_task_failure 共用同一条 SMTP 通道与凭据，但**不复用失败告警模板**，
    避免把「依赖不可用 / 已恢复」包装成「任务执行失败」。本函数不带冷却——状态
    翻转本身天然去重（每次翻转只调用一次），冷却反而会吞掉"恢复"这条通知。

    Args:
        subject: 邮件主题
        title: 正文标题（如「EWS 已恢复」）
        message: 正文说明文字（纯文本，内部做 HTML 转义）
        ts: 时间字符串
        ok: True = 恢复（绿色），False = 降级（红色）
    """
    to_addr = (receiver or DEFAULT_RECEIVER).strip()
    accent = "#1F8A4C" if ok else "#c0392b"
    msg_esc = escape(str(message))
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Arial,'Microsoft YaHei',sans-serif;">
  <div style="max-width:640px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">
    <div style="background:{accent};color:#fff;padding:16px 20px;">
      <div style="font-size:18px;font-weight:bold;">{escape(str(title))}</div>
      <div style="font-size:12px;opacity:.9;margin-top:4px;">ZTE NOC · Task Manager · EWS 状态通知</div>
    </div>
    <div style="padding:20px;color:#333;font-size:14px;line-height:1.7;">
      <table style="width:100%;border-collapse:collapse;">
        <tr><td style="padding:6px 0;color:#888;width:96px;vertical-align:top;">任务名称</td>
            <td style="padding:6px 0;font-weight:bold;">EWS 恢复后邮件补发</td></tr>
        <tr><td style="padding:6px 0;color:#888;vertical-align:top;">任务 ID</td>
            <td style="padding:6px 0;font-family:monospace;">email_recovery</td></tr>
        <tr><td style="padding:6px 0;color:#888;vertical-align:top;">发生时间</td>
            <td style="padding:6px 0;">{escape(str(ts))}</td></tr>
      </table>
      <h3 style="margin:14px 0 6px;color:{accent};">状态说明</h3>
      <div style="background:#f7f7f7;border:1px solid #e3e3e3;border-radius:6px;padding:10px;
                  white-space:pre-wrap;word-break:break-all;color:#333;font-size:13px;">{msg_esc}</div>
      <div style="margin-top:18px;color:#999;font-size:12px;">
        本邮件仅在 EWS 状态发生翻转时发送，降级期间不会重复告警。请勿直接回复。
      </div>
    </div>
  </div>
</body></html>"""

    try:
        user, pwd = _runtime_credentials()
        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr((SENDER_NAME, SENDER))
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Date"] = formatdate(usegmt=True)
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.login(user or SENDER, pwd)
            server.sendmail(SENDER, [to_addr], msg.as_string())

        logger.info(f"[EWS] 状态通知邮件已发送至 {to_addr}: {title}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[EWS] 状态通知邮件发送失败: {e}")
        return False


def send_test_email(receiver: str | None = None) -> bool:
    """发送一封测试邮件，用于验证 126 邮箱连通性与凭据有效性。

    收件人默认与失败通知一致（xin83min@126.com），可覆盖。
    """
    return notify_task_failure(
        "TEST", "连通性测试（TEST）",
        "这是一封测试邮件，用于验证任务失败邮件通知功能已正确接入 126 邮箱。",
        traceback_text=None,
        receiver=receiver,
    )


# task_runner 通过此名导入（与 weixin_notifier.notify_task_failure 对称）。
# 模块本体函数名为 notify_task_failure，这里补别名，避免 ImportError 触发
# "email_notifier 不可用" 的 no-op 兜底、导致所有任务失败邮件被静默跳过。
notify_task_failure_email = notify_task_failure

