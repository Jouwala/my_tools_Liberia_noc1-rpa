# -*- coding: utf-8 -*-
"""portal_qa.py - 门户「问答助手」API（v3 /olbrportal 右下角挂件）
================================================================

链路：

    浏览器（同源 /api/portal-qa/ask）
      → my_app 后端（本文件：鉴权 + 会话命名空间 + 超时/错误翻译）
      → 127.0.0.1:9269（whatsapp-kb-bot 的 src/http-server.js，只绑回环）
      → routeAnswer()（与 WhatsApp 群里**同一套**答题引擎与知识库）

为什么要在后端转一手，而不是让浏览器直连 / 在 nginx 里加 upstream：

1. **鉴权**：9269 只管答题、不做鉴权（它只绑回环）。放在 `/api/` 下即自动继承
   my_app 的会话中间件（见 main.py 的 require_session_middleware），与其它
   门户接口同一套登录态，不新增第二种鉴权。
2. **只绑回环**：服务本身不监听局域网，浏览器拿不到 9269，必须由同机后端中转
   —— 与 routers/realtime_proxy.py 的取舍一致。
3. **可换部署**：`PORTAL_QA_URL` 可指向另一台机器的问答服务；默认本机。

端点：
- POST /api/portal-qa/ask            提问 {question, lang:'zh'|'en', clientId}
- POST /api/portal-qa/session/clear  清空本页会话记忆
- GET  /api/portal-qa/health         服务与索引/模型状态（挂件首次打开时探测）
"""
from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.services import portal_auth, portal_qa_ctl

logger = logging.getLogger(__name__)

router = APIRouter(tags=["portal-qa"])

# 默认本机；换机器部署时改这一个环境变量即可（服务端到服务端，不经浏览器）
QA_URL = (os.environ.get("PORTAL_QA_URL") or f"http://127.0.0.1:{portal_qa_ctl.PORT}").rstrip("/")

# 单次提问上限：知识库问答不是文档生成，超长输入只会拖慢本地模型
MAX_QUESTION_CHARS = 500


class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_CHARS)
    lang: str = Field("zh", pattern="^(zh|en)$")
    clientId: str = Field("", max_length=64)


class ClearBody(BaseModel):
    clientId: str = Field("", max_length=64)


def _session_key(request: Request, client_id: str) -> str:
    """把浏览器的 clientId 绑定到当前登录用户，避免不同人撞同一个记忆槽。

    没登录（理论上中间件已拦）时退化成按来源 IP 分桶。
    """
    user = portal_auth.current_user(request) or {}
    who = str(user.get("username") or "").strip() or portal_auth.client_ip(request) or "anon"
    cid = (client_id or "").strip() or "default"
    return f"{who}#{cid}"


def _post(path: str, payload: dict, timeout: float) -> httpx.Response:
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0)) as client:
        return client.post(f"{QA_URL}{path}", json=payload)


def _upstream_unavailable(e: Exception) -> HTTPException:
    logger.warning("[portal-qa] upstream %s failed: %s", QA_URL, e)
    return HTTPException(
        status_code=503,
        detail="问答服务暂时不可用：本地问答进程未能启动，请稍后重试或联系管理员查看 log/portal_qa_*.log",
    )


@router.get("/api/portal-qa/health")
def qa_health():
    """服务健康 + 索引规模 + 当前对话通道（挂件用它决定是否显示「未就绪」）。"""
    st = portal_qa_ctl.status()
    if not st.get("healthy"):
        # 首次打开时才拉起，避免没人用也常驻进程
        st["ensure"] = portal_qa_ctl.ensure_service()
        st = portal_qa_ctl.status()
    return st


@router.post("/api/portal-qa/ask")
def qa_ask(body: AskBody, request: Request):
    """转发一次提问。超时给得很宽：.27 上 7b 与嵌入模型要来回换载（单次 7~30s）。"""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    ensure = portal_qa_ctl.ensure_service()
    if ensure.get("status") in ("missing", "error"):
        raise HTTPException(status_code=503, detail=f"问答服务未就绪：{ensure.get('error')}")

    payload = {
        "question": question,
        "lang": body.lang,
        "clientId": _session_key(request, body.clientId),
    }
    try:
        resp = _post("/ask", payload, timeout=300.0)
    except Exception as e:  # noqa: BLE001 - 连不上/超时都归为「服务不可用」
        raise _upstream_unavailable(e) from e

    if resp.status_code >= 500:
        # 服务自己抛的错是给用户看的中文（如「云端模型返回 403」），原样透出
        try:
            detail = resp.json().get("error") or "问答服务内部错误"
        except Exception:  # noqa: BLE001
            detail = resp.text[:300] or "问答服务内部错误"
        logger.warning("[portal-qa] ask failed %s: %s", resp.status_code, detail)
        raise HTTPException(status_code=502, detail=detail)
    if resp.status_code == 400:
        try:
            detail = resp.json().get("error") or "请求不合法"
        except Exception:  # noqa: BLE001
            detail = "请求不合法"
        raise HTTPException(status_code=400, detail=detail)

    return resp.json()


@router.post("/api/portal-qa/session/clear")
def qa_clear(body: ClearBody, request: Request):
    """清空当前页面在多轮记忆里的上下文（服务端按 clientId 存最近 5 轮）。"""
    key = _session_key(request, body.clientId)
    try:
        _post("/session/clear", {"clientId": key}, timeout=10.0)
    except Exception as e:  # noqa: BLE001 - 清空失败不影响用户继续提问
        logger.warning("[portal-qa] clear session failed: %s", e)
    return {"ok": True}
