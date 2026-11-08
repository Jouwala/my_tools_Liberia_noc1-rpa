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

## 诊断快照（P3-3，2026-11-07）

`verdict`（结论/四维分/证据）是**纯前端规则算出来的**
（`frontend/src/pages/vmaxDiagnosisRules.ts::buildVerdict`），接口不下发。
所以 `verdict_auto` 只是「客户端声明的结论」，事后从库里无法复现当时的判定依据。
为可审计，提交覆写时随记录存一份 `verdict_snapshot`（JSON 字符串）：
结论 + 四维分与证据 + 语音/OTT/游戏关键指标 + 各数据源 ok/truncated/error +
分析窗口 + 投诉类型 + IMSI（若有）。

快照只存**计数与阈值数字**、不存原始话单行，因此**不含号码明文**
（号码仍只落在 `msisdn_mask`，与其它 VMAX 留痕表同一写法）。

## 惰性建表 + 老库加列

sqlite / pg 双模，写法照抄 `routers/vmax_xdr_records.py::_ensure_tables`。
表 `vmax_diagnosis_override`：

    id, username, msisdn_mask, window_start, window_end,
    verdict_auto, verdict_manual, reason,
    created_at, updated_at, revoked_at, verdict_snapshot

**迁移**：本表是惰性建表，线上库里早就有历史行 —— 只改建表语句对老库不生效
（POST 会直接报 `no such column` / `column does not exist`）。所以 `_ensure_table`
建表后调用 `_migrate_columns`：列枚举走 `dialect_helpers.table_columns`
（sqlite `PRAGMA table_info` / pg `information_schema.columns`），缺列时执行
同一句 `ALTER TABLE ... ADD COLUMN verdict_snapshot TEXT` —— 这条语法两方言一致，
不需要各写一份。重复执行无副作用（先查后加），并发下另一请求先加成功也不报错。

**回滚**：不需要删列。快照列可空，老行 `NULL` 一律视为「当时未存档」，
`_row_to_dict` 原样回 `None`，读取端（前端弹窗/导出）按缺失处理；
真要回退只需停止读写该列，旧代码的 SELECT * 会多出一列、不影响既有字段。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import get_raw_connection
from backend.dialect_helpers import table_columns
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

# 诊断快照列名与体积上限（P3-3）。上限按 UTF-8 **字节**算：中文快照按字符数
# 会放过 ~3 倍体积；典型快照（结论 + 四维分 + 4 源状态 + 关键指标）实测 3~6KB，
# 20KB 留足余量，同时挡住「把整页原始话单塞进快照」那种把表撑大的用法。
SNAPSHOT_COL = "verdict_snapshot"
MAX_SNAPSHOT_BYTES = 20 * 1024


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
                revoked_at TEXT,
                verdict_snapshot TEXT
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
                revoked_at TEXT,
                verdict_snapshot TEXT
            )
        """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{TABLE}_lookup
        ON {TABLE} (username, msisdn_mask, window_start, window_end)
    """)
    # 老库补列（幂等，见模块头「惰性建表 + 老库加列」）
    _migrate_columns(conn)


def _migrate_columns(conn) -> None:
    """给已存在的旧表补 `verdict_snapshot` 列（sqlite / pg 双模、幂等）。

    为什么要单独做：`CREATE TABLE IF NOT EXISTS` 只在表不存在时生效，
    线上库早就有这张表和历史行，改 CREATE 语句救不了老库 ——
    POST 会在写入时直接报「列不存在」，而且只在真提交覆写时才暴露。

    方言处理（AGENTS.md 六.1：不得写成只有 PG 能跑）：
      - 列枚举交给 `dialect_helpers.table_columns`：sqlite 走 `PRAGMA table_info`，
        pg 走 `information_schema.columns`（带 `current_schemas(false)` 限定）；
      - 加列用 `ALTER TABLE ... ADD COLUMN ... TEXT` —— 这条**两方言语法一致**，
        不需要分支（sqlite 与 PG 都不支持裸 `ADD COLUMN` 已存在的列，所以先查后加）。
    """
    existing = set(table_columns(conn, TABLE))
    if SNAPSHOT_COL in existing:
        return
    try:
        conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {SNAPSHOT_COL} TEXT")
        logger.info("[vmax_diagnosis_override] 惰性迁移：已补列 %s", SNAPSHOT_COL)
    except Exception:
        # 并发下另一个请求可能刚加过这一列（pg duplicate_column / sqlite duplicate column），
        # 重新枚举确认；确实还没加上说明是真故障，照原样上抛，不吞。
        if SNAPSHOT_COL not in set(table_columns(conn, TABLE)):
            raise


