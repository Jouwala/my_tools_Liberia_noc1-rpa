"""WhatsApp 出图 / 扩展作业接口 —— 供「WhatsApp 定时发图」Chrome 扩展使用。

与 backend/services/whatsapp_service.py（/myapp/?page=sync 的 WhatsApp Message Send 任务）
共用同一份图片目录与群组/备注配置，但发送由 Chrome 扩展在已登录的 WhatsApp Web 标签页里完成。
业务逻辑（扫描图片 / 备注规则 / 作业状态机）都在
backend/services/whatsapp_ext_service.py；本文件只做 HTTP 薄封装。

端点（均走 require_protected；扩展与后端同机，回环地址自动放行，无需 token）：
- GET  /api/whatsapp/outbox            → { groups, items, generated_at }（图片清单）
- GET  /api/whatsapp/outbox/image      → FileResponse（带路径穿越防护）
- GET  /api/whatsapp/ext/job           → 认领一个待发作业（发图或 TT 告警文本），无则 {pending:false}
- POST /api/whatsapp/ext/job/result    → 扩展回报发送结果

> **`/api/whatsapp/ext/job` 是「统一认领口」**：系统里有两个作业源（定时发图、
> TT 告警文本），但扩展只轮询这一个端点。合并逻辑在
> `backend/services/whatsapp_job_claim.py`，返回体带 `kind`（`image` / `text`）
> 供扩展分发到两条发送路径。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.security import require_protected
from backend.services import whatsapp_ext_service as ext
from backend.services import whatsapp_job_claim as claim

logger = logging.getLogger("whatsapp_outbox")

router = APIRouter(tags=["whatsapp_outbox"])


# ==========================================================
# 出图
# ==========================================================
@router.get("/api/whatsapp/outbox", dependencies=[Depends(require_protected)])
def get_outbox():
    """返回待发送的群组与图片清单（每次重新扫描，保证最新）。"""
    return ext.build_outbox_payload()


@router.get("/api/whatsapp/outbox/image", dependencies=[Depends(require_protected)])
def get_outbox_image(name: str = Query(..., description="图片文件名（仅 basename）")):
    """按文件名返回图片字节。仅允许命中图片目录内的真实图片文件（防路径穿越）。"""
    target = ext.resolve_image_path(name)
    if target is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(
        path=str(target),
        media_type=ext._mime_for(target),
        filename=target.name,
    )


# ==========================================================
# 扩展作业（拉取 / 工人模型）
# ==========================================================
class JobResultBody(BaseModel):
    job_id: str
    ok: bool = False
    # 发图回 groups_sent；TT 告警文本回 sent（tt_no 列表）。两者都给默认值，
    # 故同一个 schema 能承接两种回报 —— 由 kind 决定后端取哪个字段。
    kind: str = "image"
    groups_sent: list[str] = []
    sent: list[str] = []
    errors: list[str] = []
    elapsed_seconds: Optional[float] = None


@router.get("/api/whatsapp/ext/job", dependencies=[Depends(require_protected)])
def poll_job():
    """扩展轮询：认领一个待发作业；无待发作业则返回 {pending:false}。

    作业可能来自两个源（发图 / TT 告警文本），返回体统一带 `kind` 供扩展分发。
    """
    claimed = claim.claim_next_job()
    if claimed is None:
        return {"pending": False}
    return claimed


@router.post("/api/whatsapp/ext/job/result", dependencies=[Depends(require_protected)])
def post_job_result(body: JobResultBody):
    """扩展回报发送结果，按 `kind` 转交给对应的作业源。"""
    accepted = claim.report_result(
        body.kind,
        body.job_id,
        {
            "ok": body.ok,
            "groups_sent": body.groups_sent,
            "sent": body.sent,
            "errors": body.errors,
            "elapsed_seconds": body.elapsed_seconds,
        },
    )
    if not accepted:
        raise HTTPException(status_code=409, detail="job_id 不匹配或已被新作业取代")
    return {"ok": True}
