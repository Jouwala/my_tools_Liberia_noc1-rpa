#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api_selector.py — OpenClaw 智能模型路由 / API 优选脚本（增强版）

功能：
  1. 从候选 API 列表探测可用端点；有密钥的远端会拉取 /models，并与 preferred_models
     合并生成「多模型候选队列」（免费/小模型优先）。
  2. 对每个提供者按候选队列级联探测：一个模型失败会自动换下一个，
     429 有限次回退重试，避免「只测一个大模型就整站判死」。
  3. 校验响应内容（不能只看 HTTP 200），并读取错误 body 区分余额不足/模型不存在等。
  4. 在可用且时延低于阈值的远端中选主用；本地 Ollama 永远作为备用第一顺位。
  5. 安全改写 openclaw.json（先备份再 merge）。

仅使用 Python 标准库，适合 Windows 任务计划程序无人值守运行。

用法：
  python api_selector.py
  python api_selector.py --dry-run
  python api_selector.py --config <path>
  python api_selector.py --threshold 5000 --probes 2 --max-models 5
  python api_selector.py --no-discover
  python api_selector.py --parallel 4
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as _dt
import json
import os
import re
import shutil
import statistics
import sys
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------- #
# Windows 控制台 UTF-8（任务计划程序默认 cp1252，中文日志会直接崩溃）
# --------------------------------------------------------------------------- #
def _force_utf8_stdio():
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_force_utf8_stdio()

# --------------------------------------------------------------------------- #
# 默认值 / 常量
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG = r"C:\Users\ZTEEMS\.openclaw\openclaw.json"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROVIDERS_FILE = os.path.join(SCRIPT_DIR, "providers.json")
REPORT_FILE = os.path.join(SCRIPT_DIR, "last_run.json")
REPORT_MD_FILE = os.path.join(SCRIPT_DIR, "test_results.md")

HTTP_TIMEOUT = 25
LIST_TIMEOUT = 15
LATENCY_THRESHOLD_MS = 5000
PROBES = 2
MAX_MODELS_PER_PROVIDER = 5
MAX_429_RETRIES = 2
RATE_LIMIT_BACKOFF_SEC = 1.5
DEFAULT_PARALLEL = 4

# 名称启发式：越靠前越优先（免费/小/快）
FREE_HINTS = (":free", "/free", "free-", "-free")
SMALL_HINTS = (
    "flash", "nano", "mini", "tiny", "1.5b", "1.2b", "2b", "3b", "4b", "7b", "8b", "9b",
    "instruct-free", "lfm",
)
LARGE_PENALTY_HINTS = (
    "70b", "72b", "120b", "235b", "397b", "405b", "480b", "671b", "ultra", "large",
)
# 错误 body 关键词
BALANCE_HINTS = (
    "balance", "insufficient", "余额", "欠费", "credit", "quota", "payment",
    "充值", "用量上限", "not support model", "token plan",
)
MODEL_MISSING_HINTS = (
    "model does not exist", "model_not_found", "unknown model", "no endpoints",
    "not found", "invalid model", "does not exist", "模型不存在", "unavailable for free",
)

