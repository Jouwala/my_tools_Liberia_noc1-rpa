# -*- coding: utf-8 -*-
"""WhatsApp 网页扫码登录接口 —— 供设置页「WhatsApp 登录」Tab 使用。

业务逻辑（通道文件读写、状态汇总）都在
`backend/services/whatsapp_login_service.py`；本文件只做 HTTP 薄封装。

端点（均走 require_protected；本地访问回环放行）：
- GET  /api/whatsapp/login/status?device=notify|bot  → 连接状态 + 出码状态 + 二维码
- POST /api/whatsapp/login/qr  { "device": "notify"|"bot" } → 请求该设备重新出码

> 两个设备对应 what**同一个号码的两个「已关联设备」**（notify=告警推送，bot=知识库问答）。
> 同号必须各扫各的凭据，不能共用（否则 code=440 互踢）。详见服务模块头。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.security import require_protected
from backend.services import whatsapp_login_service as svc

logger = logging.getLogger("whatsapp_login_router")

router = APIRouter(tags=["whatsapp_login"])


class QrRequestBody(BaseModel):
    device: str


@router.get("/api/whatsapp/login/status", dependencies=[Depends(require_protected)])
def get_login_status(device: str = Query(..., description="设备：notify 或 bot")):
    """查询某设备的登录/出码状态（前端轮询此端点取二维码）。"""
    try:
        return svc.get_status(device)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/whatsapp/login/qr", dependencies=[Depends(require_protected)])
def post_login_qr(body: QrRequestBody):
    """请求某设备重新出码（清旧凭据 + 重连）。

    ⚠️ 副作用：会让该设备断开当前连接并**备份旧凭据**（只改名不删除，可人工改回）。
    """
    try:
        return svc.request_qr(body.device)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
