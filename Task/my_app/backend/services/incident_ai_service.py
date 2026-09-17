# -*- coding: utf-8 -*-
"""
事件总览 —— AI 分析供应商代理（忠实移植自 Unified_Tools/incident_overview/app.py）

对齐说明
--------
原版在 Flask 里为 6 个供应商各写了一个 /api/ai/<provider> 端点，前端 index.html 的
AI_MODELS 表按 provider 直接命中对应端点。为保证「与原版效果完全一致」，这里逐个
移植其模型回退顺序、超时/重试策略、响应解析分支与错误信息格式。

安全边界
--------
api_key **一律由前端请求体传入**（原版即为此设计：用户在界面里填自己的 Key），
服务端不落盘、不硬编码、不写日志。源工具 IP_Trace_Tool 中那个硬编码的 OpenAI Key
不在此迁移范围内。

返回约定
--------
每个 call_* 返回 (payload: dict, status_code: int)，由路由层统一转成 JSONResponse，
与原版 jsonify(...), code 的行为一致。
"""
from __future__ import annotations

import json
import os
import re
import time
import traceback
from typing import Any, Dict, Iterator, List, Tuple

import requests

logger_prefix = "[incident-ai]"

SYSTEM_PROMPT = "You are a data analyst specializing in incident management systems."

Result = Tuple[Dict[str, Any], int]


def _need_key() -> Result:
    return {"error": "API key required"}, 400


def _err_msg_from(response: requests.Response) -> str:
    """按原版逻辑从错误响应里抽取 message，失败则截断原文 200 字符。"""
    detail = response.text
    try:
        return response.json().get("error", {}).get("message", detail[:200])
    except Exception:  # noqa: BLE001
        return detail[:200]


# --------------------------------------------------------------------------
# OpenAI
# --------------------------------------------------------------------------
def call_openai(api_key: str, prompt: str, **_: Any) -> Result:
    if not api_key:
        return _need_key()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 1500,
    }
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers, json=payload, timeout=30,
        )
        if r.status_code != 200:
            return {"error": f"API returned {r.status_code}", "detail": r.text[:200]}, 500
        result = r.json()
        choices = result.get("choices") or []
        if choices:
            return {"analysis": choices[0]["message"]["content"].strip()}, 200
        return {"error": "Unexpected response format", "response": result}, 500
    except requests.exceptions.RequestException as e:
        return {"error": f"Request failed: {e}"}, 500


# --------------------------------------------------------------------------
# Google Gemini（多模型回退）
# --------------------------------------------------------------------------
GEMINI_MODELS = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"]


def call_gemini(api_key: str, prompt: str, **_: Any) -> Result:
    if not api_key:
        return _need_key()
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1500},
    }
    for model in GEMINI_MODELS:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        try:
            r = requests.post(url, json=payload, timeout=30)
            if r.status_code == 200:
                result = r.json()
                candidates = result.get("candidates") or []
                if candidates:
                    content = candidates[0].get("content") or {}
                    parts = content.get("parts") or []
                    if parts:
                        return {"analysis": parts[0]["text"].strip()}, 200
                if "text" in result:
                    return {"analysis": result["text"].strip()}, 200
                return {"error": "Unexpected response format",
                        "response": str(result)[:500]}, 500
            if r.status_code == 404:
                continue  # 模型不存在，试下一个
            if model == GEMINI_MODELS[-1]:
                return {"error": f"API returned {r.status_code}",
                        "detail": _err_msg_from(r)}, 500
        except requests.exceptions.RequestException as e:
            if model == GEMINI_MODELS[-1]:
                return {"error": f"Request failed: {e}"}, 500
    return {"error": "All Gemini models failed"}, 500


# --------------------------------------------------------------------------
# 字节豆包（多模型回退 + 超时重试）
# --------------------------------------------------------------------------
DOUBAO_MODELS = [
    "doubao-seed-1-8-251228",
    "doubao-seed-1-6-flash-250828",
    "doubao-1-5-pro-32k-250115",
    "kimi-k2-thinking-251104",
]
DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


