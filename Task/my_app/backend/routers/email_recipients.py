"""
email_recipients.py - 邮件收件人名单管理 API 路由
================================================
提供"设置 → 邮件收件人"页签所需的查询/更新/恢复默认接口：
- GET  /api/email-recipients          列出全部收件人组（当前生效值 + 来源标记 db/default）
- PUT  /api/email-recipients          按 key 更新主送/抄送（写 db/app.db email_recipients 表）
- POST /api/email-recipients/reset     按 key 恢复默认（删除记录，下次发送回退读原名单）

存储实现见 backend/services/email_recipient_store.py。
与 routers/credentials.py 保持一致的接口风格。
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.services.email_recipient_store import (
    EMAIL_RECIPIENT_GROUPS,
    _GROUP_INDEX,
    list_email_recipients,
    set_email_recipients,
    reset_email_recipients,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email-recipients", tags=["email-recipients"])


def _is_en(request: Request) -> bool:
    return (request.headers.get("accept-language") or "").lower().startswith("en")


class EmailRecipientUpdate(BaseModel):
    key: str
    to: str | None = None
    cc: str | None = None


class EmailRecipientReset(BaseModel):
    key: str


@router.get("")
def get_email_recipients(request: Request):
    """列出全部收件人组（当前生效 to/cc 文本 + 来源标记 db/default + 更新时间）。"""
    return {"recipients": list_email_recipients("en" if _is_en(request) else "zh")}


@router.put("")
def update_email_recipients(body: EmailRecipientUpdate, request: Request):
    """更新指定 key 的主送/抄送。to/cc 为 null 或空串时记为空（清空该字段，发送时回退默认）。"""
    en = _is_en(request)
    if body.key not in _GROUP_INDEX:
        raise HTTPException(status_code=400, detail=(f"Unknown email recipient group: {body.key}" if en else f"未知收件人组: {body.key}"))
    if not body.to and not body.cc:
        raise HTTPException(status_code=400, detail=("To and Cc cannot both be empty" if en else "主送和抄送不能同时为空"))
    set_email_recipients(body.key, body.to, body.cc)
    logger.info(f"[EMAIL-RCPT] 收件人已更新: {body.key}")
    return {"status": "ok", "key": body.key, "message": ("Email recipients saved, effective immediately" if en else "收件人已保存，立即生效")}


@router.post("/reset")
def reset_email_recipients_endpoint(body: EmailRecipientReset, request: Request):
    """恢复默认：删除数据库记录，下次发送回退读取原名单文件。"""
    en = _is_en(request)
    if body.key not in _GROUP_INDEX:
        raise HTTPException(status_code=400, detail=(f"Unknown email recipient group: {body.key}" if en else f"未知收件人组: {body.key}"))
    reset_email_recipients(body.key)
    logger.info(f"[EMAIL-RCPT] 收件人已恢复默认: {body.key}")
    return {"status": "ok", "key": body.key, "message": ("Reset to default list" if en else "已恢复为默认名单")}
