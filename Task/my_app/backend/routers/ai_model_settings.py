# -*- coding: utf-8 -*-
"""AI 模型设置 API（Settings → AI Model 页签）

GET  /api/ai-model-settings       → 当前配置 + schema + defaults
PUT  /api/ai-model-settings       → 更新配置（需要鉴权）
GET  /api/ai-model-settings/chain → 返回当前调用链描述（供前端展示）
"""
from fastapi import APIRouter, Depends

from backend.security import require_protected
from backend.services import ai_model_config

router = APIRouter(tags=["ai-model-settings"])


@router.get("/api/ai-model-settings")
def get_ai_model_settings():
    """返回当前配置 + schema + defaults（无需鉴权）"""
    return ai_model_config.get_effective()


@router.put("/api/ai-model-settings", dependencies=[Depends(require_protected)])
def update_ai_model_settings(body: dict):
    """更新配置（需要鉴权）；保存后返回新配置"""
    cfg = ai_model_config.update_config(body)
    return {"success": True, "config": cfg}


@router.get("/api/ai-model-settings/chain")
def get_model_chain():
    """返回当前模型调用链描述（供前端展示「本地优先」或「Open WebUI 优先」）"""
    cfg = ai_model_config.get_config()
    provider = cfg.get("provider", "both")
    local_model = cfg.get("local_model", "deepseek-v4.1-flash")
    openwebui_model = cfg.get("openwebui_model", "agnes-2.5-flash")
    local_base = cfg.get("local_base_url", "")
    owu_base = cfg.get("openwebui_base_url", "")

    if provider == "local":
        chain = f"本地模型（{local_model}）@ {local_base}"
    elif provider == "openwebui":
        chain = f"Open WebUI（{openwebui_model}）@ {owu_base}"
    else:
        chain = f"本地模型（{local_model}）@ {local_base} → Open WebUI（{openwebui_model}）@ {owu_base}"

    return {
        "provider": provider,
        "chain": chain,
        "local_model": local_model,
        "openwebui_model": openwebui_model,
        "local_base_url": local_base,
        "openwebui_base_url": owu_base,
    }