def call_doubao(api_key: str, prompt: str, model: str = "", **_: Any) -> Result:
    if not api_key:
        return _need_key()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    models_to_try: List[str] = [model] if model and model in DOUBAO_MODELS else DOUBAO_MODELS
    max_retries, timeout, retry_delay = 2, 60, 2

    for model_to_use in models_to_try:
        is_last_model = model_to_use == models_to_try[-1]
        for attempt in range(max_retries):
            payload = {
                "model": model_to_use,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 1500,
            }
            try:
                r = requests.post(DOUBAO_URL, headers=headers, json=payload, timeout=timeout)
                if r.status_code == 200:
                    result = r.json()
                    choices = result.get("choices") or []
                    if choices:
                        return {"analysis": choices[0]["message"]["content"].strip()}, 200
                    return {"error": "Unexpected response format",
                            "response": str(result)[:500]}, 500
                # 非 200：最后一个模型才报错，否则换模型
                if is_last_model:
                    return {"error": f"API returned {r.status_code}",
                            "detail": _err_msg_from(r)}, 500
                break
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))  # 递增退避
                    continue
                if is_last_model:
                    return {"error": "Request timeout",
                            "detail": f"All retries failed for model {model_to_use}. "
                                      "The API may be slow or unavailable."}, 500
                break
            except requests.exceptions.RequestException as e:
                retriable = "timeout" in str(e).lower() or "connection" in str(e).lower()
                if attempt < max_retries - 1 and retriable:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                if is_last_model and attempt == max_retries - 1:
                    return {"error": f"Request failed: {e}"}, 500
                break
    return {"error": "All Doubao models failed"}, 500


# --------------------------------------------------------------------------
# 通义千问（DashScope 专有格式）
# --------------------------------------------------------------------------
def call_qianwen(api_key: str, prompt: str, **_: Any) -> Result:
    if not api_key:
        return _need_key()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "qwen-turbo",
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "parameters": {"temperature": 0.7, "max_tokens": 1500},
    }
    try:
        r = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
            headers=headers, json=payload, timeout=30,
        )
        if r.status_code != 200:
            return {"error": f"API returned {r.status_code}", "detail": r.text[:200]}, 500
        result = r.json()
        choices = (result.get("output") or {}).get("choices") or []
        if choices:
            return {"analysis": choices[0]["message"]["content"].strip()}, 200
        return {"error": "Unexpected response format", "response": result}, 500
    except requests.exceptions.RequestException as e:
        return {"error": f"Request failed: {e}"}, 500


# --------------------------------------------------------------------------
# GLM Coding（智谱 AI，多模型回退）
# --------------------------------------------------------------------------
GLM_MODELS = ["glm-4", "glm-4-flash", "glm-3-turbo"]
GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def call_glm_coding(api_key: str, prompt: str, **_: Any) -> Result:
    if not api_key:
        return _need_key()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for model in GLM_MODELS:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 1500,
        }
        try:
            r = requests.post(GLM_URL, headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                result = r.json()
                choices = result.get("choices") or []
                if choices:
                    return {"analysis": choices[0]["message"]["content"].strip()}, 200
                return {"error": "Unexpected response format",
                        "response": str(result)[:500]}, 500
            if r.status_code == 404:
                continue
            if model == GLM_MODELS[-1]:
                return {"error": f"API returned {r.status_code}",
                        "detail": _err_msg_from(r)}, 500
        except requests.exceptions.RequestException as e:
            if model == GLM_MODELS[-1]:
                return {"error": f"Request failed: {e}"}, 500
    return {"error": "All GLM Coding models failed"}, 500


# --------------------------------------------------------------------------
# DeepSeek（经 ModelScope，支持 reasoning_content）
# --------------------------------------------------------------------------
DEEPSEEK_BASE_URL = "https://api-inference.modelscope.cn/v1"
DEEPSEEK_MODEL = "deepseek-ai/DeepSeek-R1-0528"


def _deepseek_client(api_key: str):
    from openai import OpenAI  # 延迟导入：未安装时按原版返回提示

    return OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=api_key)


def _deepseek_create(api_key: str, prompt: str, stream: bool):
    client = _deepseek_client(api_key)
    return client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        stream=stream,
        temperature=0.7,
        max_tokens=1500,
    )


