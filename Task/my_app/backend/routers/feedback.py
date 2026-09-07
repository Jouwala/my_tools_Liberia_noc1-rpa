# -*- coding: utf-8 -*-
"""
feedback.py - 问题登记（用户反馈）API
=====================================
供前端「问题登记」页面使用，任何内网用户都可提交问题反馈：
- POST   /api/feedback          提交问题（姓名/联系方式/类型/优先级/关联页面/描述）
- GET    /api/feedback          列表（支持 status/type/priority/keyword 筛选 + 分页）
- GET    /api/feedback/stats    按状态/类型/优先级聚合计数（页面顶部统计卡）
- PUT    /api/feedback/{id}     更新处理状态/处理备注（open → processing → resolved/rejected）
- DELETE /api/feedback/{id}     删除登记记录

存储：db/app.db 表 issue_reports（sqlite/pg 双模，首次访问惰性建表，
写法与 task_runner._ensure_queue_table 一致）。
与 settings / email_recipients 路由风格一致：内网本地访问不做额外鉴权。
"""
import logging
import sqlite3
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.database import get_raw_connection
from backend.dialect_helpers import table_columns

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

TABLE = "issue_reports"

# 枚举白名单（前后端约定一致；非法值直接 400，避免脏数据）
TYPES = ("bug", "data", "feature", "other")
PRIORITIES = ("low", "medium", "high", "urgent")
STATUSES = ("open", "processing", "resolved", "rejected")


def _is_en(request: Request) -> bool:
    return (request.headers.get("accept-language") or "").lower().startswith("en")