EMBEDDED_PROVIDERS = [
    {"key": "zhipu", "name": "ZhiPu GLM 智谱", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "style": "openai", "openclaw_api": "openai-completions", "api_key_env": "ZHIPU_API_KEY",
     "test_model": "glm-4-flash", "context_window": 128000,
     "preferred_models": ["glm-4-flash", "glm-4-flash-250414", "glm-z1-flash", "glm-4.5-flash", "glm-4-air"],
     "enabled": True},
    {"key": "nvidia", "name": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1",
     "style": "openai", "openclaw_api": "openai-completions", "api_key_env": "NVIDIA_API_KEY",
     "test_model": "meta/llama-3.1-8b-instruct", "context_window": 128000,
     "preferred_models": ["llama-3.1-8b", "llama-3.2-3b", "gemma-2-9b", "mistral-7b", "qwen2.5-7b", "llama-3.3-70b"],
     "enabled": True},
    {"key": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
     "style": "openai", "openclaw_api": "openai-completions", "api_key_env": "OPENROUTER_API_KEY",
     "test_model": "openrouter/free", "context_window": 200000,
     "preferred_models": ["openrouter/free", ":free"],
     "prefer_free": True, "extra_headers": {"HTTP-Referer": "https://openclaw.local", "X-Title": "OpenClaw"},
     "enabled": True},
    {"key": "ollama-cloud", "name": "Ollama Cloud", "base_url": "https://ollama.com",
     "style": "ollama", "openclaw_api": None, "api_key_env": "OLLAMA_CLOUD_API_KEY",
     "test_model": "gemma3:4b", "context_window": 128000,
     "preferred_models": ["gemma3:4b", "ministral-3:8b", "gemma3:12b", "llama3.2", "qwen"],
     "enabled": True},
    {"key": "siliconflow", "name": "SiliconFlow 硅基流动", "base_url": "https://api.siliconflow.cn/v1",
     "style": "openai", "openclaw_api": "openai-completions", "api_key_env": "SILICONFLOW_API_KEY",
     "test_model": "Qwen/Qwen3-8B", "context_window": 32768,
     "preferred_models": ["Qwen/Qwen3-8B", "Qwen/Qwen2.5-7B", "DeepSeek-R1-Distill", "Qwen/Qwen3-4B", "THUDM/glm-4-9b"],
     "enabled": True},
    {"key": "minimax-cn", "name": "MiniMax CN", "base_url": "https://api.minimaxi.com/v1",
     "style": "openai", "openclaw_api": "openai-completions", "api_key_env": "MINIMAX_API_KEY",
     "test_model": "MiniMax-M2", "context_window": 200000,
     "preferred_models": ["MiniMax-M2", "MiniMax-M2.1", "MiniMax-M2.5", "MiniMax-M3"],
     "enabled": True},
    {"key": "ollama", "name": "Local Ollama", "base_url": "http://127.0.0.1:11434",
     "style": "ollama", "openclaw_api": None, "api_key_env": None,
     "test_model": "gemma4-16k", "context_window": 16384,
     "preferred_models": ["gemma4-16k", "gemma3:4b", "phi4-mini", "qwen3:4b", "gemma4"],
     "enabled": True, "local": True},
]


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def log(msg, level="INFO"):
    ts = _dt.datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{ts}][{level}] {msg}")
    except UnicodeEncodeError:
        safe = str(msg).encode("ascii", errors="replace").decode("ascii")
        print(f"[{ts}][{level}] {safe}")