def call_deepseek(api_key: str, prompt: str, **_: Any) -> Result:
    """非流式分支（前端 index.html 固定发 stream:false，走的就是这里）。"""
    if not api_key:
        return _need_key()
    try:
        response = _deepseek_create(api_key, prompt, stream=False)
    except ImportError:
        return {"error": "OpenAI library not installed. "
                         "Please install it with: pip install openai"}, 500
    except Exception as e:  # noqa: BLE001
        return _deepseek_error(e)

    try:
        choices = getattr(response, "choices", None) or []
        if choices:
            message = choices[0].message
            content = getattr(message, "content", "") or ""
            reasoning = getattr(message, "reasoning_content", None) \
                or getattr(response, "reasoning_content", None)
            return {
                "analysis": content.strip(),
                "reasoning": reasoning.strip() if reasoning else None,
            }, 200
        if hasattr(response, "content"):
            return {"analysis": (response.content or "").strip(), "reasoning": None}, 200
        return {"error": "Unexpected response format",
                "response": str(response)[:500],
                "response_type": type(response).__name__}, 500
    except AttributeError as e:
        return {"error": f"Failed to parse response: {e}",
                "response_type": type(response).__name__}, 500


def _deepseek_error(e: Exception) -> Result:
    """还原原版对 OpenAI SDK 异常的 status_code 提取逻辑。"""
    error_msg = str(e)
    if hasattr(e, "status_code"):
        error_msg = f"API returned {e.status_code}: {error_msg}"
    elif hasattr(e, "response") and hasattr(e.response, "status_code"):
        error_msg = f"API returned {e.response.status_code}: {error_msg}"
        try:
            detail = e.response.json()
            if "error" in detail:
                error_msg = detail.get("error", {}).get("message", error_msg)
        except Exception:  # noqa: BLE001
            pass
    trace = traceback.format_exc()
    return {"error": error_msg, "detail": trace[:500]}, 500


def stream_deepseek(api_key: str, prompt: str) -> Iterator[str]:
    """SSE 流式分支：逐段吐 reasoning / answer，与原版事件协议一致。"""
    try:
        response = _deepseek_create(api_key, prompt, stream=True)
    except Exception as e:  # noqa: BLE001
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        return

    done_reasoning = False
    reasoning_text, answer_text = "", ""
    try:
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning_chunk = getattr(delta, "reasoning_content", "") or ""
            answer_chunk = getattr(delta, "content", "") or ""
            if reasoning_chunk:
                reasoning_text += reasoning_chunk
                yield f"data: {json.dumps({'type': 'reasoning', 'content': reasoning_chunk})}\n\n"
            elif answer_chunk:
                if not done_reasoning:
                    yield ("data: " + json.dumps(
                        {"type": "separator", "content": "=== Final Answer ==="}) + "\n\n")
                    done_reasoning = True
                answer_text += answer_chunk
                yield f"data: {json.dumps({'type': 'answer', 'content': answer_chunk})}\n\n"
        yield ("data: " + json.dumps(
            {"type": "done", "reasoning": reasoning_text, "answer": answer_text}) + "\n\n")
    except Exception as e:  # noqa: BLE001
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"


# --------------------------------------------------------------------------
# Agnes AI（apihub.agnes-ai.com，OpenAI 兼容格式）
# --------------------------------------------------------------------------
AGNES_URL = "https://apihub.agnes-ai.com/v1/chat/completions"
AGNES_MODELS_URL = "https://apihub.agnes-ai.com/v1/models"
# 模型可用环境变量覆盖（AGNES_MODEL=...），默认仍是原版的 agnes-2.5-flash，保持「与原版效果一致」。
AGNES_MODEL = (os.environ.get("AGNES_MODEL", "agnes-2.5-flash") or "").strip() or "agnes-2.5-flash"

# ---- 2026-09-15 加固：上游把模型下线时不再直接失败 ----
# 原版（以及本文件的初版）把模型写死成 agnes-2.5-flash：上游一旦下线该模型，这个 provider
# 立刻变成全失败、没有任何退路。这里只加「模型被拒时的兜底」——用同一个 Key 问一次上游
# /v1/models，挑最新的 agnes-*-flash 重试一次。
# 注意：**模型正常时行为与原版完全一致**（不额外请求、不换模型），仅在错误文本明确是
# 「模型不存在 / 无可用通道」时才触发，因此不会影响其它错误分支的呈现。
#
# 触发条件是真机测出来的（别想当然）：apihub 这个网关对不存在的模型返回的是
#   HTTP 503 + {"error":{"message":"No available channel for model xxx under group default (distributor)"}}
# 而**不是** OpenAI 风格的 400/404 Model not found。所以状态码要连 503 一起收，
# 但必须用错误文本兜住，否则会把「上游忙」的瞬时 503 误判成模型下线。
_AGNES_FLASH_RE = re.compile(r"agnes[-_.]?[\d.]+-flash", re.IGNORECASE)
_AGNES_EXCLUDE_RE = re.compile(r"image|video|embed|bge|whisper|tts", re.IGNORECASE)
_AGNES_MODEL_GONE_RE = re.compile(
    r"model\s*(not\s*found|not_available|unavailable|invalid|does\s*not\s*exist)"
    r"|no\s*such\s*model|unknown\s*model|no\s*available\s*channel\s*for\s*model|模型不存在",
    re.IGNORECASE)
