# -*- coding: utf-8 -*-
"""
vmax_xdr_common.py —— VMAX XDR 两个路由（合并表 / 分表 Records）共用的小工具
================================================================================
时间窗解析、号码脱敏、上游 operation code 翻译这三件事在两个路由里一模一样，
放一处避免两份错误码表各自漂移（AGENTS.md 三.11 不造第二份）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException

# 上游错误码 -> 给用户看的中文说明。直接抛 operation code 用户看不懂，
# 且极易把「窗口超出保留期」误判成「系统故障」（2026-10-26 实测踩过）。
UPSTREAM_HINTS = {
    # 2026-10-27 实测：同一张表换个号码/换个小时就可能回这个码，含义是「该窗口无记录」，
    # 不只是「超出保留期」。文案不能写成「请缩小窗口」——那会把「本来就没数据」
    # 误导成「窗口选大了」，用户越缩越查不到。
    "3100100202": "该时间范围内无数据（可能是该号码在这张表没有记录，或时段超出上游保留期）",
    "3100100314": "查询域不匹配（该类型的服务域配置有误，请联系管理员）",
    "3100100319": "该类型暂不支持当前查询方式（33/34 尚未接入）",
    "3100100303": "上游拒绝了本次查询（通常是服务类型或表名参数不匹配）",
}


def humanize_upstream(msg: str) -> str:
    """把上游 errMsg 里的 operation code 翻成中文；认不出时原样返回。"""
    for code, hint in UPSTREAM_HINTS.items():
        if code in msg:
            return hint
    return msg


def humanize_login(msg: str) -> str:
    """登录类失败的人话版（见 13-operations.md「VMAX 门户并发会话被占满」）。

    原文 `The maximum number of connections for the user is reached` 只说明
    「连不上了」，用户会本能地连点重试 —— 那恰好会延长恢复时间，所以要显式劝阻。
    """
    if "maximum number of connections" in msg.lower():
        return ("VMAX 门户会话已满（同账号并发连接达上限）。请等待约 30 分钟让旧会话超时，"
                "期间不要连续重试，否则会延长恢复时间")
    return msg


def mask_msisdn(msisdn: str) -> str:
    """日志/审计里只留号码头尾，中间打码。"""
    if len(msisdn) <= 6:
        return "*" * len(msisdn)
    return msisdn[:4] + "*" * (len(msisdn) - 6) + msisdn[-2:]


def parse_bound(raw: Optional[str], end_of: bool) -> datetime:
    """解析 "YYYY-MM-DD" / "YYYY-MM-DD HH:MM[:SS]"，日粒度补全天边界。"""
    if not raw:
        return datetime.now().replace(minute=59 if end_of else 0,
                                      second=59 if end_of else 0, microsecond=0)
    text = str(raw).strip().replace("T", " ")
    day_only = len(text) <= 10
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise HTTPException(status_code=422,
                                detail="时间格式不正确：请用 YYYY-MM-DD 或 YYYY-MM-DD HH:MM") from exc
    if day_only:
        dt = dt.replace(hour=23 if end_of else 0, minute=59 if end_of else 0,
                        second=59 if end_of else 0)
    return dt