def load_dotenv(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        log(f"loaded env from {path}")
    except Exception as e:
        log(f"failed to load {path}: {e}", "WARN")


def load_providers(path):
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            provs = data.get("providers", data) if isinstance(data, dict) else data
            if isinstance(provs, list) and provs:
                log(f"loaded {len(provs)} providers from {path}")
                return provs
        except Exception as e:
            log(f"failed to read {path}: {e}, using embedded list", "WARN")
    log("using embedded provider list")
    return list(EMBEDDED_PROVIDERS)


def get_api_key(prov, config):
    env_name = prov.get("api_key_env")
    if env_name and os.environ.get(env_name):
        return os.environ[env_name].strip()
    pkey = prov.get("key")
    try:
        existing = config.get("models", {}).get("providers", {}).get(pkey, {})
        if existing.get("apiKey"):
            return existing["apiKey"]
    except Exception:
        pass
    return None


def _size_score(mid: str) -> int:
    """越小越好：提取类似 8b/70b 的参数量做排序辅助。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*[bB]\b", mid)
    if m:
        try:
            return int(float(m.group(1)) * 10)
        except Exception:
            pass
    return 500


def model_priority_key(mid: str, prefs: list[str]) -> tuple:
    """返回可排序 key：越小越优先。"""
    low = mid.lower()
    pref_rank = 999
    for i, p in enumerate(prefs or []):
        pl = p.lower()
        if pl == low or pl in low or low in pl:
            pref_rank = i
            break
    free_rank = 0 if any(h in low for h in FREE_HINTS) else 1
    small_rank = 0 if any(h in low for h in SMALL_HINTS) else 1
    large_rank = 1 if any(h in low for h in LARGE_PENALTY_HINTS) else 0
    return (pref_rank, free_rank, large_rank, small_rank, _size_score(mid), low)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _http_json(url, method="GET", headers=None, body=None, timeout=HTTP_TIMEOUT):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        if v is not None:
            req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace") if raw else "{}"
            try:
                parsed = json.loads(text) if text.strip() else {}
            except json.JSONDecodeError:
                parsed = {"_raw": text[:300]}
            return True, resp.status, parsed, None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except Exception:
            parsed = {"_error_body": raw[:500]}
        if "_error_body" not in parsed and raw:
            parsed = {**parsed, "_error_body": raw[:500]} if isinstance(parsed, dict) else {"_error_body": raw[:500]}
        return False, e.code, parsed, f"HTTP {e.code}"
    except Exception as e:
        return False, None, {"_error": str(e)}, str(e)[:160]


def _auth_headers(style, api_key, extra=None):
    headers = dict(extra or {})
    if not api_key:
        return headers
    if style == "anthropic":
        headers.setdefault("x-api-key", api_key)
        headers.setdefault("anthropic-version", "2023-06-01")
    elif style == "gemini":
        pass
    else:
        # openai / ollama cloud (bearer)
        headers.setdefault("Authorization", f"Bearer {api_key}")
    return headers


def list_models(prov, api_key):
    style = prov.get("style")
    base = prov["base_url"].rstrip("/")
    extra = prov.get("extra_headers") or {}
    if style == "ollama":
        url = base + "/api/tags"
        headers = _auth_headers("ollama", api_key, extra)
    elif style == "openai":
        url = base + "/models"
        headers = _auth_headers("openai", api_key, extra)
    elif style == "anthropic":
        url = base + "/models"
        headers = _auth_headers("anthropic", api_key, extra)
    elif style == "gemini":
        url = base + "/models" + (f"?key={api_key}" if api_key else "")
        headers = dict(extra)
    else:
        return None, None

    ok, code, data, err = _http_json(url, headers=headers, timeout=LIST_TIMEOUT)
    if not ok:
        log(f"  · list models failed ({prov.get('key')}): {err}", "DEBUG")
        return None, err

    ids = []
    free_ids = []
    if style == "ollama":
        for m in data.get("models", []) if isinstance(data, dict) else []:
            if isinstance(m, dict) and m.get("name"):
                ids.append(m["name"])
    elif style == "gemini":
        for m in data.get("models", []) if isinstance(data, dict) else []:
            name = (m.get("name") or "") if isinstance(m, dict) else ""
            ids.append(name.split("/")[-1])
    else:
        for m in (data.get("data") or data.get("models") or []) if isinstance(data, dict) else []:
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            if not mid:
                continue
            ids.append(mid)
            # OpenRouter pricing
            pr = m.get("pricing") or {}
            try:
                p = float(pr.get("prompt") or -1)
                o = float(pr.get("completion") or -1)
                if p == 0 and o == 0:
                    free_ids.append(mid)
            except Exception:
                pass
            if any(h in mid.lower() for h in FREE_HINTS):
                if mid not in free_ids:
                    free_ids.append(mid)
    return (ids or None), free_ids


def build_model_candidates(prov, available_ids, free_ids=None):
    """构建有序候选模型列表：preferred + free + 小模型，去重。"""
    prefs = list(prov.get("preferred_models") or [])
    test = prov.get("test_model")
    available_ids = list(available_ids or [])
    free_ids = list(free_ids or [])
    prefer_free = bool(prov.get("prefer_free"))
    avail_lower = {m.lower(): m for m in available_ids}

    candidates = []
    seen = set()

    def add(mid):
        if not mid or mid in seen:
            return
        candidates.append(mid)
        seen.add(mid)

    def looks_like_model_id(p: str) -> bool:
        """完整模型 id 可在无目录时直接尝试；纯启发式片段（如 ':free'/'qwen'）不行。"""
        if not p or p.startswith(":") or "*" in p:
            return False
        # 明确的厂商/模型 id
        if "/" in p or p.startswith("glm-") or p.startswith("MiniMax") or p.startswith("step-"):
            return True
        if ":" in p:  # ollama tags e.g. gemma3:4b
            return True
        # 带版本号的 openai 风格名
        if re.search(r"\d", p) and ("-" in p or "_" in p) and len(p) >= 6:
            return True
        return False

    # 1) preferred：精确匹配 > 子串匹配(小模型优先) > 直接尝试配置 id
    for p in prefs:
        pl = p.lower()
        if available_ids:
            if pl in avail_lower:
                add(avail_lower[pl])
                continue
            matched = [mid for mid in available_ids if pl in mid.lower()]
            matched.sort(key=lambda m: model_priority_key(m, prefs))
            for mid in matched[:3]:
                add(mid)
        if looks_like_model_id(p):
            add(p)

    # 2) 免费优先（OpenRouter 等）
    if prefer_free:
        add("openrouter/free")
        free_sorted = sorted(free_ids, key=lambda m: model_priority_key(m, prefs))
        for mid in free_sorted[:8]:
            add(mid)

    # 3) test_model
    add(test)

    # 4) 其余 available 按启发式补齐
    if available_ids:
        rest = sorted(available_ids, key=lambda m: model_priority_key(m, prefs))
        for mid in rest:
            add(mid)
            if len(candidates) >= max(MAX_MODELS_PER_PROVIDER * 3, 12):
                break

    max_n = int(prov.get("max_models") or MAX_MODELS_PER_PROVIDER)
    return candidates[:max_n] if candidates else ([test] if test else [])


def _build_request(style, base, api_key, model, extra_headers=None):
    base = base.rstrip("/")
    extra = extra_headers or {}
    if style == "ollama":
        url = base + "/api/chat"
        headers = _auth_headers("ollama", api_key, extra)
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
            "options": {"num_predict": 8},
        }
    elif style == "anthropic":
        url = base + "/messages"
        headers = _auth_headers("anthropic", api_key, extra)
        body = {"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "ping"}]}
    elif style == "gemini":
        url = f"{base}/models/{model}:generateContent" + (f"?key={api_key}" if api_key else "")
        headers = dict(extra)
        body = {
            "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 8},
        }
    else:
        url = base + "/chat/completions"
        headers = _auth_headers("openai", api_key, extra)
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
            "stream": False,
        }
    return url, headers, body


def _extract_text(style, data):
    if not isinstance(data, dict):
        return ""
    try:
        if style == "ollama":
            return (data.get("message") or {}).get("content") or ""
        if style == "anthropic":
            parts = data.get("content") or []
            if parts and isinstance(parts[0], dict):
                return parts[0].get("text") or ""
            return ""
        if style == "gemini":
            cands = data.get("candidates") or []
            if not cands:
                return ""
            parts = ((cands[0].get("content") or {}).get("parts") or [])
            if parts and isinstance(parts[0], dict):
                return parts[0].get("text") or ""
            return ""
        # openai
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        return msg.get("content") or choices[0].get("text") or ""
    except Exception:
        return ""


def classify_status(code, err, body):
    text_parts = [str(err or ""), str(body or "")]
    if isinstance(body, dict):
        text_parts.append(json.dumps(body, ensure_ascii=False)[:800])
    s = " ".join(text_parts).lower()

    if code == 401 or "http 401" in s:
        return "auth_invalid", "密钥被拒绝 (401)"
    if code == 402 or "http 402" in s:
        return "payment_required", "需付费/余额不足 (402)"
    if any(h in s for h in BALANCE_HINTS) and (code in (402, 403, 429, 400) or code is None):
        return "balance", "余额/配额不足"
    if code == 429 or "rate" in s and "limit" in s:
        return "rate_limited", "触发限流 (429)"
    if any(h in s for h in MODEL_MISSING_HINTS) or code in (404,):
        # 404 may also be bad endpoint; model-ish messages win
        if any(h in s for h in MODEL_MISSING_HINTS) or "model" in s:
            return "model_unavailable", "模型不可用/不存在"
        return "bad_endpoint", "端点路径错误 (404)"
    if code == 403:
        return "forbidden", "无权限 (403)"
    if code == 405:
        return "bad_endpoint", "端点方法不允许 (405)"
    if "timed out" in s or "timeout" in s:
        return "timeout", "网络超时"
    if "getaddrinfo" in s or "name or service" in s or "11001" in s:
        return "dns", "DNS 解析失败"
    if code and code >= 500:
        return "server_error", f"服务端错误 ({code})"
    if code:
        return "http_error", f"HTTP {code}"
    return "error", (str(err) or "unknown")[:80]


def probe_once(prov, api_key, model):
    style = prov.get("style")
    url, headers, body = _build_request(
        style, prov["base_url"], api_key, model, prov.get("extra_headers")
    )
    t0 = time.perf_counter()
    ok, code, data, err = _http_json(url, method="POST", headers=headers, body=body, timeout=HTTP_TIMEOUT)
    dt_ms = int((time.perf_counter() - t0) * 1000)
    if not ok:
        st, reason = classify_status(code, err, data)
        return False, dt_ms, err or f"HTTP {code}", st, reason, data

    text = _extract_text(style, data)
    # 宽松：有 choices/message 结构，或有非空文本
    has_structure = False
    if isinstance(data, dict):
        if style == "ollama" and "message" in data:
            has_structure = True
        elif style == "anthropic" and "content" in data:
            has_structure = True
        elif style == "gemini" and "candidates" in data:
            has_structure = True
        elif "choices" in data:
            has_structure = True

    if not has_structure and not (text and str(text).strip()):
        return False, dt_ms, "empty response", "empty_response", "响应无内容", data

    # 部分 thinking 模型 content 为空但结构 OK — 仍算可用
    return True, dt_ms, None, "ok", "正常", data


def probe_model_with_retries(prov, api_key, model, probes):
    """对单个模型：429 有限重试；成功则多探针取中位时延。"""
    lats = []
    last_err = last_status = last_reason = None
    attempts = 0
    max_attempts = max(1, probes) + MAX_429_RETRIES

    while attempts < max_attempts and len(lats) < max(1, probes):
        attempts += 1
        ok, dt, err, st, reason, _body = probe_once(prov, api_key, model)
        if ok:
            lats.append(dt)
            continue
        last_err, last_status, last_reason = err, st, reason
        if st == "rate_limited" and attempts < max_attempts:
            time.sleep(RATE_LIMIT_BACKOFF_SEC * attempts)
            continue
        # 不可恢复错误：模型不存在/鉴权/余额/端点错误 — 立刻换模型
        if st in ("model_unavailable", "auth_invalid", "balance", "payment_required",
                  "forbidden", "bad_endpoint", "dns"):
            break
        # timeout/server_error 可再试一次
        if st in ("timeout", "server_error") and attempts < max_attempts:
            time.sleep(0.5)
            continue
        break

    if not lats:
        return False, None, last_err, last_status, last_reason
    return True, int(statistics.median(lats)), None, "ok", "正常"


def test_provider(prov, api_key, probes, do_discover, max_models):
    key_name = prov.get("key")
    style = prov.get("style")
    base = prov["base_url"]
    log(f"probe {prov.get('name', key_name)} ({base}) ...")

    available_ids = None
    free_ids = []
    if do_discover:
        # ollama 本地/云都可拉 tags；openai 系需要 key（gemini/anthropic 同理）
        if style == "ollama" or (api_key and style in ("openai", "anthropic", "gemini")):
            available_ids, free_ids = list_models(prov, api_key)
            if available_ids:
                log(f"  · catalog: {len(available_ids)} models"
                    + (f", free≈{len(free_ids)}" if free_ids else ""))

    # 允许配置覆盖 max models
    prov = dict(prov)
    prov["max_models"] = max_models
    candidates = build_model_candidates(prov, available_ids, free_ids)
    if not candidates:
        return {
            "key": key_name, "name": prov.get("name", key_name), "available": False,
            "latency_ms": None, "model": prov.get("test_model"), "error": "无候选模型",
            "status": "no_model", "reason": "无候选模型", "local": prov.get("local", False),
            "tried_models": [],
        }

    log(f"  · candidates: {', '.join(candidates)}")
    tried = []
    last = None
    for mid in candidates:
        ok, lat, err, st, reason = probe_model_with_retries(prov, api_key, mid, probes)
        tried.append({"model": mid, "ok": ok, "latency_ms": lat, "status": st, "error": err})
        if ok:
            log(f"  · OK  model={mid}  median={lat} ms")
            return {
                "key": key_name, "name": prov.get("name", key_name), "available": True,
                "latency_ms": lat, "model": mid, "error": None,
                "status": "ok", "reason": "正常", "local": prov.get("local", False),
                "tried_models": tried,
            }
        last = (mid, err, st, reason)
        log(f"  · fail model={mid}: {reason or err}", "WARN")
        # 账户级失败：换模型也没用，直接放弃该提供者
        if st in ("auth_invalid", "dns", "balance", "payment_required"):
            break
        # 403 且 body 已判为 balance 时上面已覆盖；纯 forbidden 若连续也可能是账户问题
        if st == "forbidden" and any(
            h in (err or "").lower() for h in ("balance", "insufficient", "quota")
        ):
            break

    mid, err, st, reason = last if last else (candidates[0], "unknown", "error", "失败")
    return {
        "key": key_name, "name": prov.get("name", key_name), "available": False,
        "latency_ms": None, "model": mid, "error": err,
        "status": st, "reason": reason, "local": prov.get("local", False),
        "tried_models": tried,
    }


# --------------------------------------------------------------------------- #
# 选择
# --------------------------------------------------------------------------- #
def select(results, threshold_ms, ollama_models=None, prov_catalog=None, api_keys=None):
    prov_catalog = prov_catalog or []
    api_keys = api_keys or {}
    ollama_models = ollama_models or []

    ollama_ok = [r for r in results if r.get("local") and r["available"]]
    remote_ok = [
        r for r in results
        if not r.get("local") and r["available"] and (r["latency_ms"] or 10**9) <= threshold_ms
    ]
    remote_ok.sort(key=lambda r: (r["latency_ms"] or 10**9))

    if remote_ok:
        primary = remote_ok[0]
    elif ollama_ok:
        primary = sorted(ollama_ok, key=lambda r: r["latency_ms"] or 0)[0]
        log(f"no healthy remote under {threshold_ms}ms, primary fallback to local Ollama: {primary['model']}", "WARN")
    else:
        # 全部失败：若有已配置密钥的远端，暂用其 test 结果模型（不可用标记）
        cfg_remote = [p for p in prov_catalog if api_keys.get(p["key"]) and not p.get("local")]
        if cfg_remote:
            p = cfg_remote[0]
            mid = next((r["model"] for r in results if r["key"] == p["key"] and r.get("model")), p.get("test_model"))
            primary = {
                "key": p["key"], "name": p.get("name", p["key"]), "model": mid,
                "latency_ms": None, "local": False, "available": False,
            }
            log(f"all probes failed; temporary primary={primary['key']}/{primary['model']}", "WARN")
        else:
            return None, None, "没有任何可用端点（远端与本地 Ollama 均不可用）"

    primary_ref = f"{primary['key']}/{primary['model']}"
    fb = []
    seen = set()

    def add_ref(ref):
        if ref and ref != primary_ref and ref not in seen:
            fb.append(ref)
            seen.add(ref)

    # 1) 本地 Ollama 全部模型优先备用
    for mid in ollama_models:
        add_ref(f"ollama/{mid}")

    # 2) 其他实测可用远端（按时延）
    for r in remote_ok:
        add_ref(f"{r['key']}/{r['model']}")

    # 3) 限流但仍可能可用的远端（排在可用之后）
    for r in results:
        if r.get("local") or not r.get("model"):
            continue
        if r.get("status") == "rate_limited" and api_keys.get(r["key"]):
            add_ref(f"{r['key']}/{r['model']}")

    # 4) 其余有密钥的远端：仅纳入「有可能恢复」的状态，避免把余额耗尽/密钥作废写进 fallbacks
    recoverable = {"rate_limited", "timeout", "server_error", "empty_response", "error", "http_error"}
    for r in results:
        if r.get("local") or not api_keys.get(r["key"]) or not r.get("model"):
            continue
        if r.get("available"):
            continue
        if r.get("status") in recoverable:
            add_ref(f"{r['key']}/{r['model']}")

    return primary, fb, None


# --------------------------------------------------------------------------- #
# 写入 openclaw.json
# --------------------------------------------------------------------------- #
def ensure_provider(cfg, prov, api_key):
    pkey = prov["key"]
    oc_api = prov.get("openclaw_api")
    provs = cfg.setdefault("models", {}).setdefault("providers", {})
    block = provs.get(pkey)
    if block is None:
        block = {"baseUrl": prov["base_url"]}
        if api_key:
            block["apiKey"] = api_key
        if oc_api:
            block["api"] = oc_api
        block["models"] = []
        provs[pkey] = block
    else:
        block["baseUrl"] = prov["base_url"]
        if api_key:
            # 始终用最新密钥（env 优先路径已在 get_api_key 处理）
            block["apiKey"] = api_key
        if oc_api:
            block["api"] = oc_api
        elif "api" in block and prov.get("style") == "ollama":
            # ollama 原生协议不需要 openai api 字段
            block.pop("api", None)
        block.setdefault("models", [])
    return block, oc_api


def ensure_model(block, model_id, name, oc_api, ctx):
    for m in block["models"]:
        if m.get("id") == model_id:
            # 刷新显示名/上下文
            m["name"] = name
            if ctx:
                m["contextWindow"] = ctx
            if oc_api:
                m["api"] = oc_api
            return
    entry = {
        "id": model_id,
        "name": name,
        "reasoning": False,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": ctx,
        "maxTokens": 8192,
    }
    if oc_api:
        entry["api"] = oc_api
    block["models"].append(entry)


def promote_model_first(block, model_id):
    """把验证成功的模型挪到列表前面，方便 UI/默认选择。"""
    models = block.get("models") or []
    hit = [m for m in models if m.get("id") == model_id]
    rest = [m for m in models if m.get("id") != model_id]
    if hit:
        block["models"] = hit + rest


def _ollama_models(provs, do_discover):
    for p in provs:
        if p.get("local") or p.get("key") == "ollama":
            if do_discover:
                try:
                    ids, _ = list_models(p, None)
                    if ids:
                        log(f"local Ollama models: {', '.join(ids)}")
                        return ids
                except Exception:
                    pass
            try:
                with open(DEFAULT_CONFIG, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                ms = cfg.get("models", {}).get("providers", {}).get("ollama", {}).get("models", [])
                return [m.get("id") for m in ms if m.get("id")]
            except Exception:
                return []
    return []


def ensure_alias(cfg, ref, alias):
    models_map = cfg.setdefault("agents", {}).setdefault("defaults", {}).setdefault("models", {})
    if ref not in models_map:
        models_map[ref] = {"alias": alias}


def apply_selection(cfg, prov_catalog, api_keys, results, primary, fallbacks):
    def find_prov(ref):
        pkey = ref.split("/", 1)[0]
        for p in prov_catalog:
            if p["key"] == pkey:
                return p
        return None

    def discovered_model(pkey):
        return next((r["model"] for r in results if r["key"] == pkey and r.get("model")), None)

    result_by_key = {r["key"]: r for r in results}

    for p in prov_catalog:
        if p.get("local"):
            k = None
        else:
            k = api_keys.get(p["key"])
            if not k:
                continue
        mid = discovered_model(p["key"]) or p.get("test_model")
        if not mid:
            continue
        block, oc_api = ensure_provider(cfg, p, k)
        ensure_model(
            block, mid, f"{p.get('name', p['key'])} / {mid}",
            oc_api, p.get("context_window", 128000),
        )
        # 成功的模型置顶
        r = result_by_key.get(p["key"])
        if r and r.get("available"):
            promote_model_first(block, mid)
        ensure_alias(cfg, f"{p['key']}/{mid}", p["key"])

    # primary / fallbacks 再确保一遍
    for ref in [f"{primary['key']}/{primary['model']}"] + list(fallbacks or []):
        pprov = find_prov(ref)
        if not pprov:
            continue
        block, oc_api = ensure_provider(cfg, pprov, api_keys.get(pprov["key"]))
        mid = ref.split("/", 1)[1]
        ensure_model(
            block, mid, f"{pprov.get('name', pprov['key'])} / {mid}",
            oc_api, pprov.get("context_window", 128000),
        )
        ensure_alias(cfg, ref, pprov["key"])

    primary_ref = f"{primary['key']}/{primary['model']}"
    defaults = cfg.setdefault("agents", {}).setdefault("defaults", {})
    defaults["model"] = {"primary": primary_ref, "fallbacks": fallbacks}
    for ag in cfg.get("agents", {}).get("list", []) or []:
        if isinstance(ag, dict) and "model" in ag:
            ag["model"] = {"primary": primary_ref, "fallbacks": list(fallbacks)}


def write_markdown_report(results, primary, fallbacks, threshold_ms):
    lines = [
        "# OpenClaw API 优选 — 探测结果",
        "",
        f"运行时间: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}  |  时延阈值: {threshold_ms} ms",
        "",
        "## 汇总",
        "",
        "| 提供者 | 可用 | 时延(ms) | 选用模型 | 状态/原因 |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        avail = "是" if r.get("available") else "否"
        lat = r.get("latency_ms") if r.get("latency_ms") is not None else "-"
        model = r.get("model") or "-"
        reason = r.get("reason") or r.get("error") or ""
        lines.append(f"| {r.get('name', r.get('key'))} | {avail} | {lat} | `{model}` | {reason} |")

    lines.append("")
    if primary:
        lines.append(f"## 结论")
        lines.append(f"- 主用 (primary): **{primary['key']}/{primary['model']}**"
                     + (f"（{primary.get('latency_ms')} ms）" if primary.get("latency_ms") is not None else ""))
        lines.append(f"- 备用 (fallbacks): {', '.join(fallbacks) if fallbacks else '(无)'}")
    lines.append("")
    lines.append("## 级联尝试明细")
    lines.append("")
    for r in results:
        tried = r.get("tried_models") or []
        if not tried:
            continue
        lines.append(f"### {r.get('name', r.get('key'))}")
        for t in tried:
            mark = "OK" if t.get("ok") else "FAIL"
            lat = t.get("latency_ms")
            extra = f"{lat} ms" if lat is not None else (t.get("status") or t.get("error") or "")
            lines.append(f"- `{t.get('model')}` → {mark} {extra}")
        lines.append("")

    with open(REPORT_MD_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="OpenClaw API 优选器")
    ap.add_argument("--config", default=DEFAULT_CONFIG, help="openclaw.json 路径")
    ap.add_argument("--providers", default=DEFAULT_PROVIDERS_FILE, help="providers.json 路径")
    ap.add_argument("--dry-run", action="store_true", help="只探测与计算，不修改配置")
    ap.add_argument("--threshold", type=int, default=LATENCY_THRESHOLD_MS, help="主用时延阈值(ms)")
    ap.add_argument("--probes", type=int, default=PROBES, help="每模型成功后的测速次数")
    ap.add_argument("--max-models", type=int, default=MAX_MODELS_PER_PROVIDER, help="每提供者最多尝试模型数")
    ap.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL, help="并行探测提供者数 (1=串行)")
    ap.add_argument("--no-discover", action="store_true", help="不拉取实时 /models 目录")
    ap.add_argument("--report", choices=["json", "none"], default="json")
    args = ap.parse_args()

    do_discover = not args.no_discover
    load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

    if not os.path.exists(args.config):
        log(f"openclaw config not found: {args.config}", "ERROR")
        sys.exit(2)
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    provs = [p for p in load_providers(args.providers) if p.get("enabled", True)]

    api_keys = {}
    for p in provs:
        k = get_api_key(p, cfg)
        api_keys[p["key"]] = k
        if k:
            log(f"  {p['key']}: key ready")
        elif p.get("local"):
            log(f"  {p['key']}: local, no key needed")
        else:
            log(f"  {p['key']}: no key (set {p.get('api_key_env')})", "WARN")

    log("start probing ...")
    results = []
    work = []
    for p in provs:
        k = api_keys.get(p["key"])
        if not k and not p.get("local"):
            results.append({
                "key": p["key"], "name": p.get("name", p["key"]), "available": False,
                "latency_ms": None, "model": p.get("test_model"),
                "error": "缺少 API 密钥", "status": "no_key", "reason": "未配置密钥·跳过",
                "local": p.get("local", False), "tried_models": [],
            })
            continue
        work.append((p, k))

    def _run_one(item):
        p, k = item
        try:
            return test_provider(p, k, max(1, args.probes), do_discover, max(1, args.max_models))
        except Exception as e:
            return {
                "key": p["key"], "name": p.get("name", p["key"]), "available": False,
                "latency_ms": None, "model": p.get("test_model"), "error": str(e)[:120],
                "status": "error", "reason": str(e)[:80],
                "local": p.get("local", False), "tried_models": [],
            }

    if args.parallel <= 1 or len(work) <= 1:
        for item in work:
            results.append(_run_one(item))
    else:
        # 保持与 providers 顺序大致一致：并行执行后按 key 归位
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.parallel)) as ex:
            futs = {ex.submit(_run_one, item): item[0]["key"] for item in work}
            got = {}
            for fut in concurrent.futures.as_completed(futs):
                key = futs[fut]
                got[key] = fut.result()
        for p, _k in work:
            results.append(got[p["key"]])

    # 把无密钥结果与探测结果按 providers 原始顺序重排
    by_key = {r["key"]: r for r in results}
    ordered = []
    for p in provs:
        if p["key"] in by_key:
            ordered.append(by_key[p["key"]])
    results = ordered

    ollama_models = _ollama_models(provs, do_discover)
    primary, fallbacks, err = select(
        results, args.threshold,
        ollama_models=ollama_models,
        prov_catalog=provs,
        api_keys=api_keys,
    )
    if err:
        log(f"selection failed: {err}", "ERROR")

    print("\n========== PROBE RESULTS ==========")
    print(f"{'Provider':<28}{'OK':<4}{'ms':<8}{'Model / Reason'}")
    for r in results:
        avail = "Y" if r["available"] else "N"
        lat = str(r["latency_ms"]) if r["latency_ms"] is not None else "-"
        tail = r.get("model") or ""
        if not r["available"]:
            tail = f"{tail} | {r.get('reason') or r.get('error') or ''}"
        print(f"{(r.get('name') or r['key'])[:26]:<28}{avail:<4}{lat:<8}{tail}")
    if primary:
        print("\n>>> primary:", f"{primary['key']}/{primary['model']}",
              f"({primary['latency_ms']} ms)" if primary.get("latency_ms") is not None else "")
        print(">>> fallbacks:", ", ".join(fallbacks) if fallbacks else "(none)")
    print("===================================\n")

    if args.report != "none":
        report = {
            "run_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "threshold_ms": args.threshold,
            "results": results,
            "primary": (f"{primary['key']}/{primary['model']}" if primary else None),
            "fallbacks": fallbacks,
        }
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        write_markdown_report(results, primary, fallbacks, args.threshold)
        log(f"report -> {REPORT_FILE}")
        log(f"markdown -> {REPORT_MD_FILE}")

    if args.dry_run:
        log("DRY-RUN: config not modified.")
        sys.exit(0 if primary else 3)
    if not primary:
        log("no usable endpoint; keep existing config.", "ERROR")
        sys.exit(3)

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = args.config + f".bak-{stamp}"
    shutil.copy2(args.config, bak)
    log(f"backup -> {bak}")

    apply_selection(cfg, provs, api_keys, results, primary, fallbacks)
    with open(args.config, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    log(f"updated {args.config}: primary={primary['key']}/{primary['model']}")
    log("restart OpenClaw gateway if it does not hot-reload config.")
    sys.exit(0)


if __name__ == "__main__":
    main()