def _normalize_snapshot(raw: Optional[str]) -> Optional[str]:
    """校验并归一化诊断快照（JSON 字符串，可空）。

    - 空串 / None → None：老客户端或「本次不重算」，按「未提供」处理，
      更新时保留库里已有快照（见 submit_override 的 COALESCE）。
    - UTF-8 字节数超过 20KB → 422（人话错误；按字节而不是字符，避免中文快照按
      字符数放过近 3 倍体积）。
    - 不是合法 JSON 对象 → 422：存进去的必须是审计端能解析的结构，不是任意文本。

    返回原字符串（不重新序列化）：审计要的是提交当时那一份，格式化只会丢信息。
    """
    text = (raw or "").strip()
    if not text:
        return None
    size = len(text.encode("utf-8"))
    if size > MAX_SNAPSHOT_BYTES:
        raise HTTPException(
            status_code=422,
            detail=(f"诊断快照过大（{size} 字节，上限 {MAX_SNAPSHOT_BYTES // 1024}KB）。"
                    "快照只该放结论、四维分、关键指标与数据源状态，不要塞原始话单"),
        )
    try:
        obj = json.loads(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="诊断快照不是合法 JSON，无法存档",
        ) from exc
    if not isinstance(obj, dict):
        raise HTTPException(
            status_code=422, detail="诊断快照必须是 JSON 对象（{...}）",
        )
    return text


def _row_to_dict(row) -> Dict[str, Any]:
    """按列名映射（sqlite Row / pg dict cursor 两种都吃）。"""
    if isinstance(row, sqlite3.Row):
        return {k: row[k] for k in row.keys()}
    if isinstance(row, dict):
        return dict(row)
    # pg 的 RealDictRow 就是 dict；退一步按位置走已知列序
    # ⚠ 老库是 ALTER 加列，新库是建表时加在最后 —— 两边列序一致，都排在 revoked_at 之后
    cols = ["id", "username", "msisdn_mask", "window_start", "window_end",
            "verdict_auto", "verdict_manual", "reason",
            "created_at", "updated_at", "revoked_at", SNAPSHOT_COL]
    return {c: row[i] for i, c in enumerate(cols) if i < len(row)}


class OverrideIn(BaseModel):
    msisdn: str = Field(..., min_length=5, max_length=24)
    start: Optional[str] = None
    end: Optional[str] = None
    verdict_auto: str = Field("", max_length=500)
    verdict_manual: str = Field(..., max_length=MAX_VERDICT_LEN)
    reason: str = Field(..., max_length=MAX_REASON_LEN)
    # 完整 verdict 快照（前端 JSON.stringify 后的字符串），落库列名为 `verdict_snapshot`
    # （入参叫 snapshot、表列叫 verdict_snapshot：与 GET/history 回读的字段名保持一致）。
    # 长度/格式在 _normalize_snapshot 里显式校验 —— 不用 Field(max_length=...)
    # 是为了按**字节**限长并给中文人话错误，而不是 pydantic 的英文默认报文。
    snapshot: Optional[str] = Field(
        None, description="提交时前端的完整诊断快照（JSON 字符串，<=20KB），落库列 verdict_snapshot")


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

    诊断快照（入参 `snapshot` → 列 `verdict_snapshot`）随本次提交一起存档：
    - 本次带了快照 → 覆盖为本次的（新增/更新都写）；
    - 本次没带（`None`/空串，如老客户端或只改理由）→ 更新时**保留**库里已有快照，
      用 `COALESCE(?, verdict_snapshot)`（两方言都支持标量 COALESCE）；
      INSERT 时自然落 NULL。避免「顺手改个理由」把审计依据清空。
    """
    verdict = (body.verdict_manual or "").strip()
    reason = (body.reason or "").strip()
    if not verdict:
        raise HTTPException(status_code=422, detail="请填写人工判定结论")
    if len(reason) < MIN_REASON_LEN:
        raise HTTPException(
            status_code=422,
            detail="覆写理由至少 %d 个字（理由会写进导出报告作为留痕依据）" % MIN_REASON_LEN)
    # 快照校验放在写库之前：非法/超长直接 422，不留半条记录
    snapshot = _normalize_snapshot(body.snapshot)

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
                f"verdict_snapshot = COALESCE(?, verdict_snapshot), updated_at = ? "
                f"WHERE id = ?",
                (body.verdict_auto or "", verdict, reason, snapshot, now, oid),
            )
        else:
            conn.execute(
                f"INSERT INTO {TABLE} (username, msisdn_mask, window_start, window_end, "
                f"verdict_auto, verdict_manual, reason, created_at, updated_at, revoked_at, "
                f"{SNAPSHOT_COL}) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                (username, masked, start, end,
                 body.verdict_auto or "", verdict, reason, now, now, snapshot),
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
