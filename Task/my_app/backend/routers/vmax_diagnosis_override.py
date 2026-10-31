# -*- coding: utf-8 -*-
"""
vmax_diagnosis_override.py —— 诊断结论的人工覆写（留痕）
=============================================================================
方案 §4.5，评审意见 4：「允许人工覆写」。

## 为什么覆写要落库、要留痕

诊断是规则算出来的，但排障的人可能知道规则不知道的事
（「这个小区今天在割接」「用户自己重启过手机」）。
覆写不落库的话，下一个人打开同一条投诉看到的是系统判定，
会得出与上一个人相反的结论 —— 这在投诉闭环里是硬伤。

## 五条规则（与方案 §4.5 一一对应，改之前先读）

1. **原始结论永不覆盖**：`verdict_auto` 单独存一列。
   系统判定是可复现的证据链，覆盖掉它就毁掉了取证基础。
2. **理由必填 ≥ 10 字**：低于 10 字基本等于没写（"没问题"/"已处理"），
   起不到留痕作用。理由会原样进导出文件。
3. **按用户隔离**：同 `vmax_xdr_saved_record`，别人的覆写看不到，
   避免同一条投诉被多人互相改写。
4. **留痕**：记 username + 时间。
5. **只增不删**：撤销用软删（`revoked_at`），历史行仍在表里。
   硬删会让「谁改过、改了几次」这段历史整段消失。

## 惰性建表

sqlite / pg 双模，写法照抄 `routers/vmax_xdr_records.py::_ensure_tables`。
表 `vmax_diagnosis_override`：

    id, username, msisdn_mask, window_start, window_end,
    verdict_auto, verdict_manual, reason,
    created_at, updated_at, revoked_at
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import get_raw_connection
from backend.routers.vmax_xdr_common import mask_msisdn
from backend.services.portal_auth import require_user
from backend.services.vmax_cca.vmax_cca_client import normalize_msisdn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vmax-diagnosis/override", tags=["vmax-diagnosis"])

TABLE = "vmax_diagnosis_override"

# 理由下限：低于 10 字起不到留痕作用（见模块头规则 2）
MIN_REASON_LEN = 10
MAX_REASON_LEN = 500
MAX_VERDICT_LEN = 300


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_table(conn) -> None:
    """惰性建表（sqlite / pg 双模）。"""
    if isinstance(conn, sqlite3.Connection):
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                msisdn_mask TEXT NOT NULL,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                verdict_auto TEXT,
                verdict_manual TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                revoked_at TEXT
            )
        """)
    else:
        # ⚠ PG 上不能用 COALESCE(时间列, '9999') 这类套路（见 AGENTS.md 4.11），
        # 这里全部用 NULL + IS NULL 判断，保持与 sqlite 同一套 SQL。
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                username TEXT NOT NULL,
                msisdn_mask TEXT NOT NULL,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                verdict_auto TEXT,
                verdict_manual TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                revoked_at TEXT
            )
        """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{TABLE}_lookup
        ON {TABLE} (username, msisdn_mask, window_start, window_end)
    """)


def _row_to_dict(row) -> Dict[str, Any]:
    """按列名映射（sqlite Row / pg dict cursor 两种都吃）。"""
    if isinstance(row, sqlite3.Row):
        return {k: row[k] for k in row.keys()}
    if isinstance(row, dict):
        return dict(row)
    # pg 的 RealDictRow 就是 dict；退一步按位置走已知列序
    cols = ["id", "username", "msisdn_mask", "window_start", "window_end",
            "verdict_auto", "verdict_manual", "reason",
            "created_at", "updated_at", "revoked_at"]
    return {c: row[i] for i, c in enumerate(cols) if i < len(row)}


class OverrideIn(BaseModel):
    msisdn: str = Field(..., min_length=5, max_length=24)
    start: Optional[str] = None
    end: Optional[str] = None
    verdict_auto: str = Field("", max_length=500)
    verdict_manual: str = Field(..., max_length=MAX_VERDICT_LEN)
    reason: str = Field(..., max_length=MAX_REASON_LEN)


@router.get("")
def get_override(
    msisdn: str = Query(..., min_length=5, max_length=24),
    start: str = Query(""),
    end: str = Query(""),
    user: dict = Depends(require_user),
):
    """取当前用户对该号码 + 窗口的**有效**覆写（未撤销的那条，取最新）。

    没有就返回 `{"data": null}` —— 前端据此决定按钮文案
    （「覆写结论」vs「修改覆写」），不报错。
    """
    normalized = normalize_msisdn(msisdn)
    masked = mask_msisdn(normalized)
    username = user.get("username", "unknown")
    with get_raw_connection() as conn:
        _ensure_table(conn)
        cur = conn.execute(
            f"SELECT * FROM {TABLE} WHERE username = ? AND msisdn_mask = ? "
            f"AND window_start = ? AND window_end = ? AND revoked_at IS NULL "
            f"ORDER BY id DESC LIMIT 1",
            (username, masked, start or "", end or ""),
        )
        row = cur.fetchone()
        return {"data": _row_to_dict(row) if row else None}


