# -*- coding: utf-8 -*-
"""
feedback.py - 问题登记（用户反馈）API
=====================================
供前端「问题登记」页面使用，任何内网用户都可提交问题反馈：
- POST   /api/feedback          提交问题（multipart/form-data：反馈人/联系方式/类型/优先级/关联页面/标题/描述
                                全部必填；附件选填，≤5 个、单个 ≤10MB，拒收可执行/脚本类）
- GET    /api/feedback          列表（支持 status/type/priority/keyword 筛选 + 分页）
- GET    /api/feedback/stats    按状态/类型/优先级聚合计数（页面顶部统计卡）
- GET    /api/feedback/{id}/attachments/{stored}   下载/预览附件（图片与 PDF 内联，其余下载）
- PUT    /api/feedback/{id}     更新处理状态/处理备注（open → processing → resolved/rejected）
- DELETE /api/feedback/{id}     删除登记记录（连同附件目录）

存储：db/app.db 表 issue_reports（sqlite/pg 双模，首次访问惰性建表，
写法与 task_runner._ensure_queue_table 一致）；附件落盘 db/attachments/fb_<id>/，
元数据 JSON 存 issue_reports.attachments 列，落盘范式与 upload.py 的 db/uploads 一致。
与 settings / email_recipients 路由风格一致：内网本地访问不做额外鉴权。
"""
import json
import logging
import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.database import DB_PATH, get_raw_connection
from backend.dialect_helpers import table_columns

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

TABLE = "issue_reports"

# 枚举白名单（前后端约定一致；非法值直接 400，避免脏数据）
TYPES = ("bug", "data", "feature", "other")
PRIORITIES = ("low", "medium", "high", "urgent")
STATUSES = ("open", "processing", "resolved", "rejected")

# 附件约束（与前端 IssueFeedback.tsx 的 beforeUpload 限制保持一致）
ATTACH_DIR = DB_PATH.parent / "attachments"
# parents=True 不能省：db/ 整个目录被 .gitignore 排除，全新克隆里它不存在，
# 缺省参数会让 import backend.routers.feedback 直接抛 FileNotFoundError，
# 连带整个后端起不来（upload.py 踩过的坑）。
ATTACH_DIR.mkdir(parents=True, exist_ok=True)
MAX_ATTACHMENTS = 5
MAX_FILE_MB = 10
# 黑名单只挡可执行/脚本类扩展名——白名单容易误伤用户的真实文件
DENIED_EXTS = {
    ".exe", ".bat", ".cmd", ".com", ".scr", ".msi", ".dll",
    ".js", ".mjs", ".vbs", ".vbe", ".ps1", ".psm1", ".sh", ".jar", ".lnk", ".reg",
}
# 浏览器可直接预览的类型（Content-Disposition inline），其余强制 attachment 下载
INLINE_PREFIXES = ("image/", "application/pdf", "text/plain")

