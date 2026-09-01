"""WhatsApp 出图 / 扩展作业接口 —— 供「WhatsApp 定时发图」Chrome 扩展使用。

与 backend/services/whatsapp_service.py（/myapp/?page=sync 的 WhatsApp Message Send 任务）
共用同一份图片目录与群组/备注配置，但发送由 Chrome 扩展在已登录的 WhatsApp Web 标签页里完成。
业务逻辑（扫描图片 / 备注规则 / 作业状态机）都在
backend/services/whatsapp_ext_service.py；本文件只做 HTTP 薄封装。

端点（均走 require_protected；扩展与后端同机，回环地址自动放行，无需 token）：
- GET  /api/whatsapp/outbox            → { groups, items, generated_at }（图片清单）
- GET  /api/whatsapp/outbox/image      → FileResponse（带路径穿越防护）
- GET  /api/whatsapp/ext/job           → 认领一个待发作业（含图片清单），无则 {pending:false}
- POST /api/whatsapp/ext/job/result    → 扩展回报发送结果
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.security import require_protected
from backend.services import whatsapp_ext_service as ext

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
    groups_sent: list[str] = []
    errors: list[str] = []
    elapsed_seconds: Optional[float] = None


@router.get("/api/whatsapp/ext/job", dependencies=[Depends(require_protected)])
def poll_job():
    """扩展轮询：认领一个待发作业（附带最新图片清单）；无待发作业则返回 {pending:false}。"""
    claimed = ext.claim_pending_job()
    if claimed is None:
        return {"pending": False}
    return claimed


@router.post("/api/whatsapp/ext/job/result", dependencies=[Depends(require_protected)])
def post_job_result(body: JobResultBody):
    """扩展回报发送结果。"""
    accepted = ext.complete_job(
        body.job_id,
        {
            "ok": body.ok,
            "groups_sent": body.groups_sent,
            "errors": body.errors,
            "elapsed_seconds": body.elapsed_seconds,
        },
    )
    if not accepted:
        raise HTTPException(status_code=409, detail="job_id 不匹配或已被新作业取代")
    return {"ok": True}