_agnes_cache: Dict[str, Any] = {"model": "", "ts": 0.0}
_AGNES_CACHE_TTL = 600


def _agnes_ver_key(model_id: str):
    """'agnes-3.0-flash' -> (3, 0)，用于「取版本最新」。取不到则 (0,)。"""
    m = re.search(r"(\d+(?:\.\d+)*)", model_id or "")
    if not m:
        return (0,)
    try:
        return tuple(int(p) for p in m.group(1).split("."))
    except ValueError:
        return (0,)


def _agnes_latest_flash(api_key: str) -> str:
    """问上游 /v1/models，返回最新的 agnes-*-flash；排除 image/video/embed 等多模态条目。
    任何失败都返回 ''（调用方保持原错误行为）。结果缓存 10 分钟。"""
    if _agnes_cache["model"] and time.time() - _agnes_cache["ts"] < _AGNES_CACHE_TTL:
        return _agnes_cache["model"]
    try:
        r = requests.get(AGNES_MODELS_URL,
                         headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
        if r.status_code != 200:
            return ""
        ids = [str(m.get("id") or "") for m in (r.json().get("data") or [])]
    except Exception:  # noqa: BLE001
        return ""
    cands = sorted((i for i in ids
                    if _AGNES_FLASH_RE.search(i) and not _AGNES_EXCLUDE_RE.search(i)),
                   key=_agnes_ver_key, reverse=True)
    if not cands:
        return ""
    _agnes_cache.update({"model": cands[0], "ts": time.time()})
    return cands[0]


def call_agnes(api_key: str, prompt: str, **_: Any) -> Result:
    if not api_key:
        return _need_key()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _post(model: str) -> requests.Response:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 1500,
        }
        return requests.post(AGNES_URL, headers=headers, json=payload, timeout=60)

    try:
        r = _post(AGNES_MODEL)
        if r.status_code != 200:
            detail = _err_msg_from(r)
            # 仅「模型本身不可用」才兜底换最新 flash 重试一次；其它错误维持原行为。
            # 503 也收：apihub 网关对不存在的模型就是 503 + "No available channel for model ..."。
            if r.status_code in (400, 404, 503) and _AGNES_MODEL_GONE_RE.search(detail):
                newer = _agnes_latest_flash(api_key)
                if newer and newer != AGNES_MODEL:
                    r = _post(newer)
                    detail = "" if r.status_code == 200 else _err_msg_from(r)
            if r.status_code != 200:
                return {"error": f"API returned {r.status_code}",
                        "detail": detail}, 500
        result = r.json()
        choices = result.get("choices") or []
        if choices:
            return {"analysis": (choices[0]["message"]["content"] or "").strip()}, 200
        return {"error": "Unexpected response format", "response": str(result)[:500]}, 500
    except requests.exceptions.RequestException as e:
        return {"error": f"Request failed: {e}"}, 500


# --------------------------------------------------------------------------
# 分发表：key 与前端 AI_MODELS 的 endpoint 尾段一一对应
# --------------------------------------------------------------------------
PROVIDERS = {
    "openai": call_openai,
    "gemini": call_gemini,
    "doubao": call_doubao,
    "qianwen": call_qianwen,
    "glm-coding": call_glm_coding,
    "deepseek": call_deepseek,
    "agnes": call_agnes,
}


def dispatch(provider: str, body: Dict[str, Any]) -> Result:
    fn = PROVIDERS.get(provider)
    if fn is None:
        return {"error": f"Unknown AI provider: {provider}",
                "supported": sorted(PROVIDERS)}, 404
    try:
        return fn(
            api_key=body.get("api_key", ""),
            prompt=body.get("prompt", ""),
            model=body.get("model", "") or "",
        )
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "traceback": traceback.format_exc()}, 500