# POST 全字段必填（前端表单同步必填，这里做服务端兜底）
REQUIRED_FIELDS = ("reporter", "contact", "category", "priority", "page", "title", "description")


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
                attachments TEXT,
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
                attachments TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                handler TEXT,
                resolution TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
    # 幂等迁移：早期版本无 handler/resolution 列（处理人/处理备注）、
    # 无 attachments 列（附件元数据 JSON）
    cols = table_columns(conn, TABLE)
    for col in ("handler", "resolution", "attachments"):
        if col not in cols:
            conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} TEXT")
            conn.commit()
    conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_status ON {TABLE}(status)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_created ON {TABLE}(created_at)")
    conn.commit()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_attachments(raw) -> list:
    """issue_reports.attachments 列是 JSON 字符串，脏数据一律按空列表处理。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 - 历史脏值不该让列表接口 500
        return []


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
        "attachments": _parse_attachments(r["attachments"]),
        "status": r["status"],
        "handler": r["handler"],
        "resolution": r["resolution"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def _safe_stored_name(filename: str) -> str:
    """生成落盘文件名：剥离目录分隔符/空字符、替换非常见字符，uuid 前缀防覆盖
    （范式同 upload.py）。展示用原始文件名保存在附件元数据里，不依赖这个值。"""
    base = re.sub(r"[\/\\]", "_", filename).split("\x00")[0]
    base = re.sub(r"[^\w.\-]", "_", base) or "attachment"
    return f"{uuid.uuid4().hex[:8]}_{base}"


def _validate_attachments(files: List[UploadFile], en: bool) -> None:
    """落盘前的统一校验：数量 / 扩展名黑名单 / 声明大小（size 缺失时靠写入期限量兜底）。"""
    if len(files) > MAX_ATTACHMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Up to {MAX_ATTACHMENTS} attachments allowed" if en else f"附件最多 {MAX_ATTACHMENTS} 个",
        )
    cap = MAX_FILE_MB * 1024 * 1024
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext in DENIED_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed: {f.filename}" if en else f"不允许上传的文件类型: {f.filename}",
            )
        if (f.size or 0) > cap:
            raise HTTPException(
                status_code=400,
                detail=f"File exceeds {MAX_FILE_MB}MB limit: {f.filename}" if en else f"文件超过 {MAX_FILE_MB}MB 限制: {f.filename}",
            )


def _save_attachments(fid: int, files: List[UploadFile]) -> list:
    """把附件写入 db/attachments/fb_<id>/，返回元数据列表。

    写入按 1MB 分块限量——multipart 解析出的 size 可能被伪造，这里以实际字节数为准。
    """
    if not files:
        return []
    attach_dir = ATTACH_DIR / f"fb_{fid}"
    attach_dir.mkdir(parents=True, exist_ok=True)
    dir_real = str(attach_dir.resolve())
    cap = MAX_FILE_MB * 1024 * 1024
    saved = []
    for f in files:
        stored = _safe_stored_name(f.filename or "attachment")
        path = (attach_dir / stored).resolve()
        if not str(path).startswith(dir_real + os.sep):
            raise HTTPException(status_code=400, detail="非法文件名")
        size = 0
        with open(path, "wb") as out:
            while True:
                chunk = f.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > cap:
                    raise HTTPException(
                        status_code=400,
                        detail=f"File exceeds {MAX_FILE_MB}MB limit: {f.filename}",
                    )
                out.write(chunk)
        saved.append({
            "name": f.filename or stored,
            "stored": stored,
            "size": size,
            "content_type": f.content_type or "application/octet-stream",
        })
    return saved


class FeedbackUpdate(BaseModel):
    status: Optional[str] = Field(None, max_length=16)
    handler: Optional[str] = Field(None, max_length=64)
    resolution: Optional[str] = Field(None, max_length=2000)


@router.post("")
def create_feedback(
    request: Request,
    reporter: str = Form(...),
    contact: str = Form(...),
    category: str = Form(...),
    priority: str = Form(...),
    page: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    attachments: Optional[List[UploadFile]] = File(None),
):
    """提交问题登记（multipart/form-data）。全字段必填；附件选填。同步 def 走线程池，
    避免附件读写阻塞事件循环。"""
    en = _is_en(request)
    values = {"reporter": reporter, "contact": contact, "category": category,
              "priority": priority, "page": page, "title": title, "description": description}
    missing = [k for k in REQUIRED_FIELDS if not (values.get(k) or "").strip()]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=("Missing required fields: " + ", ".join(missing)) if en else "缺少必填字段: " + "、".join(missing),
        )
    if category not in TYPES:
        raise HTTPException(status_code=400, detail="Invalid category" if en else f"未知问题类型: {category}")
    if priority not in PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority" if en else f"未知优先级: {priority}")
    files = [f for f in (attachments or []) if f and (f.filename or "").strip()]
    _validate_attachments(files, en)
    now = _now()
    with get_raw_connection() as conn:
        _ensure_table(conn)
        insert_sql = (
            f"INSERT INTO {TABLE} (reporter, contact, category, priority, page, title, description, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)"
        )
        params = (reporter.strip(), contact.strip(), category, priority, page.strip(),
                  title.strip(), description.strip(), now, now)
        if isinstance(conn, sqlite3.Connection):
            conn.execute(insert_sql, params)
            conn.commit()
            new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            # PG 包装游标无 lastrowid，用 INSERT ... RETURNING 取回新 id
            new_id = conn.execute(insert_sql + " RETURNING id", params).fetchone()[0]
            conn.commit()
        try:
            saved = _save_attachments(new_id, files)
            if saved:
                conn.execute(
                    f"UPDATE {TABLE} SET attachments = ? WHERE id = ?",
                    (json.dumps(saved, ensure_ascii=False), new_id),
                )
        except Exception:
            # 附件落盘失败：回滚整条登记并清掉半截附件目录，不留无附件元数据的残缺记录
            shutil.rmtree(ATTACH_DIR / f"fb_{new_id}", ignore_errors=True)
            raise
        conn.commit()
    logger.info(f"[FEEDBACK] 新登记 #{new_id}: {title.strip()[:50]} (by {reporter.strip()}, 附件 {len(files)} 个)")
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


@router.get("/{fid}/attachments/{stored}")
def download_attachment(fid: int, stored: str, request: Request):
    """下载/预览附件。stored 必须与登记元数据精确匹配（uuid 前缀生成名），天然防路径穿越。"""
    en = _is_en(request)
    if "/" in stored or "\\" in stored or ".." in stored:
        raise HTTPException(status_code=400, detail="非法文件名" if en else "非法文件名")
    with get_raw_connection() as conn:
        _ensure_table(conn)
        row = _get_or_404(conn, fid, en)
    meta = next((a for a in _parse_attachments(row["attachments"]) if a.get("stored") == stored), None)
    if meta is None:
        raise HTTPException(status_code=404, detail="Attachment not found" if en else "附件不存在")
    attach_dir = (ATTACH_DIR / f"fb_{fid}").resolve()
    path = (attach_dir / stored).resolve()
    if not str(path).startswith(str(attach_dir) + os.sep) or not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment file missing" if en else "附件文件缺失")
    media_type = meta.get("content_type") or "application/octet-stream"
    inline = media_type.startswith(INLINE_PREFIXES)
    return FileResponse(path, filename=meta.get("name") or stored, media_type=media_type,
                        content_disposition_type="inline" if inline else "attachment")


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
    """删除登记记录（连同附件目录）。"""
    en = _is_en(request)
    with get_raw_connection() as conn:
        _ensure_table(conn)
        _get_or_404(conn, fid, en)
        conn.execute(f"DELETE FROM {TABLE} WHERE id = ?", (fid,))
        conn.commit()
    shutil.rmtree(ATTACH_DIR / f"fb_{fid}", ignore_errors=True)
    logger.info(f"[FEEDBACK] #{fid} 已删除")
    return {"status": "ok"}
