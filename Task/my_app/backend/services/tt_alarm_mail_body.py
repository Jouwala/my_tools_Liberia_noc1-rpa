"""P1 TT 通报邮件的**正文构造**（纯函数，可单测）。

两种邮件（用户 2026-10-06 指定）：

  1. **首次通报**（`build_notified_body`）—— 每单**第一次**推送确认发出后发。
     重报（20 分钟停滞再推）**不发**邮件，避免同一单刷屏。
  2. **结束汇总**（`build_summary_body`）—— 该单告警清除（`alarm_clear_time`
     非空）后发，给完整生命周期时间轴与总历时。

## 语言

主题与正文**均为英文**（用户明确要求 "注意使用英文"）。正文以现有 WhatsApp
英文文本为主体 —— 该文本已由分析引擎按英文渲染，不重复翻译。

## 「取不到给 —」是硬规矩

项目约定：取值一律「取不到给 —，不得给 0」（见 `tt_alarm_message.dash`）。
时间差同理 —— 算不出来给 `-`，绝不默认 0 分钟（那会谎报"秒级恢复"）。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.services.tt_alarm_message import norm_alarm_code as _norm_code
from backend.services.tt_alarm_message import s as _s

# 主题（英文，用户指定）
SUBJECT_NOTIFIED = "P1 TT Progress Notification"
SUBJECT_SUMMARY = "P1 TT Progress Notification - Closed"


def _parse_ts(v: Any) -> Optional[datetime]:
    """宽松解析 eFlow 的时间文本（`YYYY-MM-DD HH:MM:SS[.ffffff]`）。失败返回 None。

    只认这几种格式：eFlow 的时间列实测都是该文本格式（毫秒/微秒尾巴可能有）。
    解析不出来时**返回 None 让上层显示 —**，不猜、不补当前时间。
    """
    if isinstance(v, datetime):
        return v
    txt = _s(v).replace("T", " ")
    if not txt:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def _fmt_minutes(start: Any, end: Any) -> str:
    """两个时间戳之间的分钟数（人类可读）；任一解析失败 → '-'（不是 0）。"""
    a, b = _parse_ts(start), _parse_ts(end)
    if not a or not b:
        return "-"
    mins = (b - a).total_seconds() / 60.0
    if mins < 0:
        # 清除早于发生 = 数据异常，如实说明而不是显示负数
        return f"invalid ({int(mins)} min)"
    if mins < 60:
        return f"{mins:.0f} min"
    return f"{mins / 60:.1f} h ({mins:.0f} min)"


def _header(row: Dict[str, Any]) -> List[str]:
    """邮件通用的头部三行（单号/级别/站点），缺值一律 —。"""
    tt = _s(row.get("tt_no")) or "-"
    sev = _s(row.get("ticket_severity")) or "-"
    site = _s(row.get("site_name")) or _s(row.get("site_id")) or "-"
    # 告警码必须归一化：`eflow_tt.alarm_code` 经同步链路后常带浮点尾巴
    # （'99933.0'），库里两种写法并存；邮件里显示 '.0' 会让人以为是另一个码。
    code = _s(row.get("_alarm_code_norm")) or _norm_code(row.get("alarm_code")) or "-"
    title = _s(row.get("title"))
    lines = [f"TT No:   {tt}", f"Severity: {sev}", f"Site:    {site}",
             f"Alarm:   {code}"]
    if title:
        lines.append(f"Title:   {title}")
    return lines


def build_notified_body(row: Dict[str, Any], wa_text: str) -> str:
    """首次通报正文：头部字段 + WhatsApp 那份完整分析文本。

    `wa_text` 直接复用已渲染好的消息（含里程碑时间轴），保证**邮件与群里
    看到的是同一份内容** —— 用户要求「与 WhatsApp 消息同一份内容」。
    """
    lines = ["P1 TT Progress Notification", "=" * 46, ""]
    lines += _header(row)
    occurred = _s(row.get("alarm_occur_time")) or "-"
    lines.append(f"Occurred: {occurred}")
    lines += ["", "-" * 46, "Analysis", "-" * 46, ""]
    lines.append(_s(wa_text) or "(no analysis text)")
    lines += ["", "-" * 46,
              "This is an automated notification. Please do not reply."]
    return "\n".join(lines)


def build_summary_body(row: Dict[str, Any], wa_text: Optional[str] = None) -> str:
    """结束汇总正文：生命周期时间轴 + 总历时（该单已清除）。

    `wa_text` 可选 —— 分析引擎对已结束的单可能取不到数据；此时传 None，
    正文只给可靠的时间轴部分（不编造分析内容）。
    """
    occurred = _s(row.get("alarm_occur_time"))
    cleared = _s(row.get("alarm_clear_time"))
    created = _s(row.get("created_time"))
    modified = _s(row.get("last_modified_time"))

    lines = ["P1 TT Progress Notification - CLOSED", "=" * 46, ""]
    lines += _header(row)
    lines += ["", "-" * 46, "Timeline", "-" * 46]
    lines.append(f"Alarm occurred : {occurred or '-'}")
    if created:
        lines.append(f"TT created     : {created}")
    lines.append(f"Alarm cleared  : {cleared or '-'}")
    if modified:
        lines.append(f"Last update    : {modified}")
    lines += ["",
              f"Total duration (occurred -> cleared): "
              f"{_fmt_minutes(occurred, cleared)}"]

    if wa_text:
        lines += ["", "-" * 46, "Analysis", "-" * 46, "", _s(wa_text)]
    else:
        lines += ["", "Analysis unavailable for this closed ticket."]

    lines += ["", "-" * 46,
              "This is an automated notification. Please do not reply."]
    return "\n".join(lines)