@router.post("")
def submit_override(body: OverrideIn, user: dict = Depends(require_user)):
    """提交覆写。

    同一 (用户, 号码, 窗口) 只保留一条有效覆写：再次提交是**更新**
    同一行（`updated_at` 变），而不是插一条新的 ——
    否则页面上「我到底以哪条为准」会说不清。
    但**历史不会被抹掉**：`verdict_auto` 每次都被最新系统判定覆盖，
    `created_at` 保持第一次的时间，撤销走软删。
    """
    verdict = (body.verdict_manual or "").strip()
    reason = (body.reason or "").strip()
    if not verdict:
        raise HTTPException(status_code=422, detail="请填写人工判定结论")
    if len(reason) < MIN_REASON_LEN:
        raise HTTPException(
            status_code=422,
            detail="覆写理由至少 %d 个字（理由会写进导出报告作为留痕依据）" % MIN_REASON_LEN)

    normalized = normalize_msisdn(body.msisdn)
    masked = mask_msisdn(normalized)
    username = user.get("username", "unknown")
    start = (body.start or "").strip()
    end = (body.end or "").strip()
    now = _now()

    with get_raw_connection() as conn:
        _ensure_table(conn)
        cur = conn.execute(
            f"SELECT id FROM {TABLE} WHERE username = ? AND msisdn_mask = ? "
            f"AND window_start = ? AND window_end = ? AND revoked_at IS NULL "
            f"ORDER BY id DESC LIMIT 1",
            (username, masked, start, end),
        )
        row = cur.fetchone()
        if row:
            # sqlite Row 与 pg dict 都支持 [0] / ["id"]；按形状取
            oid = row["id"] if isinstance(row, dict) else row[0]
            conn.execute(
                f"UPDATE {TABLE} SET verdict_auto = ?, verdict_manual = ?, reason = ?, "
                f"updated_at = ? WHERE id = ?",
                (body.verdict_auto or "", verdict, reason, now, oid),
            )
        else:
            conn.execute(
                f"INSERT INTO {TABLE} (username, msisdn_mask, window_start, window_end, "
                f"verdict_auto, verdict_manual, reason, created_at, updated_at, revoked_at) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (username, masked, start, end,
                 body.verdict_auto or "", verdict, reason, now, now),
            )

        cur = conn.execute(
            f"SELECT * FROM {TABLE} WHERE username = ? AND msisdn_mask = ? "
            f"AND window_start = ? AND window_end = ? AND revoked_at IS NULL "
            f"ORDER BY id DESC LIMIT 1",
            (username, masked, start, end),
        )
        out = cur.fetchone()
        return {"data": _row_to_dict(out) if out else None}


@router.delete("/{override_id}")
def revoke_override(override_id: int, user: dict = Depends(require_user)):
    """撤销覆写（软删，留痕）。

    只允许撤销自己的记录；别人的记录一律 404（不暴露存在性）。
    """
    username = user.get("username", "unknown")
    with get_raw_connection() as conn:
        _ensure_table(conn)
        cur = conn.execute(
            f"SELECT id FROM {TABLE} WHERE id = ? AND username = ? AND revoked_at IS NULL",
            (override_id, username),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="没有可撤销的覆写记录")
        conn.execute(
            f"UPDATE {TABLE} SET revoked_at = ?, updated_at = ? WHERE id = ?",
            (_now(), _now(), override_id),
        )
    return {"ok": True}


@router.get("/history")
def list_history(
    msisdn: str = Query(..., min_length=5, max_length=24),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_user),
):
    """该号码的全部覆写历史（含已撤销）—— 给审计与交接用。"""
    normalized = normalize_msisdn(msisdn)
    masked = mask_msisdn(normalized)
    username = user.get("username", "unknown")
    with get_raw_connection() as conn:
        _ensure_table(conn)
        cur = conn.execute(
            f"SELECT * FROM {TABLE} WHERE username = ? AND msisdn_mask = ? "
            f"ORDER BY id DESC LIMIT ?",
            (username, masked, limit),
        )
        return {"data": [_row_to_dict(r) for r in cur.fetchall() or []]}
