# -*- coding: utf-8 -*-
"""AP（Action Plan）API —— 下发 / 确认 / 更新进度 / 提交审核 / 审核关闭。

## 端点（**顺序敏感**）

```
GET  /api/ap/meta                      当前用户身份、可管理标记、组织架构、枚举
GET  /api/ap/org                       Escalation Matrix（按 level 分组）
GET  /api/ap/stats                     统计卡数字
GET  /api/ap                          列表（scope=mine|review|all + 筛选 + 分页）
POST /api/ap                          创建（可 dispatch=true 直接下发）
GET  /api/ap/{id}                     详情（含进度记录、审核记录、时间线）
PUT  /api/ap/{id}                     编辑（DRAFT / ASSIGNED）
POST /api/ap/{id}/dispatch            下发
POST /api/ap/{id}/accept              确认接收
POST /api/ap/{id}/start               开始执行
POST /api/ap/{id}/progress            更新进度
POST /api/ap/{id}/submit              提交审核
POST /api/ap/{id}/approve             审核通过
POST /api/ap/{id}/reject              审核退回（必须填原因）
POST /api/ap/{id}/cancel              取消
POST /api/ap/{id}/attachments         上传凭证（multipart，最多 5 个 / 单个 10MB）
GET  /api/ap/{id}/attachments/{name}  下载/预览（**带权限校验**）
```

> ⚠️ `/meta`、`/org`、`/stats` 必须注册在 `/{ap_id}` **之前**。FastAPI 按注册顺序
> 匹配，`/{ap_id}` 在前会把 `meta` 当成 id 解析，直接 422 —— 方案 7 的
> `/api/ap/analytics` 就有这个问题（`AP_Plan_Review.md` 第 4.2 条）。

## 状态机

转换白名单在 `store.TRANSITIONS`；**每一次转换都由后端校验**，不接受客户端
直接指定目标状态。并发用乐观锁：`UPDATE ... WHERE id=? AND status=?`，
`rowcount=0` 即视为"已被别人改过"，返回 409 而不是覆盖。

## 权限

`permissions.can_*` 是唯一判定处。前端隐藏按钮只是体验，不算鉴权。
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.database import DB_PATH, get_raw_connection
from backend.services import portal_auth
from backend.services.ap_manager import notify, org, permissions, store

logger = logging.getLogger("ap.router")

router = APIRouter(prefix="/api/ap", tags=["ap"])

# 凭证落盘目录：与 issue_reports 的 db/attachments 同一处，按 ap_<id> 分子目录
ATTACH_DIR = DB_PATH.parent / "attachments"
ATTACH_DIR.mkdir(parents=True, exist_ok=True)
MAX_ATTACHMENTS = 5
MAX_FILE_MB = 10
DENIED_EXTS = {
    ".exe", ".bat", ".cmd", ".com", ".scr", ".msi", ".dll",
    ".js", ".mjs", ".vbs", ".vbe", ".ps1", ".psm1", ".sh", ".jar", ".lnk", ".reg",
}
INLINE_PREFIXES = ("image/", "application/pdf", "text/plain")


# ========== 基础设施 ==========

class _Ctx:
    """一次请求的上下文：连接 + 身份 + 权限角色。"""

    def __init__(self, request: Request):
        self.conn = get_raw_connection()
        store.ensure_tables(self.conn)
        org.ensure_seed(self.conn)
        user = portal_auth.current_user(request) or {}
        self.username = str(user.get("username") or "").strip()
        self.portal_role = str(user.get("role") or "viewer")
        if not self.username:
            raise HTTPException(status_code=401, detail="未登录：请通过统一门户登录")
        self.profile = org.resolve_profile(self.conn, self.username, self.portal_role)
        self.eff_role = permissions.effective_role(self.profile, self.portal_role)
        self.can_manage = permissions.can_manage(self.eff_role)
        # 同一个人可能被写成 账号 / 组织姓名 / 显示名（见 permissions.keys 的说明）
        self.alias_set = permissions.keys(
            self.username,
            [self.profile.get("org_name"), self.profile.get("display_name")],
        )

    def close(self):
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass


def _ctx(request: Request):
    c = _Ctx(request)
    try:
        yield c
    finally:
        c.close()


def _en(request: Request) -> bool:
    return (request.headers.get("accept-language") or "").lower().startswith("en")


def _err(en: bool, zh: str, en_msg: str, code: int = 400):
    raise HTTPException(status_code=code, detail=en_msg if en else zh)


def _now():
    return store.now()


def _load(ctx: _Ctx, ap_id: int) -> dict:
    row = ctx.conn.execute(
        f"SELECT * FROM {store.T_TASKS} WHERE id = ?", (int(ap_id),)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="AP 不存在")
    task = store.row_to_dict(row)
    task["attachments"] = store.parse_json(task.get("attachments"), [])
    store.normalize_ts(task)
    task["is_overdue"] = _is_overdue(task)
    return task


def _is_overdue(task: dict) -> bool:
    """逾期是**计算属性**，不是状态（方案第 3 节的判断正确）。

    查询时算而不是定时任务维护标记：少一个会静默失效的定时任务。
    """
    if task.get("status") not in store.OPEN_STATUSES:
        return False
    due = task.get("due_at")
    if not due:
        return False
    return str(store.fmt_ts(due)) < _now()


def _require_view(ctx: _Ctx, task: dict):
    if not permissions.can_view(task, ctx.username, ctx.eff_role, ctx.alias_set):
        # 越权时不泄露任务内容（方案 AT-12）
        raise HTTPException(status_code=403, detail="无权访问该 AP")


def _require_act(ctx: _Ctx, task: dict, action: str, en: bool):
    if not permissions.can_act(task, ctx.username, ctx.eff_role, action, ctx.alias_set):
        _err(en, "无权执行该操作", "You are not allowed to perform this action", 403)


def _check_transition(ctx: _Ctx, task: dict, action: str, en: bool) -> str | None:
    """校验状态合法性并返回目标状态（progress 动作返回 None）。"""
    allowed, target = store.TRANSITIONS[action]
    if task["status"] not in allowed:
        _err(en,
             f"当前状态 {task['status']} 不允许该操作",
             f"Action not allowed in status {task['status']}", 409)
    return target


def _apply(ctx: _Ctx, task: dict, action: str, sets: dict | None = None,
           en: bool = False, note: str | None = None) -> dict:
    """执行一次状态转换（乐观锁）+ 写历史。返回更新后的任务。

    `rowcount=0` 说明并发下已被别人改过 —— 返回 409 让前端刷新，
    **绝不覆盖**（方案 12.11 并发控制）。
    """
    target = _check_transition(ctx, task, action, en)
    now = _now()
    payload = dict(sets or {})
    payload["updated_at"] = now
    if target:
        payload["status"] = target
    # 时间戳列
    stamp = {"dispatch": "dispatched_at", "accept": "accepted_at", "submit": "submitted_at",
             "approve": "completed_at", "cancel": "cancelled_at"}.get(action)
    if stamp:
        payload[stamp] = now

    cols = ", ".join(f"{k} = ?" for k in payload)
    params = list(payload.values()) + [task["id"], task["status"]]
    cur = ctx.conn.execute(
        f"UPDATE {store.T_TASKS} SET {cols} WHERE id = ? AND status = ?", tuple(params)
    )
    if getattr(cur, "rowcount", 1) == 0:
        ctx.conn.rollback()
        _err(en, "该 AP 已被其他人更新，请刷新后重试",
             "This AP was updated by someone else, please refresh", 409)

    store.history(ctx.conn, task["id"], ctx.username, action,
                  task["status"], target or task["status"],
                  {"note": note} if note else None)
    ctx.conn.commit()
    return _load(ctx, task["id"])


# ========== 请求体 ==========

class CreateBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    owner_username: str = Field(..., min_length=1)
    description: Optional[str] = None
    category: Optional[str] = "OTHER"
    priority: Optional[str] = "MEDIUM"
    reviewer_username: Optional[str] = None
    target_position: Optional[str] = None
    due_at: Optional[str] = None
    notify_groups: Optional[str] = None
    related_ticket_id: Optional[str] = None
    site_id: Optional[str] = None
    region: Optional[str] = None
    dispatch: bool = False


class EditBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    owner_username: Optional[str] = None
    reviewer_username: Optional[str] = None
    target_position: Optional[str] = None
    due_at: Optional[str] = None
    notify_groups: Optional[str] = None
    related_ticket_id: Optional[str] = None
    site_id: Optional[str] = None
    region: Optional[str] = None


class ProgressBody(BaseModel):
    progress: Optional[int] = None
    note: Optional[str] = None


class SubmitBody(BaseModel):
    progress: Optional[int] = 100
    completion_note: Optional[str] = None


class ReviewBody(BaseModel):
    comments: Optional[str] = None


# ========== 元信息（必须在 /{ap_id} 之前） ==========

@router.get("/meta")
def ap_meta(ctx: _Ctx = Depends(_ctx)):
    """页面初始化：当前身份 + 可管理标记 + 组织架构 + 枚举 + 默认群组。"""
    return {
        "user": {
            "username": ctx.username,
            "display_name": ctx.profile.get("display_name") or ctx.username,
            "email": ctx.profile.get("email") or "",
            "position": ctx.profile.get("org_position") or "",
            "level": ctx.profile.get("org_level") or "",
            "portal_role": ctx.portal_role,
            "ap_role": ctx.eff_role,
            "can_manage": ctx.can_manage,
        },
        "org": org.list_org(ctx.conn),
        "levels": [{"id": k, "label": v} for k, v in org.LEVELS],
        "statuses": list(store.STATUSES),
        "priorities": list(store.PRIORITIES),
        "categories": list(store.CATEGORIES),
        "default_groups": list(notify.DEFAULT_GROUPS),
        "today": _now(),
    }


@router.get("/org")
def ap_org(ctx: _Ctx = Depends(_ctx)):
    return {"people": org.list_org(ctx.conn),
            "levels": [{"id": k, "label": v} for k, v in org.LEVELS]}


@router.get("/stats")
def ap_stats(ctx: _Ctx = Depends(_ctx)):
    """顶部统计卡。口径与列表的 WHERE 保持一致，避免"卡片数字 ≠ 点进去的行数"。"""
    scope_clause, params = _scope_where(ctx, "mine")
    rows = ctx.conn.execute(
        f"SELECT status, COUNT(*) FROM {store.T_TASKS} WHERE {scope_clause} GROUP BY status",
        tuple(params),
    ).fetchall()
    by_status = {r[0]: r[1] for r in rows}
    total = sum(by_status.values())
    open_cnt = sum(v for k, v in by_status.items() if k in store.OPEN_STATUSES)
    # 逾期：与 _is_overdue 同一判定
    overdue = ctx.conn.execute(
        f"SELECT COUNT(*) FROM {store.T_TASKS} WHERE {scope_clause} "
        "AND due_at IS NOT NULL AND due_at < ? AND status IN ("
        + ",".join("?" * len(store.OPEN_STATUSES)) + ")",
        tuple(params) + (_now(),) + tuple(store.OPEN_STATUSES),
    ).fetchone()[0]
    return {
        "total": total,
        "open": open_cnt,
        "overdue": overdue,
        "pending_review": by_status.get(store.PENDING_REVIEW, 0),
        "in_progress": by_status.get(store.IN_PROGRESS, 0),
        "completed": by_status.get(store.COMPLETED, 0),
        "by_status": by_status,
    }


def _scope_where(ctx: _Ctx, scope: str) -> tuple[str, list]:
    """列表/统计共用的 WHERE —— 两处必须同源，否则数字对不上。

    比较用 `alias_set`（账号 + 组织姓名 + 显示名）：下发人从 Escalation Matrix
    挑的是英文姓名，执行人用门户账号登录，两者必须互相认得出。
    """
    keys = sorted(ctx.alias_set) or [ctx.username.lower()]

    def _any(cols: tuple[str, ...]) -> tuple[str, list]:
        clause = " OR ".join(f"lower({c}) = ?" for c in cols for _ in keys)
        params = [k for _c in cols for k in keys]
        return f"({clause})", params

    if scope == "all":
        if not ctx.can_manage:
            # 非管理者请求 all：退化为"与我相关"，不报错（前端也可能传 all）
            return _any(("owner_username", "reviewer_username", "created_by"))
        return ("1=1", [])
    if scope == "review":
        return _any(("reviewer_username",))
    # mine：我负责的 + 我创建的（创建人也要能看到自己下发的进度）
    return _any(("owner_username", "created_by"))


# ========== 列表 / 创建 ==========

@router.get("")
def ap_list(
    request: Request,
    scope: str = Query("mine", pattern="^(mine|review|all)$"),
    status: Optional[str] = None,
    priority: Optional[str] = None,
    keyword: Optional[str] = None,
    overdue: Optional[bool] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    ctx: _Ctx = Depends(_ctx),
):
    where, params = _scope_where(ctx, scope)
    if status and status in store.STATUSES:
        where += " AND status = ?"
        params.append(status)
    if priority and priority in store.PRIORITIES:
        where += " AND priority = ?"
        params.append(priority)
    if keyword:
        where += " AND (title LIKE ? OR ap_no LIKE ? OR description LIKE ?)"
        kw = f"%{keyword.strip()}%"
        params.extend([kw, kw, kw])
    if overdue is True:
        where += (" AND due_at IS NOT NULL AND due_at < ? AND status IN ("
                  + ",".join("?" * len(store.OPEN_STATUSES)) + ")")
        params.append(_now())
        params.extend(store.OPEN_STATUSES)

    total = ctx.conn.execute(
        f"SELECT COUNT(*) FROM {store.T_TASKS} WHERE {where}", tuple(params)
    ).fetchone()[0]
    rows = ctx.conn.execute(
        f"SELECT * FROM {store.T_TASKS} WHERE {where} ORDER BY "
        "CASE status WHEN 'PENDING_REVIEW' THEN 0 WHEN 'IN_PROGRESS' THEN 1 "
        "WHEN 'ACKNOWLEDGED' THEN 2 WHEN 'ASSIGNED' THEN 3 WHEN 'REJECTED' THEN 4 "
        # ⚠️ 兜底值必须是一个**合法时间**：PG 的 due_at 是 TIMESTAMP，
        # COALESCE(due_at, '9999') 会直接抛 InvalidDatetimeFormat（实测踩过）。
        "ELSE 5 END, COALESCE(due_at, '9999-12-31 00:00:00') ASC, id DESC LIMIT ? OFFSET ?",
        tuple(params) + (page_size, (page - 1) * page_size),
    ).fetchall()
    items = []
    for r in rows:
        t = store.row_to_dict(r)
        t.pop("attachments", None)
        store.normalize_ts(t)
        t["is_overdue"] = _is_overdue(t)
        items.append(t)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("")
def ap_create(body: CreateBody, request: Request, ctx: _Ctx = Depends(_ctx)):
    en = _en(request)
    if not ctx.can_manage:
        _err(en, "只有管理员或 AP Manager 可以创建 AP",
             "Only admin or AP Manager can create an AP", 403)
    priority = (body.priority or "MEDIUM").upper()
    if priority not in store.PRIORITIES:
        _err(en, "优先级非法", "Invalid priority")
    category = (body.category or "OTHER").upper()
    if category not in store.CATEGORIES:
        category = "OTHER"
    owner = body.owner_username.strip()
    reviewer = (body.reviewer_username or "").strip()
    if reviewer and reviewer.lower() == owner.lower():
        _err(en, "审核人不能与执行人相同", "Reviewer cannot be the same as the owner")
    due = store.to_ts(body.due_at)
    if body.due_at and not due:
        _err(en, "截止时间格式无法识别", "Unrecognized due time format")
    groups = ",".join(notify.parse_groups(body.notify_groups))

    now = _now()
    status = store.ASSIGNED if body.dispatch else store.DRAFT
    last_err = None
    for _ in range(5):
        ap_no = store.next_ap_no(ctx.conn)
        try:
            cur = ctx.conn.execute(
                f"INSERT INTO {store.T_TASKS} (ap_no, title, category, description, priority, "
                "status, target_position, owner_username, reviewer_username, progress, due_at, "
                "notify_groups, related_ticket_id, site_id, region, created_by, created_at, "
                "updated_at, dispatched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ap_no, body.title.strip(), category, (body.description or "").strip(), priority,
                 status, (body.target_position or "").strip(), owner, reviewer, due, groups,
                 (body.related_ticket_id or "").strip(), (body.site_id or "").strip(),
                 (body.region or "").strip(), ctx.username, now, now,
                 now if body.dispatch else None),
            )
            row = ctx.conn.execute(
                f"SELECT id FROM {store.T_TASKS} WHERE ap_no = ?", (ap_no,)
            ).fetchone()
            ap_id = row[0]
            break
        except Exception as e:  # noqa: BLE001  唯一索引冲突 → 换号重试
            ctx.conn.rollback()
            last_err = e
            if "unique" not in str(e).lower() and "duplicate" not in str(e).lower():
                raise
    else:
        logger.error("[ap] 生成 AP 编号连续冲突：%s", last_err)
        _err(en, "AP 编号生成失败，请重试", "Failed to allocate AP number", 500)

    store.history(ctx.conn, ap_id, ctx.username, "create",
                  None, status, {"title": body.title.strip(), "owner": owner})
    ctx.conn.commit()
    task = _load(ctx, ap_id)

    if body.dispatch:
        _notify_dispatch(ctx, task)
    return task


def _notify_dispatch(ctx: _Ctx, task: dict) -> None:
    """下发通知：负责人（邮件+群）+ 审核人（邮件）。失败不影响业务。"""
    groups = notify.parse_groups(task.get("notify_groups"))
    notify.send_whatsapp(groups, task["ap_no"], notify.wa_text("dispatch", task))
    to = [org.email_of(ctx.conn, task.get("owner_username")),
          org.email_of(ctx.conn, task.get("reviewer_username"))]
    notify.send_email(
        to,
        f"[AP] {task['ap_no']} {task['title']}",
        f"New Action Plan assigned · {task['ap_no']}",
        notify.mail_lines(task),
    )


# ========== 详情 / 编辑 ==========

@router.get("/{ap_id}")
def ap_detail(ap_id: int, ctx: _Ctx = Depends(_ctx)):
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    updates = [store.normalize_ts(store.row_to_dict(r)) for r in ctx.conn.execute(
        f"SELECT * FROM {store.T_UPDATES} WHERE ap_id = ? ORDER BY id", (ap_id,)
    ).fetchall()]
    reviews = [store.normalize_ts(store.row_to_dict(r)) for r in ctx.conn.execute(
        f"SELECT * FROM {store.T_REVIEWS} WHERE ap_id = ? ORDER BY id", (ap_id,)
    ).fetchall()]
    timeline = []
    for r in ctx.conn.execute(
        f"SELECT * FROM {store.T_HISTORY} WHERE ap_id = ? ORDER BY id", (ap_id,)
    ).fetchall():
        h = store.normalize_ts(store.row_to_dict(r))
        h["details"] = store.parse_json(h.get("details"), None)
        timeline.append(h)
    task["updates"] = updates
    task["reviews"] = reviews
    task["timeline"] = timeline
    task["allowed"] = _allowed_actions(ctx, task)
    return task


def _allowed_actions(ctx: _Ctx, task: dict) -> list[str]:
    """给前端算"该显示哪些按钮"。**仅用于展示**，后端仍逐动作校验。"""
    out = []
    for action in ("dispatch", "accept", "start", "progress", "submit",
                   "approve", "reject", "cancel", "attach", "edit"):
        if not permissions.can_act(task, ctx.username, ctx.eff_role, action, ctx.alias_set):
            continue
        # progress / attach / edit 不受 TRANSITIONS 约束（不改状态 / 任何状态都能传凭证）
        if action in ("progress", "attach", "edit"):
            if action != "edit" or task["status"] in (store.DRAFT, store.ASSIGNED):
                out.append(action)
            continue
        allowed, _ = store.TRANSITIONS[action]
        if task["status"] in allowed:
            out.append(action)
    return out


@router.put("/{ap_id}")
def ap_edit(ap_id: int, body: EditBody, request: Request, ctx: _Ctx = Depends(_ctx)):
    en = _en(request)
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    _require_act(ctx, task, "edit", en)
    if task["status"] not in (store.DRAFT, store.ASSIGNED):
        _err(en, "只有草稿或已下发（未确认）的 AP 可以编辑",
             "Only DRAFT or unacknowledged ASSIGNED APs can be edited", 409)

    sets, details = {}, {}
    data = body.model_dump(exclude_unset=True)
    if "priority" in data and data["priority"]:
        p = str(data["priority"]).upper()
        if p not in store.PRIORITIES:
            _err(en, "优先级非法", "Invalid priority")
        sets["priority"] = p
    if "category" in data and data["category"]:
        c = str(data["category"]).upper()
        sets["category"] = c if c in store.CATEGORIES else "OTHER"
    for key in ("title", "description", "target_position", "related_ticket_id", "site_id", "region"):
        if key in data and data[key] is not None:
            sets[key] = str(data[key]).strip()
    if "owner_username" in data and data["owner_username"]:
        sets["owner_username"] = str(data["owner_username"]).strip()
    if "reviewer_username" in data and data["reviewer_username"] is not None:
        sets["reviewer_username"] = str(data["reviewer_username"]).strip()
    if "due_at" in data:
        sets["due_at"] = store.to_ts(data["due_at"])
    if "notify_groups" in data:
        sets["notify_groups"] = ",".join(notify.parse_groups(data["notify_groups"]))
    if not sets:
        return task
    details = {k: str(v)[:200] for k, v in sets.items()}
    sets["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in sets)
    ctx.conn.execute(f"UPDATE {store.T_TASKS} SET {cols} WHERE id = ?",
                     tuple(sets.values()) + (ap_id,))
    store.history(ctx.conn, ap_id, ctx.username, "edit", task["status"], task["status"], details)
    ctx.conn.commit()
    return _load(ctx, ap_id)


# ========== 状态流转 ==========

@router.post("/{ap_id}/dispatch")
def ap_dispatch(ap_id: int, request: Request, ctx: _Ctx = Depends(_ctx)):
    en = _en(request)
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    _require_act(ctx, task, "dispatch", en)
    if not task.get("owner_username"):
        _err(en, "未指定执行人，无法下发", "No owner assigned, cannot dispatch")
    task = _apply(ctx, task, "dispatch", en=en)
    _notify_dispatch(ctx, task)
    return task


@router.post("/{ap_id}/accept")
def ap_accept(ap_id: int, request: Request, ctx: _Ctx = Depends(_ctx)):
    en = _en(request)
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    _require_act(ctx, task, "accept", en)
    return _apply(ctx, task, "accept", en=en)


@router.post("/{ap_id}/start")
def ap_start(ap_id: int, request: Request, ctx: _Ctx = Depends(_ctx)):
    en = _en(request)
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    _require_act(ctx, task, "start", en)
    return _apply(ctx, task, "start", en=en)


@router.post("/{ap_id}/progress")
def ap_progress(ap_id: int, body: ProgressBody, request: Request, ctx: _Ctx = Depends(_ctx)):
    en = _en(request)
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    _require_act(ctx, task, "progress", en)
    _check_transition(ctx, task, "progress", en)

    progress = task.get("progress") or 0
    if body.progress is not None:
        progress = max(0, min(100, int(body.progress)))
    now = _now()
    ctx.conn.execute(
        f"INSERT INTO {store.T_UPDATES} (ap_id, username, progress, note, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ap_id, ctx.username, progress, (body.note or "").strip(), now),
    )
    sets = {"progress": progress, "updated_at": now}
    # 退回后第一次更新进度 = 重新开始整改（方案 3.1：Rejected → In Progress）
    if task["status"] == store.REJECTED:
        sets["status"] = store.IN_PROGRESS
    ctx.conn.execute(
        f"UPDATE {store.T_TASKS} SET progress = ?, status = ?, updated_at = ? WHERE id = ?",
        (sets["progress"], sets.get("status", task["status"]), now, ap_id),
    )
    store.history(ctx.conn, ap_id, ctx.username, "progress",
                  task["status"], sets.get("status", task["status"]),
                  {"progress": progress, "note": (body.note or "")[:500]})
    ctx.conn.commit()
    return _load(ctx, ap_id)


@router.post("/{ap_id}/submit")
def ap_submit(ap_id: int, body: SubmitBody, request: Request, ctx: _Ctx = Depends(_ctx)):
    en = _en(request)
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    _require_act(ctx, task, "submit", en)
    _check_transition(ctx, task, "submit", en)
    note = (body.completion_note or "").strip()
    if not note:
        _err(en, "请填写完成说明后再提交", "Please fill in the completion note before submitting")
    progress = 100 if body.progress is None else max(0, min(100, int(body.progress)))
    task = _apply(ctx, task, "submit",
                  sets={"progress": progress, "completion_note": note}, en=en, note=note)
    _notify_submit(ctx, task)
    return task


def _notify_submit(ctx: _Ctx, task: dict) -> None:
    groups = notify.parse_groups(task.get("notify_groups"))
    notify.send_whatsapp(groups, task["ap_no"], notify.wa_text("submit", task))
    to = [org.email_of(ctx.conn, task.get("reviewer_username"))]
    notify.send_email(
        to,
        f"[AP] {task['ap_no']} submitted for review",
        f"Action Plan submitted for review · {task['ap_no']}",
        notify.mail_lines(task),
    )


@router.post("/{ap_id}/approve")
def ap_approve(ap_id: int, body: ReviewBody, request: Request, ctx: _Ctx = Depends(_ctx)):
    en = _en(request)
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    _require_act(ctx, task, "approve", en)
    _check_transition(ctx, task, "approve", en)
    comments = (body.comments or "").strip()
    task = _apply(ctx, task, "approve", sets={"progress": 100}, en=en, note=comments)
    ctx.conn.execute(
        f"INSERT INTO {store.T_REVIEWS} (ap_id, reviewer_username, decision, comments, snapshot, created_at) "
        "VALUES (?, ?, 'APPROVED', ?, ?, ?)",
        (ap_id, ctx.username, comments,
         json.dumps({"completion_note": task.get("completion_note"),
                     "attachments": task.get("attachments")}, ensure_ascii=False), _now()),
    )
    ctx.conn.commit()
    _notify_review(ctx, task, "approve")
    return task


@router.post("/{ap_id}/reject")
def ap_reject(ap_id: int, body: ReviewBody, request: Request, ctx: _Ctx = Depends(_ctx)):
    en = _en(request)
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    _require_act(ctx, task, "reject", en)
    _check_transition(ctx, task, "reject", en)
    comments = (body.comments or "").strip()
    if not comments:
        # 方案 AT-09：退回必须填原因
        _err(en, "审核退回必须填写原因", "A reason is required when returning an AP")
    task = _apply(ctx, task, "reject", sets={"reject_reason": comments}, en=en, note=comments)
    ctx.conn.execute(
        f"INSERT INTO {store.T_REVIEWS} (ap_id, reviewer_username, decision, comments, snapshot, created_at) "
        "VALUES (?, ?, 'REJECTED', ?, ?, ?)",
        (ap_id, ctx.username, comments,
         json.dumps({"completion_note": task.get("completion_note")}, ensure_ascii=False), _now()),
    )
    ctx.conn.commit()
    _notify_review(ctx, task, "reject")
    return task


def _notify_review(ctx: _Ctx, task: dict, event: str) -> None:
    groups = notify.parse_groups(task.get("notify_groups"))
    notify.send_whatsapp(groups, task["ap_no"], notify.wa_text(event, task))
    to = [org.email_of(ctx.conn, task.get("owner_username")),
          org.email_of(ctx.conn, task.get("reviewer_username"))]
    label = "approved and closed" if event == "approve" else "returned for rework"
    notify.send_email(
        to,
        f"[AP] {task['ap_no']} {label}",
        f"Action Plan {label} · {task['ap_no']}",
        notify.mail_lines(task),
    )


@router.post("/{ap_id}/cancel")
def ap_cancel(ap_id: int, body: ReviewBody, request: Request, ctx: _Ctx = Depends(_ctx)):
    en = _en(request)
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    _require_act(ctx, task, "cancel", en)
    return _apply(ctx, task, "cancel", en=en, note=(body.comments or "").strip())


# ========== 凭证附件 ==========

def _safe_name(filename: str) -> str:
    base = re.sub(r"[\/\\]", "_", filename or "").split("\x00")[0]
    return re.sub(r"[^\w.\-]", "_", base) or "attachment"


@router.post("/{ap_id}/attachments")
async def ap_upload(ap_id: int, request: Request,
                    files: list[UploadFile] = File(...),
                    ctx: _Ctx = Depends(_ctx)):
    en = _en(request)
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    _require_act(ctx, task, "attach", en)
    existing = task.get("attachments") or []
    if len(existing) + len(files) > MAX_ATTACHMENTS:
        _err(en, f"附件最多 {MAX_ATTACHMENTS} 个", f"Up to {MAX_ATTACHMENTS} attachments allowed")

    ap_dir = ATTACH_DIR / f"ap_{ap_id}"
    ap_dir.mkdir(parents=True, exist_ok=True)
    dir_real = str(ap_dir.resolve())
    added = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext in DENIED_EXTS:
            _err(en, f"不允许上传的文件类型: {f.filename}", f"File type not allowed: {f.filename}")
        raw = await f.read()
        if len(raw) > MAX_FILE_MB * 1024 * 1024:
            _err(en, f"文件超过 {MAX_FILE_MB}MB: {f.filename}",
                 f"File exceeds {MAX_FILE_MB}MB: {f.filename}")
        stored = f"{uuid.uuid4().hex[:12]}_{_safe_name(f.filename)}"
        target = (ap_dir / stored).resolve()
        # 防路径穿越：落盘路径必须仍在 ap_<id> 目录内
        if not str(target).startswith(dir_real):
            _err(en, "文件名非法", "Illegal file name")
        target.write_bytes(raw)
        added.append({"name": f.filename or stored, "stored": stored,
                      "size": len(raw), "content_type": f.content_type or ""})

    merged = existing + added
    ctx.conn.execute(
        f"UPDATE {store.T_TASKS} SET attachments = ?, updated_at = ? WHERE id = ?",
        (json.dumps(merged, ensure_ascii=False), _now(), ap_id),
    )
    store.history(ctx.conn, ap_id, ctx.username, "attach",
                  task["status"], task["status"],
                  {"files": [a["name"] for a in added]})
    ctx.conn.commit()
    return {"attachments": merged}


@router.get("/{ap_id}/attachments/{stored}")
def ap_download(ap_id: int, stored: str, ctx: _Ctx = Depends(_ctx)):
    """下载/预览凭证。**必须校验权限** —— 不能只靠"URL 猜不到"。"""
    task = _load(ctx, ap_id)
    _require_view(ctx, task)
    meta = next((a for a in (task.get("attachments") or []) if a.get("stored") == stored), None)
    if not meta:
        raise HTTPException(status_code=404, detail="附件不存在")
    path = (ATTACH_DIR / f"ap_{ap_id}" / stored).resolve()
    if not str(path).startswith(str((ATTACH_DIR / f"ap_{ap_id}").resolve())) or not path.is_file():
        raise HTTPException(status_code=404, detail="附件不存在")
    ctype = meta.get("content_type") or ""
    inline = any(str(ctype).startswith(p) for p in INLINE_PREFIXES)
    return FileResponse(
        str(path),
        media_type=ctype or "application/octet-stream",
        filename=meta.get("name") or stored,
        content_disposition_type="inline" if inline else "attachment",
    )