def _ensure_table(conn) -> None:
    """惰性建表 + 索引（sqlite / pg 双模，范式同 task_runner._ensure_queue_table）。"""
    if isinstance(conn, sqlite3.Connection):
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter TEXT NOT NULL,
                contact TEXT,
                category TEXT NOT NULL DEFAULT 'other',
                priority TEXT NOT NULL DEFAULT 'medium',
                page TEXT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                handler TEXT,
                resolution TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
    else:
        # PG：以 GENERATED ALWAYS AS IDENTITY 取代 sqlite 的 AUTOINCREMENT
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                reporter TEXT NOT NULL,
                contact TEXT,
                category TEXT NOT NULL DEFAULT 'other',
                priority TEXT NOT NULL DEFAULT 'medium',
                page TEXT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                handler TEXT,
                resolution TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
    # 幂等迁移：早期版本无 handler/resolution 列（处理人/处理备注）
    cols = table_columns(conn, TABLE)
    for col in ("handler", "resolution"):
        if col not in cols:
            conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} TEXT")
            conn.commit()
    conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_status ON {TABLE}(status)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_created ON {TABLE}(created_at)")
    conn.commit()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(r) -> dict:
    return {
        "id": r["id"],
        "reporter": r["reporter"],
        "contact": r["contact"],
        "category": r["category"],
        "priority": r["priority"],
        "page": r["page"],
        "title": r["title"],
        "description": r["description"],
        "status": r["status"],
        "handler": r["handler"],
        "resolution": r["resolution"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


class FeedbackIn(BaseModel):
    reporter: str = Field(..., min_length=1, max_length=64)
    contact: Optional[str] = Field(None, max_length=128)
    category: str = Field("other", max_length=16)
    priority: str = Field("medium", max_length=16)
    page: Optional[str] = Field(None, max_length=64)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=4000)


class FeedbackUpdate(BaseModel):
    status: Optional[str] = Field(None, max_length=16)
    handler: Optional[str] = Field(None, max_length=64)
    resolution: Optional[str] = Field(None, max_length=2000)


@router.post("")
def create_feedback(body: FeedbackIn, request: Request):
    """提交问题登记。内网开放提交；字段做白名单/长度校验。"""
    en = _is_en(request)
    if body.category not in TYPES:
        raise HTTPException(status_code=400, detail="Invalid category" if en else f"未知问题类型: {body.category}")
    if body.priority not in PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority" if en else f"未知优先级: {body.priority}")
    now = _now()
    with get_raw_connection() as conn:
        _ensure_table(conn)
        insert_sql = (
            f"INSERT INTO {TABLE} (reporter, contact, category, priority, page, title, description, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)"
        )
        params = (body.reporter.strip(), (body.contact or "").strip() or None,
                  body.category, body.priority, (body.page or "").strip() or None,
                  body.title.strip(), body.description.strip(), now, now)
        if isinstance(conn, sqlite3.Connection):
            conn.execute(insert_sql, params)
            conn.commit()
            new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            # PG 包装游标无 lastrowid，用 INSERT ... RETURNING 取回新 id
            new_id = conn.execute(insert_sql + " RETURNING id", params).fetchone()[0]
            conn.commit()
    logger.info(f"[FEEDBACK] 新登记 #{new_id}: {body.title[:50]} (by {body.reporter})")
    return {"status": "ok", "id": new_id,
            "message": "Issue submitted, thank you for your feedback" if en else "问题已提交，感谢反馈"}


@router.get("")
def list_feedback(
    request: Request,
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """列表查询：可按状态/类型/优先级筛选，keyword 模糊匹配标题/描述/登记人；倒序分页。"""
    where, params = [], []
    if status:
        where.append("status = ?")
        params.append(status)
    if category:
        where.append("category = ?")
        params.append(category)
    if priority:
        where.append("priority = ?")
        params.append(priority)
    if keyword:
        kw = f"%{keyword.strip()}%"
        where.append("(title LIKE ? OR description LIKE ? OR reporter LIKE ?)")
        params.extend([kw, kw, kw])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    with get_raw_connection() as conn:
        _ensure_table(conn)
        total = conn.execute(f"SELECT COUNT(*) FROM {TABLE} {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM {TABLE} {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    return {"total": total, "items": [_row_to_dict(r) for r in rows]}


@router.get("/stats")
def feedback_stats(request: Request):
    """状态/类型/优先级聚合计数（页面统计卡）。"""
    with get_raw_connection() as conn:
        _ensure_table(conn)
        def group(col):
            rows = conn.execute(f"SELECT {col}, COUNT(*) FROM {TABLE} GROUP BY {col}").fetchall()
            return {r[0]: r[1] for r in rows}
        return {
            "total": conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0],
            "by_status": group("status"),
            "by_category": group("category"),
            "by_priority": group("priority"),
        }


def _get_or_404(conn, fid: int, en: bool):
    row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (fid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Issue not found" if en else f"登记记录不存在: #{fid}")
    return row


@router.put("/{fid}")
def update_feedback(fid: int, body: FeedbackUpdate, request: Request):
    """更新处理状态/处理人/处理备注（至少传一个字段）。"""
    en = _is_en(request)
    if body.status is not None and body.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status" if en else f"未知状态: {body.status}")
    updates, params = [], []
    if body.status is not None:
        updates.append("status = ?")
        params.append(body.status)
    if body.handler is not None:
        updates.append("handler = ?")
        params.append(body.handler.strip() or None)
    if body.resolution is not None:
        updates.append("resolution = ?")
        params.append(body.resolution.strip() or None)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update" if en else "没有需要更新的字段")
    updates.append("updated_at = ?")
    params.append(_now())
    params.append(fid)
    with get_raw_connection() as conn:
        _ensure_table(conn)
        _get_or_404(conn, fid, en)
        conn.execute(f"UPDATE {TABLE} SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        row = conn.execute(f"SELECT * FROM {TABLE} WHERE id = ?", (fid,)).fetchone()
    logger.info(f"[FEEDBACK] #{fid} 更新: status={row['status']} handler={row['handler']}")
    return {"status": "ok", "item": _row_to_dict(row)}


@router.delete("/{fid}")
def delete_feedback(fid: int, request: Request):
    """删除登记记录。"""
    en = _is_en(request)
    with get_raw_connection() as conn:
        _ensure_table(conn)
        _get_or_404(conn, fid, en)
        conn.execute(f"DELETE FROM {TABLE} WHERE id = ?", (fid,))
        conn.commit()
    logger.info(f"[FEEDBACK] #{fid} 已删除")
    return {"status": "ok"}
