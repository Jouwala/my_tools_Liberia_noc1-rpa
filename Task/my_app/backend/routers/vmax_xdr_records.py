# -*- coding: utf-8 -*-
"""
vmax_xdr_records.py —— XDR Records（分表信令详单）+ 取证存档
==============================================================
「VMAX 用户查询」页第三个视图（`?page=vmax_user_query` 的 XDR Records 页签）。

与 `vmax_xdr_query.py`（合并表 exec_merge_query）的区别：
合并表是「一个号码所有接口的流水」，本路由是**按 XDR 表**查单表明细
（UEMR_XDR / UU_XDR / X2_XDR…），列结构由该表的列头决定 —— UEMR_XDR 带
RSRP/SINR 等空口测量列，排障时必须看这张表。

接口：
- GET    /api/vmax-xdr-records/tables?service_type=32   该类型下可查的 XDR 表
- GET    /api/vmax-xdr-records                          按号码 + 表 + 时间窗查记录
- POST   /api/vmax-xdr-records/saved                    把某条记录存档（取证）
- GET    /api/vmax-xdr-records/saved                    我的存档列表（按用户隔离）
- GET    /api/vmax-xdr-records/saved/{id}               存档详情（含完整字段）
- DELETE /api/vmax-xdr-records/saved/{id}               删除我的存档
- GET    /api/vmax-xdr-records/history                  我的查询历史（审计）

为什么要落库（其余 VMAX 页面都是只读透传）：
信令记录属于用户隐私数据，按运营商合规要求需要能回答「谁在什么时候查了谁」；
同时排障时抓到的关键记录要能存下来复核（上游只留 24~72 小时，过期就没了）。
因此：
- `vmax_xdr_query_log` 记录每次查询（号码打码，不存明文）；
- `vmax_xdr_saved_record` 存用户主动存档的单条记录（完整 payload，仅本人可见）。
两表都是惰性建表，sqlite / pg 双模，写法同 routers/feedback.py。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import get_raw_connection
from backend.routers.vmax_xdr_common import (
    humanize_login, humanize_upstream, mask_msisdn, parse_bound,
)
from backend.services.portal_auth import require_user
from backend.services.vmax_cca.vmax_cca_client import (
    VmaxCcaError, VmaxCcaNotConfigured, VmaxCcaUnavailable, normalize_msisdn,
)
from backend.services.vmax_cca.vmax_xdr_client import (
    XDR_SERVICES, VmaxXdrError, VmaxXdrUnsupported, get_xdr_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vmax-xdr-records", tags=["vmax-xdr-records"])

SAVED_TABLE = "vmax_xdr_saved_record"
LOG_TABLE = "vmax_xdr_query_log"

# 单条存档上限：一行 XDR 通常 50~90 个字段、几 KB；给到 200KB 足够容纳
# 上游加列，同时挡住把整页数据当一条记录塞进来的误用。
MAX_PAYLOAD_BYTES = 200 * 1024
MAX_SAVED_PER_USER = 500


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_tables(conn) -> None:
    """惰性建表 + 索引（sqlite / pg 双模，范式同 routers/feedback.py）。"""
    if isinstance(conn, sqlite3.Connection):
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {SAVED_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                msisdn_mask TEXT NOT NULL,
                service_type TEXT NOT NULL,
                table_name TEXT NOT NULL,
                table_label TEXT,
                record_time TEXT,
                payload TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {LOG_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                msisdn_mask TEXT NOT NULL,
                service_type TEXT NOT NULL,
                table_name TEXT,
                window_start TEXT,
                window_end TEXT,
                records INTEGER NOT NULL DEFAULT 0,
                page INTEGER NOT NULL DEFAULT 1,
                elapsed_ms INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                err_msg TEXT,
                created_at TEXT NOT NULL
            )
        """)
    else:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {SAVED_TABLE} (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                username TEXT NOT NULL,
                msisdn_mask TEXT NOT NULL,
                service_type TEXT NOT NULL,
                table_name TEXT NOT NULL,
                table_label TEXT,
                record_time TEXT,
                payload TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {LOG_TABLE} (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                username TEXT NOT NULL,
                msisdn_mask TEXT NOT NULL,
                service_type TEXT NOT NULL,
                table_name TEXT,
                window_start TEXT,
                window_end TEXT,
                records INTEGER NOT NULL DEFAULT 0,
                page INTEGER NOT NULL DEFAULT 1,
                elapsed_ms INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                err_msg TEXT,
                created_at TEXT NOT NULL
            )
        """)
    conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{SAVED_TABLE}_user ON {SAVED_TABLE}(username)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{SAVED_TABLE}_created ON {SAVED_TABLE}(created_at)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{LOG_TABLE}_user ON {LOG_TABLE}(username)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{LOG_TABLE}_created ON {LOG_TABLE}(created_at)")
    conn.commit()


def _service(service_type: str) -> Dict[str, Any]:
    spec = next((s for s in XDR_SERVICES if s["id"] == service_type), None)
    if spec is None:
        raise HTTPException(
            status_code=422,
            detail="serviceType %s 暂未接入；当前支持 %s"
                   % (service_type, ", ".join(s["id"] for s in XDR_SERVICES)))
    return spec


def _write_log(username: str, msisdn: str, service_type: str, table_name: str,
               window: Dict[str, str], records: int, page: int,
               elapsed_ms: int, status: str, err: str = "") -> None:
    """查询审计：失败也不能影响主流程（取证日志是附加能力，不是业务前置）。"""
    try:
        with get_raw_connection() as conn:
            _ensure_tables(conn)
            conn.execute(
                f"INSERT INTO {LOG_TABLE} (username, msisdn_mask, service_type, table_name, "
                "window_start, window_end, records, page, elapsed_ms, status, err_msg, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (username, mask_msisdn(msisdn), service_type, table_name,
                 window.get("starttime", ""), window.get("endtime", ""),
                 int(records or 0), int(page or 1), int(elapsed_ms or 0),
                 status, (err or "")[:500], _now()))
            conn.commit()
    except Exception as exc:                                          # noqa: BLE001
        logger.warning("[vmax_xdr_records] 写查询审计失败（不影响查询）: %s", exc)


# ============================ 表清单 ============================
@router.get("/tables")
def list_tables(service_type: str = Query("32", description="serviceType，见 /api/vmax-xdr-query/services")):
    """该 serviceType 下可查的 XDR 表清单（上游 get_tabinfo，进程内缓存 10 分钟）。

    上游不可用时客户端回落到静态清单（`XDR_TABLES_FALLBACK`），下拉不会空白。
    """
    spec = _service(service_type)
    try:
        tables = get_xdr_client().tables(service_type)
    except VmaxXdrUnsupported as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except VmaxCcaNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (VmaxCcaUnavailable, VmaxCcaError) as exc:
        raise HTTPException(status_code=502,
                            detail="取 XDR 表清单失败: %s" % exc) from exc
    return {"service_type": service_type, "service_name": spec.get("name_zh") or spec["name"],
            "retention_hours": spec.get("retention_hours"), "tables": tables}


# ============================ 记录查询 ============================
@router.get("")
def query_records(
    msisdn: str = Query(..., min_length=5, max_length=24),
    service_type: str = Query("32"),
    table: str = Query(..., min_length=2, max_length=64,
                       description="表名或 xdr_name（如 UEMR_XDR / fact_lte_uemr）"),
    start: Optional[str] = Query(None, description="窗口起点 YYYY-MM-DD[ HH:MM]，缺省 2 小时前"),
    end: Optional[str] = Query(None, description="窗口终点 YYYY-MM-DD[ HH:MM]，缺省现在"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user: dict = Depends(require_user),
):
    """按号码 + XDR 表查记录（分表详细）。records=0 是业务正常（窗口内无该表记录）。"""
    normalized = normalize_msisdn(msisdn)
    if not re.fullmatch(r"\d{5,20}", normalized):
        raise HTTPException(status_code=422,
                            detail="号码格式不正确：请输入 231 开头的完整数字号码")

    spec = _service(service_type)
    max_hours = int(spec.get("retention_hours") or 72)
    default_hours = min(2, max_hours)

    end_dt = parse_bound(end, end_of=True)
    start_dt = (parse_bound(start, end_of=False) if start
                else end_dt - timedelta(hours=default_hours))
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt
    if end_dt - start_dt > timedelta(hours=max_hours):
        raise HTTPException(
            status_code=422,
            detail="%s 的时间窗跨度不能超过 %d 小时（上游只保留最近 %d 小时的数据）"
                   % (spec.get("name_zh") or spec["name"], max_hours, max_hours))

    fmt = "%Y-%m-%d %H:%M:%S.000"          # 上游按毫秒边界切分区
    window = {"starttime": start_dt.strftime(fmt), "endtime": end_dt.strftime(fmt)}
    t0 = time.monotonic()
    try:
        result = get_xdr_client().query_table(
            normalized, service_type, table, window["starttime"], window["endtime"],
            page=page, page_size=page_size)
    except VmaxXdrUnsupported as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except VmaxCcaNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VmaxCcaUnavailable as exc:
        logger.warning("[vmax_xdr_records] 上游不可用 %s/%s: %s", mask_msisdn(normalized), table, exc)
        _write_log(user.get("username", ""), normalized, service_type, table,
                   window, 0, page, int((time.monotonic() - t0) * 1000), "error", str(exc))
        raise HTTPException(status_code=502,
                            detail="XDR 查询服务暂不可用: %s" % humanize_login(str(exc))) from exc
    except VmaxXdrError as exc:
        logger.warning("[vmax_xdr_records] 查询 %s/%s 失败: %s", mask_msisdn(normalized), table, exc)
        _write_log(user.get("username", ""), normalized, service_type, table,
                   window, 0, page, int((time.monotonic() - t0) * 1000), "error", str(exc))
        detail = humanize_upstream(str(exc))
        if detail == str(exc):
            raise HTTPException(status_code=502, detail="XDR 查询失败: %s" % exc) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
    except VmaxCcaError as exc:
        raise HTTPException(status_code=502, detail="XDR 查询失败: %s" % exc) from exc

    _write_log(user.get("username", ""), normalized, service_type,
               result.get("table") or table, window, result.get("records", 0), page,
               int((time.monotonic() - t0) * 1000), "ok")
    return result


# ============================ 存档（取证） ============================
class SavedRecordIn(BaseModel):
    msisdn: str = Field(..., min_length=5, max_length=24)
    service_type: str = Field(..., max_length=16)
    table: str = Field(..., min_length=2, max_length=64)
    table_label: Optional[str] = Field(None, max_length=64, description="界面显示名，如 UEMR_XDR")
    record_time: Optional[str] = Field(None, max_length=64)
    note: Optional[str] = Field(None, max_length=500)
    payload: Dict[str, Any]


@router.post("/saved")
def save_record(body: SavedRecordIn, user: dict = Depends(require_user)):
    """把一条记录存档（上游只保留 24~72 小时，关键记录需要落库才能复核）。

    只存本人可见：列表/详情都按 username 过滤，不做跨用户共享。
    """
    normalized = normalize_msisdn(body.msisdn)
    spec = _service(body.service_type)
    raw = json.dumps(body.payload, ensure_ascii=False)
    if len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="记录过大，无法存档（单条上限 200KB）")

    # 记录时间：优先用调用方给的，其次按域的默认时间字段从 payload 取
    record_time = (body.record_time or "").strip()
    if not record_time:
        for key in (spec.get("time_field"), "btime", "start_time", "etime"):
            if key and body.payload.get(key):
                record_time = str(body.payload[key])[:32]
                break

    username = user.get("username", "unknown")
    with get_raw_connection() as conn:
        _ensure_tables(conn)
        count = conn.execute(
            f"SELECT COUNT(*) FROM {SAVED_TABLE} WHERE username = ?", (username,)
        ).fetchone()[0]
        if count >= MAX_SAVED_PER_USER:
            raise HTTPException(
                status_code=409,
                detail="存档已达上限 %d 条，请先在「已存记录」里删除不需要的记录" % MAX_SAVED_PER_USER)
        insert_sql = (
            f"INSERT INTO {SAVED_TABLE} (username, msisdn_mask, service_type, table_name, "
            "table_label, record_time, payload, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        params = (username, mask_msisdn(normalized), body.service_type,
                  body.table, body.table_label or body.table, record_time, raw,
                  (body.note or "").strip() or None, _now())
        if isinstance(conn, sqlite3.Connection):
            conn.execute(insert_sql, params)
            conn.commit()
            new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            new_id = conn.execute(insert_sql + " RETURNING id", params).fetchone()[0]
            conn.commit()
    logger.info("[vmax_xdr_records] %s 存档记录 #%s (%s/%s)",
                username, new_id, body.service_type, body.table)
    return {"status": "ok", "id": new_id,
            "message": "记录已存档，可在「已存记录」中复核"}


@router.get("/saved")
def list_saved(
    user: dict = Depends(require_user),
    service_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None, description="按备注 / 表名 / 号码打码串模糊匹配"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """我的存档列表（按创建时间倒序，不含完整 payload，避免列表过大）。"""
    username = user.get("username", "unknown")
    where, params = ["username = ?"], [username]
    if service_type:
        where.append("service_type = ?")
        params.append(service_type)
    if keyword:
        kw = "%%%s%%" % keyword.strip()
        where.append("(note LIKE ? OR table_name LIKE ? OR msisdn_mask LIKE ?)")
        params.extend([kw, kw, kw])
    where_sql = "WHERE " + " AND ".join(where)
    with get_raw_connection() as conn:
        _ensure_tables(conn)
        total = conn.execute(f"SELECT COUNT(*) FROM {SAVED_TABLE} {where_sql}",
                             params).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, msisdn_mask, service_type, table_name, table_label, record_time, "
            f"note, created_at FROM {SAVED_TABLE} {where_sql} "
            "ORDER BY id DESC LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
    return {"total": total, "rows": [dict(r) for r in rows]}


@router.get("/saved/{record_id}")
def get_saved(record_id: int, user: dict = Depends(require_user)):
    """存档详情：完整字段（payload 原样返回，前端按 key/value 渲染）。"""
    username = user.get("username", "unknown")
    with get_raw_connection() as conn:
        _ensure_tables(conn)
        row = conn.execute(
            f"SELECT * FROM {SAVED_TABLE} WHERE id = ? AND username = ?",
            (record_id, username)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="存档不存在或不属于当前用户")
    item = dict(row)
    try:
        item["payload"] = json.loads(item.get("payload") or "{}")
    except ValueError:
        item["payload"] = {}
    return item


@router.delete("/saved/{record_id}")
def delete_saved(record_id: int, user: dict = Depends(require_user)):
    """删除我的存档（他人存档一律 404，不暴露存在性）。"""
    username = user.get("username", "unknown")
    with get_raw_connection() as conn:
        _ensure_tables(conn)
        cur = conn.execute(f"DELETE FROM {SAVED_TABLE} WHERE id = ? AND username = ?",
                           (record_id, username))
        conn.commit()
        deleted = cur.rowcount or 0
    if not deleted:
        raise HTTPException(status_code=404, detail="存档不存在或不属于当前用户")
    return {"status": "ok", "deleted": deleted}


@router.get("/history")
def query_history(
    user: dict = Depends(require_user),
    limit: int = Query(50, ge=1, le=200),
):
    """我的查询历史（审计留痕，号码已打码）。"""
    username = user.get("username", "unknown")
    with get_raw_connection() as conn:
        _ensure_tables(conn)
        rows = conn.execute(
            f"SELECT id, msisdn_mask, service_type, table_name, window_start, window_end, "
            f"records, page, elapsed_ms, status, err_msg, created_at FROM {LOG_TABLE} "
            "WHERE username = ? ORDER BY id DESC LIMIT ?", (username, limit)).fetchall()
    return {"rows": [dict(r) for r in rows]}
